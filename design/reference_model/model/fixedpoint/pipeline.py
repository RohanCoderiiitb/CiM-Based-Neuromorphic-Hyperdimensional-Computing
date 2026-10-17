"""Shared run/compare/measure logic (used by run_phase0.py and the tests)."""
import contextlib
import numpy as np
import torch
import _paths  # noqa: F401
import neurohdc
from neurohdc import NeuroHDC
from int_model import snn_forward_batch, predict, xnor_scores_prefix
from quantize import thresholds, granularity_for
from bounds import bits_unsigned, bits_signed


@contextlib.contextmanager
def quantizer(per_channel):
    """Run the (unmodified) float model with the quantizer granularity a checkpoint was trained with.
    NeuroHDC.forward resolves the module-level name `fake_quant_int8` at call time, so rebinding it
    here is enough; neurohdc.py itself is not edited."""
    orig = neurohdc.fake_quant_int8
    neurohdc.fake_quant_int8 = lambda w, per_channel=per_channel: orig(w, per_channel=per_channel)
    try:
        yield
    finally:
        neurohdc.fake_quant_int8 = orig


def float_run(ckpt, frames, bs=32, per_channel=None):
    per_channel = granularity_for(ckpt) if per_channel is None else per_channel
    m = NeuroHDC(n=20, T=100, n_input=512, n_classes=10)
    m.load_state_dict(torch.load(ckpt, map_location="cpu")); m.eval()
    S, P = [], []
    with torch.no_grad(), quantizer(per_channel):
        for i in range(0, len(frames), bs):
            sc, r = m(torch.from_numpy(frames[i:i + bs]))
            S.append(r.numpy().astype(np.uint8)); P.append(sc.argmax(1).numpy())
    return np.concatenate(S), np.concatenate(P).astype(np.int16)


def int_run(prm, counts, N_e=None, normalised=False):
    """Integer model over a batch. For input-normalised models (N-MNIST) the threshold is
    ceil(v_thresh * N_e / s_j) per sample (N_e = max(N_e,1))."""
    if normalised:
        thr = np.stack([thresholds(prm.v_thresh, prm.scale, max(int(n), 1)) for n in N_e])
    else:
        thr = prm.thresh_int
    tr = snn_forward_batch(counts, prm.W, thr)
    pred = np.array([predict(tr.S[i], prm.class_hv)[0] for i in range(len(counts))], np.int16)
    return tr, np.broadcast_to(thr, (len(counts), 20)), pred


def compare(S_int, S_ref, tr, thr, n_listed=25):
    """Bit-for-bit raster comparison. Differing spikes are explained by their exact integer
    margin Vp_int - thresh_int at the FIRST divergence of each (sample, neuron) trajectory
    (later differences in the same trajectory are knock-on effects of the different reset)."""
    d = S_int != S_ref
    per_sample = d.reshape(len(d), -1).sum(1)
    first = []
    for b, j in zip(*np.nonzero(d.any(axis=1))):
        t = int(np.argmax(d[b, :, j]))
        first.append(dict(sample=int(b), t=t, neuron=int(j), int_spike=int(S_int[b, t, j]),
                          ref_spike=int(S_ref[b, t, j]),
                          margin_int=int(tr.Vp[b, t, j] - thr[b, j])))
    m = tr.Vp - np.asarray(thr)[:, None, :]
    return dict(n_samples=int(len(d)), samples_bit_exact=int((per_sample == 0).sum()),
                # tightest integer margins seen: Vp == thresh fires only because the compare is '>=';
                # Vp == thresh-1 is the closest non-firing case. Float rounding would show up here first.
                n_margin_eq0=int((m == 0).sum()), n_margin_eq_minus1=int((m == -1).sum()),
                differing_spikes=int(d.sum()), spikes_compared=int(d.size),
                diverged_trajectories=len(first),
                first_divergences=first[:n_listed],
                max_abs_first_margin=(max(abs(f["margin_int"]) for f in first) if first else None),
                differing_samples=[int(i) for i in np.nonzero(per_sample)[0]])


def measure(counts, tr):
    """True maxima. `Vp` is the adder output (pre-reset) and sets the datapath width;
    `V` is the stored register."""
    return dict(c_max=int(counts.max()), x_min=int(tr.X.min()), x_max=int(tr.X.max()),
                vp_min=int(tr.Vp.min()), vp_max=int(tr.Vp.max()),
                v_min=int(tr.V.min()), v_max=int(tr.V.max()),
                sum_c_per_step_max=int(counts.astype(np.int64).sum(-1).max()))


def widths(m):
    return dict(W_COUNT=bits_unsigned(m["c_max"]),
                W_X=bits_signed(m["x_min"], m["x_max"]),
                W_V=bits_signed(min(m["vp_min"], m["v_min"]), max(m["vp_max"], m["v_max"])))


def merge_measure(ms):
    return dict(c_max=max(m["c_max"] for m in ms), x_min=min(m["x_min"] for m in ms),
                x_max=max(m["x_max"] for m in ms), vp_min=min(m["vp_min"] for m in ms),
                vp_max=max(m["vp_max"] for m in ms), v_min=min(m["v_min"] for m in ms),
                v_max=max(m["v_max"] for m in ms),
                sum_c_per_step_max=max(m["sum_c_per_step_max"] for m in ms))
