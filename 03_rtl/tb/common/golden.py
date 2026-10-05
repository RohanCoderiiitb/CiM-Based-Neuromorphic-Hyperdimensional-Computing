"""Golden-model access and stimulus preparation for the 1E testbenches.

THE GOLDEN MODEL RULE: this module IMPORTS the Phase 0 reference (int_model.py, events.py, export/load_vectors.py). It never
re-implements any of it. Every expected value in every 1E test comes from a call into those modules or from the frozen golden vectors.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
P0 = REPO / "01_integer_reference_model"
VEC = P0 / "tb" / "vectors"
for sub in ("model/fixedpoint", "model/export", "model/neurohdc"):
    p = str(P0 / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import _paths  # noqa: E402,F401  (Phase 0 path bootstrap)
import events as EV  # noqa: E402  (address, bin_sizes, boundary_counter_bins, timestep rules)
import int_model as IM  # noqa: E402  (THE golden model)
import load_vectors as LV  # noqa: E402
from export_weights import read_mem  # noqa: E402,F401  (Phase 0 .mem reader)

T = IM.T_DEFAULT
N_NEURON, N_ADDR = IM.N_NEURON, IM.N_ADDR
GEOM = {"dvsgesture": (128, 128, 0), "nmnist": (34, 34, 1)}      # H, W, geometry flag used by the testbench
AER_SHIFT = {"dvsgesture": 7, "nmnist": 6}


def weight_tag(dataset: str, seed: int) -> str:
    return f"nmnist{seed}" if dataset == "nmnist" else str(seed)


def load_dataset(dataset: str, seed: int):
    """(manifest, counts dict, seed dict with golden spikes/X/V, int8 weights W [20,512])."""
    return LV.load(str(VEC), dataset, seed, weight_tag(dataset, seed))


def reference_trace(counts_row: np.ndarray, W: np.ndarray, thresh_int: np.ndarray) -> IM.SnnTrace:
    """The golden answer for one sample: int_model.snn_forward on the exported count vectors."""
    return IM.snn_forward(counts_row, W, thresh_int)


def weight_mem_files(dataset: str, seed: int) -> list[Path]:
    tag = weight_tag(dataset, seed)
    return [VEC / "weights" / f"weights_seed{tag}_macro{m}_32b.mem" for m in range(5)]


# ------------------------------------------------------------------ event streams
def _preimage(dataset: str):
    """For every grid cell c (0..15) the sensor coordinates that addr_gen must map to c (eq. 19 incl. clamp)."""
    H, W, _ = GEOM[dataset]
    pre = {c: [] for c in range(16)}
    for x in range(W):
        pre[int(min(x * 16 // W, 15))].append(x)
    return pre


def pack_aer(dataset: str, x, y, p):
    sh = AER_SHIFT[dataset]
    return ((np.asarray(p, np.uint32) << (2 * sh)) | (np.asarray(y, np.uint32) << sh) | np.asarray(x, np.uint32)).astype(np.uint16)


def synth_events(dataset: str, counts_row: np.ndarray, rng: np.random.Generator, order: str = "shuffle") -> np.ndarray:
    """AER words (uint16) of a stream whose binned counts equal counts_row [T,512]. Event order inside a timestep is free (the
    integer sum is order independent), so it is a test knob: 'shuffle' (random) or 'sorted' (all events of an address adjacent:
    worst case for the count_mem read-modify-write hazard)."""
    pre = _preimage(dataset)
    words = []
    for t in range(counts_row.shape[0]):
        addr = np.repeat(np.arange(N_ADDR), counts_row[t].astype(np.int64))
        if order == "shuffle":
            rng.shuffle(addr)
        p = addr >> 8
        row = (addr >> 4) & 15
        col = addr & 15
        x = np.empty(len(addr), np.int64); y = np.empty(len(addr), np.int64)
        for c in range(16):
            for arr, sel in ((x, col), (y, row)):
                m = sel == c
                arr[m] = rng.choice(pre[c], size=int(m.sum()))
        words.append(pack_aer(dataset, x, y, p))
    return np.concatenate(words) if words else np.zeros(0, np.uint16)


def unpack_aer(dataset: str, words: np.ndarray):
    sh = AER_SHIFT[dataset]
    w = words.astype(np.int64)
    return w & ((1 << sh) - 1), (w >> sh) & ((1 << sh) - 1), (w >> (2 * sh)) & 1


def check_stream_reproduces_counts(dataset: str, words: np.ndarray, counts_row: np.ndarray) -> bool:
    """Reference-side proof that a stream is a valid input for this sample: decode the AER words with the reference address rule and bin
    them with the reference hardware counter (events.boundary_counter_bins); the result must equal the exported counts exactly."""
    H, W, _ = GEOM[dataset]
    x, y, p = unpack_aer(dataset, words)
    addr = EV.address(x, y, p, H, W)
    t_of = EV.boundary_counter_bins(len(words), T)
    c = np.zeros((T, N_ADDR), np.int64)
    np.add.at(c, (t_of, addr), 1)
    return bool(np.array_equal(c, counts_row))


def real_streams(dataset: str):
    """The raw AER streams Phase 0 exported (20 DVS-Gesture, 1000 N-MNIST): list of (counts_row_index, words, label)."""
    e = np.load(VEC / dataset / "events.npz")
    out = []
    for i, row in enumerate(e["sample_row"]):
        lo, hi = int(e["offset"][i]), int(e["offset"][i + 1])
        out.append((int(row), e["aer"][lo:hi].astype(np.uint16), int(e["label"][i])))
    return out, e


# ------------------------------------------------------------------ job files for the SV testbench
def write_job(job_dir: Path, dataset: str, seed: int, samples: list[tuple[np.ndarray, np.ndarray]], thresholds: list[np.ndarray],
              gap_mode: int = 0, sim_seed: int = 1, gap_seeds: list[int] | None = None) -> None:
    """samples: [(aer words, counts_row)], thresholds: [thresh_int [20]] per sample. Files per the header of tb/sv/snn_regress_tb.sv."""
    job_dir.mkdir(parents=True, exist_ok=True)
    for m, f in enumerate(weight_mem_files(dataset, seed)):
        shutil.copyfile(f, job_dir / f"weights_macro{m}.mem")
    with open(job_dir / "job.txt", "w") as fh:
        fh.write(f"{GEOM[dataset][2]} {len(samples)} {gap_mode} {sim_seed}\n")
        for i, ((words, _), th) in enumerate(zip(samples, thresholds)):
            gs = (gap_seeds[i] if gap_seeds else sim_seed * 7919 + i) & 0x7FFFFFFF
            fh.write(f"{len(words)} " + " ".join(str(int(v)) for v in th) + f" {gs}\n")
    with open(job_dir / "events.bin", "wb") as fh:
        for words, _ in samples:
            fh.write(words.astype(">u2").tobytes())


def parse_output(path: Path):
    """-> list of per-sample dicts: spikes [T,20] u8, X [T,20], V [T,20], stats [T,11], plus the END record."""
    samples, cur = [], None
    for line in open(path):
        f = line.split()
        if not f:
            continue
        if f[0] == "TS":
            s, t = int(f[1]), int(f[2])
            while len(samples) <= s:
                samples.append(dict(rows=[]))
            samples[s]["rows"].append((t, int(f[3], 16), [int(v) for v in f[4:24]], [int(v) for v in f[24:44]], [int(v) for v in f[44:55]]))
        elif f[0] == "END":
            s = int(f[1])
            while len(samples) <= s:
                samples.append(dict(rows=[]))
            samples[s]["end"] = dict(cycles=int(f[2]), stall_cycles=int(f[3]), idle_cycles=int(f[4]), events=int(f[5]), assert_cycles=int(f[6]), ts_seen=int(f[7]))
    out = []
    for sm in samples:
        rows = sorted(sm["rows"])
        S = np.array([[(r[1] >> j) & 1 for j in range(N_NEURON)] for r in rows], np.uint8)
        out.append(dict(t=np.array([r[0] for r in rows]), S=S, X=np.array([r[2] for r in rows], np.int64), V=np.array([r[3] for r in rows], np.int64),
                        stats=np.array([r[4] for r in rows], np.int64), end=sm.get("end")))
    return out


STAT_NAMES = ["events", "active_addrs", "rows_skipped", "rows_read", "reads_allcols", "reads_plane", "reads_issued", "zero_groups", "fwd_events", "cycles", "cycles_ingest"]


def independent_access_estimate(counts_row: np.ndarray, g: int, w_count: int = 11):
    """Access counts predicted from the count vectors alone (no RTL): per timestep active addresses, non-zero / skipped bit-rows, group
    reads in both column assumptions, and the groups that carry no active row. Used by criterion 7."""
    n_groups = -(-N_ADDR // g)
    est = np.zeros((counts_row.shape[0], 8), np.int64)
    for t in range(counts_row.shape[0]):
        c = counts_row[t].astype(np.int64)
        rows_nz = [b for b in range(w_count) if ((c >> b) & 1).any()]
        zero_groups = 0
        for b in rows_nz:
            bits = ((c >> b) & 1)
            pad = np.zeros(n_groups * g, np.int64); pad[:N_ADDR] = bits
            zero_groups += int((pad.reshape(n_groups, g).sum(axis=1) == 0).sum())
        est[t] = [int(c.sum()), int((c > 0).sum()), w_count - len(rows_nz), len(rows_nz), len(rows_nz) * n_groups, len(rows_nz) * n_groups * 8, 0, zero_groups]
    return est      # columns: events, active_addrs, rows_skipped, rows_read, reads_allcols, reads_plane, (issued: mode dependent), zero_groups


def compare_sample(counts_row, W, thresh_int, got) -> dict:
    """Bit-exact comparison of one DUT sample against the golden model: spikes, X, V of every timestep. Returns the first mismatch."""
    tr = reference_trace(counts_row, W, thresh_int)
    res = dict(ok=True, first=None, n_ts=len(got["t"]))
    if len(got["t"]) != T or not np.array_equal(got["t"], np.arange(T)):
        return dict(ok=False, first=("timesteps", len(got["t"])), n_ts=len(got["t"]))
    for name, a, b in (("spikes", tr.S, got["S"]), ("X", tr.X, got["X"]), ("V", tr.V, got["V"])):
        bad = np.argwhere(a != b)
        if len(bad):
            t, j = bad[0]
            return dict(ok=False, first=(name, int(t), int(j), int(a[t, j]), int(b[t, j])), n_ts=T)
    return res
