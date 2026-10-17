"""
Faithful-as-possible reimplementation of NeuroHDC (Yu et al., IEEE TVLSI 2026)
for the sole purpose of capturing and characterizing the output spike raster
S in {0,1}^{n x T}.

No official code or checkpoint exists for NeuroHDC (see README.md section 13.1
and firing_rate_experiment_spec.md, blockers B1-B3). This module is a full
reimplementation, not a reproduction. Every design choice that the paper does
not specify is called out with a "CHOICE:" comment and documented in
firing_rate_results.md.

Faithful-by-construction properties (do not violate these, see README.md
section 10):
  - Events are binned into T timesteps by EQUAL EVENT COUNT, not wall-clock time.
  - SumPool is implemented exactly as address generation (eq. 19 in the paper):
    addr = p*256 + floor(y*16/H)*16 + floor(x*16/W). No frame is ever pooled
    with a lossy spatial filter; this is address truncation.
  - The neuron is IF (not LIF): V_p(t) = V(t-1) + X(t), hard reset to 0, no leak,
    no bias.
  - The SNN weights W_s are quantized to signed int8 via a straight-through
    fake-quantizer (QAT), consistent with the paper's use of QAT [ref 36].
  - The hypervector is direct concatenation of spikes (eq. 7): nothing sits
    between the raster and the flatten operation.
  - The class hypervectors are C = Sign(W_c), trained jointly with the SNN via
    gradient descent (Mode 1 in the paper, section IV-D/IV-E), using a
    straight-through estimator for Sign().
"""
import math
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset


# ----------------------------------------------------------------------------
# Event -> [T, 512] SumPooled-by-address-generation frame tensor
# ----------------------------------------------------------------------------

def events_to_frames(x, y, p, T, H, W, beta_grid=16):
    """
    Implements NeuroHDC eq. (8) [equal-event-count binning] composed with
    eq. (19) [SumPool as address generation], exactly as described for the
    HARDWARE inference path (paper section V-B): the pooled 2x16x16 frame is
    never materialized as a spatial array; each event is independently
    translated into one of 512 addresses and accumulated.

    Returns
    -------
    frames : float32 [T, 512]   D_flat(t), the SumPooled count image per timestep
    n_events : int              total number of events in the sample
    N_e : int                   floor(n_events / T), nominal events/timestep
    """
    n_events = len(x)
    frames = np.zeros((T, 2 * beta_grid * beta_grid), dtype=np.float32)
    if n_events == 0:
        return frames, 0, 0

    x = np.minimum(x.astype(np.int64), W - 1)
    y = np.minimum(y.astype(np.int64), H - 1)
    p = p.astype(np.int64)

    col = np.minimum((x * beta_grid) // W, beta_grid - 1)
    row = np.minimum((y * beta_grid) // H, beta_grid - 1)
    addr = p * (beta_grid * beta_grid) + row * beta_grid + col  # 0..511

    # Equal-event-count binning: event index k (already time-sorted) goes to
    # bin floor(k*T/n_events). Bin sizes differ by at most 1 event -- this is
    # the vectorized equivalent of splitting the sorted event array into T
    # contiguous, (as close as possible to) equal-count chunks.
    k = np.arange(n_events)
    bin_idx = np.minimum((k * T) // n_events, T - 1)

    flat_idx = bin_idx * (2 * beta_grid * beta_grid) + addr
    counts = np.bincount(flat_idx, minlength=T * 2 * beta_grid * beta_grid).astype(np.float32)
    frames = counts.reshape(T, 2 * beta_grid * beta_grid)

    N_e = n_events // T
    return frames, n_events, N_e


# ----------------------------------------------------------------------------
# Dataset: N-MNIST (raw AER .bin files, standard Orchard et al. format)
# ----------------------------------------------------------------------------

def _read_nmnist_bin(path):
    raw = np.fromfile(path, dtype=np.uint8)
    n = (len(raw) // 5) * 5
    raw = raw[:n].reshape(-1, 5)
    x = raw[:, 0].astype(np.int64)
    y = raw[:, 1].astype(np.int64)
    p = (raw[:, 2] >> 7).astype(np.int64)
    t = ((raw[:, 2] & 0x7F).astype(np.int64) << 16) | (raw[:, 3].astype(np.int64) << 8) | raw[:, 4].astype(np.int64)
    order = np.argsort(t, kind="stable")
    return x[order], y[order], p[order], t[order]


class NMNISTDataset(Dataset):
    SENSOR_H = 34
    SENSOR_W = 34

    def __init__(self, root, T=100, input_scaling="per_sample_norm", limit_per_class=None, seed=0):
        self.T = T
        self.input_scaling = input_scaling
        self.samples = []  # (path, label)
        rng = np.random.RandomState(seed)
        for label in range(10):
            cdir = f"{root}/{label}"
            files = sorted(__import__("os").listdir(cdir))
            files = [f for f in files if f.endswith(".bin")]
            if limit_per_class is not None and len(files) > limit_per_class:
                idx = rng.choice(len(files), limit_per_class, replace=False)
                files = [files[i] for i in idx]
            for f in files:
                self.samples.append((f"{cdir}/{f}", label))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        path, label = self.samples[i]
        x, y, p, t = _read_nmnist_bin(path)
        frames, n_events, N_e = events_to_frames(x, y, p, self.T, self.SENSOR_H, self.SENSOR_W)
        if self.input_scaling == "per_sample_norm":
            denom = max(N_e, 1)
            frames = frames / denom
        elif self.input_scaling == "clip":
            frames = np.clip(frames, 0, 10)
        # "raw": leave as-is
        return torch.from_numpy(frames), label, n_events, N_e


# ----------------------------------------------------------------------------
# Dataset: DVS-Gesture, pre-segmented per-instance .npy event arrays
# columns: [x, y, p, t(seconds)]. 11th class ("Other", label index 10) excluded.
# ----------------------------------------------------------------------------

class DVSGestureDataset(Dataset):
    SENSOR_H = 128
    SENSOR_W = 128

    def __init__(self, root, T=100, input_scaling="raw", event_dropout=0.0, users=None):
        """
        input_scaling: "raw" is the paper-faithful default (eq. 16 uses
            D_flat(t) directly, unnormalized -- see
            neurohdc_implementation_audit.md row B-13). "per_sample_norm" is
            OUR CHOICE, not paper-supported, kept only for the controlled A/B
            comparison in dvs_accuracy_report.md.
        users: optional iterable of user-id prefixes (e.g. {"user01"}) to
            restrict this dataset to. Used to carve a held-out validation
            split out of the official training users without ever touching
            the official test-user split. None = use every user directory
            under `root`.
        """
        import os
        self.T = T
        self.input_scaling = input_scaling
        # OUR CHOICE: event_dropout is a training-only augmentation (randomly
        # drop each event independently with this probability before
        # binning), not part of the paper. Defaults to 0.0 (disabled).
        self.event_dropout = event_dropout
        self.samples = []  # (path, label)
        for user_dir in sorted(os.listdir(root)):
            full = f"{root}/{user_dir}"
            if not __import__("os").path.isdir(full):
                continue
            user_id = user_dir.split("_")[0]
            if users is not None and user_id not in users:
                continue
            for f in os.listdir(full):
                if not f.endswith(".npy"):
                    continue
                label = int(f[:-4])
                if label == 10:  # "Other" class excluded, per README section 4.4 / paper section IV-A
                    continue
                self.samples.append((f"{full}/{f}", label))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        path, label = self.samples[i]
        ev = np.load(path)
        x = ev[:, 0]
        y = ev[:, 1]
        p = ev[:, 2]
        t = ev[:, 3]
        order = np.argsort(t, kind="stable")
        x, y, p = x[order], y[order], p[order]
        if self.event_dropout > 0:
            keep = np.random.rand(len(x)) >= self.event_dropout
            if keep.sum() > 0:
                x, y, p = x[keep], y[keep], p[keep]
        frames, n_events, N_e = events_to_frames(x, y, p, self.T, self.SENSOR_H, self.SENSOR_W)
        if self.input_scaling == "per_sample_norm":
            denom = max(N_e, 1)
            frames = frames / denom
        elif self.input_scaling == "clip":
            frames = np.clip(frames, 0, 10)
        return torch.from_numpy(frames), label, n_events, N_e


def collate(batch):
    frames = torch.stack([b[0] for b in batch]).float()
    labels = torch.tensor([b[1] for b in batch], dtype=torch.long)
    n_events = torch.tensor([b[2] for b in batch], dtype=torch.long)
    N_e = torch.tensor([b[3] for b in batch], dtype=torch.long)
    return frames, labels, n_events, N_e


# ----------------------------------------------------------------------------
# Straight-through estimators
# ----------------------------------------------------------------------------

class ATanSpike(torch.autograd.Function):
    """Heaviside forward, ATan surrogate gradient backward (SpikingJelly-style)."""

    @staticmethod
    def forward(ctx, v_minus_thresh, alpha):
        ctx.save_for_backward(v_minus_thresh)
        ctx.alpha = alpha
        return (v_minus_thresh >= 0).float()

    @staticmethod
    def backward(ctx, grad_output):
        (x,) = ctx.saved_tensors
        alpha = ctx.alpha
        grad = alpha / 2.0 / (1.0 + (math.pi / 2.0 * alpha * x) ** 2) * grad_output
        return grad, None


def fake_quant_int8(w, per_channel=True):
    """
    Straight-through 8-bit signed fake quantizer.

    per_channel=True (OUR CHOICE, now the default): one scale per output row
    (per IF neuron for Ws). This is arguably MORE faithful to the paper's own
    hardware description (neurohdc_implementation_audit.md row B-1/15) than a
    single global scale: eq./text in Section V-A states each neuron's 512
    weights are stored independently in that neuron's own SRAM macro, which
    naturally implies each neuron's weights are quantized with their own
    scale, not one scale shared across all 20 neurons. A single global
    per-tensor scale (per_channel=False, the previous default) lets one
    outlier weight in any neuron coarsen the quantization resolution for
    every other neuron's weights.
    """
    if per_channel and w.dim() == 2:
        scale = w.detach().abs().amax(dim=1, keepdim=True).clamp_min(1e-8) / 127.0
    else:
        scale = w.detach().abs().max().clamp_min(1e-8) / 127.0
    wq = torch.round(w / scale).clamp(-127, 127) * scale
    return w + (wq - w).detach()


def sign_ste(w):
    s = torch.sign(w)
    s = torch.where(s == 0, torch.ones_like(s), s)
    return w + (s - w).detach()


# ----------------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------------

class NeuroHDC(nn.Module):
    def __init__(self, n=20, T=100, n_input=512, n_classes=10, alpha=2.0,
                 v_thresh_init=1.0, head_dropout=0.0):
        super().__init__()
        self.n = n
        self.T = T
        self.n_input = n_input
        self.n_classes = n_classes
        self.alpha = alpha
        # OUR CHOICE: standard dropout applied to the flattened hypervector
        # ONLY during training, before the class-HV score. Targets the
        # classifier head specifically (Wc has n*T*n_classes = 20,000
        # parameters for only 769 DVS-Gesture training samples). Disabled
        # (identity) in eval(), so the DEPLOYED/inference dataflow is exactly
        # "flatten then score" -- this does not add any operation between the
        # raster and the score at inference time, and does not rate-collapse
        # spikes (README.md section 10, invariant 1); it only randomly zeroes
        # training-time gradients through a subset of dimensions per step,
        # exactly as standard dropout does before any fully-connected layer.
        self.head_dropout = head_dropout
        self.Ws = nn.Parameter(torch.randn(n, n_input) * (1.0 / math.sqrt(n_input)))
        # CHOICE (resolves U1/B5, the paper never states V_thresh): V_thresh is
        # trained jointly with all other parameters via gradient descent,
        # rather than hand-picked or exhaustively swept. This measures the
        # firing rate that the paper's own training objective (cross-entropy
        # on the downstream classifier) naturally converges to, which is the
        # most defensible stand-in for a value the paper calls a "configuration
        # register" but never publishes. See firing_rate_results.md, "Limitations".
        self._v_thresh_raw = nn.Parameter(torch.tensor(math.log(math.exp(v_thresh_init) - 1.0)))
        self.Wc = nn.Parameter(torch.randn(n_classes, n * T) * 0.01)

    @property
    def v_thresh(self):
        return torch.nn.functional.softplus(self._v_thresh_raw) + 1e-3

    @torch.no_grad()
    def calibrate_threshold(self, sample_frames):
        """
        OUR CHOICE (initialization-only heuristic, label-free): set the
        INITIAL v_thresh so the randomly-initialized Ws produces a
        roughly-balanced firing rate on a calibration batch instead of
        saturating all-on or all-off, then let gradient descent take over.
        This matters because under "raw" (paper-faithful, unnormalized)
        input scaling, X(t)'s magnitude differs by ~2 orders of magnitude
        between N-MNIST and DVS-Gesture (see
        neurohdc_implementation_audit.md row B-1), and a single fixed
        default init is badly mismatched for one or the other. v_thresh
        remains fully trainable afterward -- this only changes where
        gradient descent starts.
        """
        Wq = fake_quant_int8(self.Ws)
        X = sample_frames.reshape(-1, self.n_input) @ Wq.t()
        med = X.abs().median().clamp_min(1e-3)
        self._v_thresh_raw.copy_(torch.log(torch.expm1(med)))

    def forward(self, frames):
        # frames: [B, T, n_input]
        B = frames.shape[0]
        device = frames.device
        Wq = fake_quant_int8(self.Ws)
        V = torch.zeros(B, self.n, device=device)
        raster = torch.empty(B, self.T, self.n, device=device)
        vth = self.v_thresh
        for t in range(self.T):
            X = frames[:, t, :] @ Wq.t()
            Vp = V + X
            S = ATanSpike.apply(Vp - vth, self.alpha)
            V = Vp * (1.0 - S)  # hard reset to 0 on spike, no leak
            raster[:, t, :] = S
        h_u = raster.reshape(B, self.T * self.n)
        h_b = 2.0 * h_u - 1.0
        if self.training and self.head_dropout > 0:
            h_b = torch.nn.functional.dropout(h_b, p=self.head_dropout, training=True)
        C = sign_ste(self.Wc)
        # CHOICE: scale by 1/sqrt(D_hv) so cross-entropy logits are O(1-10)
        # rather than O(D_hv). This is a training-stability temperature only;
        # it is a monotonic rescaling and does not change argmax(scores), so
        # it does not alter eq. (9)'s decision rule.
        scores = (h_b @ C.t()) / math.sqrt(self.n * self.T)
        return scores, raster
