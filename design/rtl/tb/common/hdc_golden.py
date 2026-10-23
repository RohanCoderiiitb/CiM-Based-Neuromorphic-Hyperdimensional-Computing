"""Golden-model access and stimulus preparation for the Phase 2-4 testbenches.

THE GOLDEN MODEL RULE (as in golden.py): this module IMPORTS the references (int_model.py, hdc_query.py, r1_model.py, events.py). Nothing here re-implements them; every
expected value comes from a call into them or from the frozen golden vectors.

Models (a "model" = SNN weights + thresholds + class hypervector, all from one checkpoint):
  base  seed k   the frozen unfactorized NeuroHDC (class_hv_seed<k>.npy, weights tag k)           -> unfactorized RTL build only
  r1    seed k   the R=1 factorized checkpoint (a_i[20], b_i[T] bits, weights tag r1s<k>)           -> factorized RTL build, or the unfactorized build with the expansion
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np

from . import golden as G

sys.path.insert(0, str(G.P0 / "model" / "fixedpoint"))
import hdc_query as HQ  # noqa: E402  (Phase 2-4 reference)

N_CLASS = 10
T = G.T


def weight_files(model: str, seed: int) -> list[Path]:
    tag = str(seed) if model == "base" else f"r1s{seed}"
    return [G.VEC / "weights" / f"weights_seed{tag}_macro{m}_32b.mem" for m in range(5)]


def load_model(model: str, seed: int) -> dict:
    """counts, labels, per-sample thresholds, golden SNN trace, class hypervector and the reference prefix scores/predictions."""
    c = np.load(G.VEC / "dvsgesture" / "counts.npz")
    if model == "base":
        z = np.load(G.VEC / "dvsgesture" / f"seed{seed}.npz")
        hv = np.load(G.P0 / "artifacts" / "phase0" / f"class_hv_seed{seed}.npy")
        a = b = None
    elif model == "r1":
        z = np.load(G.VEC / "dvsgesture" / f"r1_seed{seed}.npz")
        hv, a, b = z["class_hv"], z["a_bits"], z["b_bits"]
    else:
        raise ValueError(model)
    W = G.load_dataset("dvsgesture", seed)[3] if model == "base" else _decode_weights(model, seed)
    prefix = np.stack([HQ.prefix_scores(HQ.agree_unfactorized(z["spikes"][i], hv)) for i in range(len(z["spikes"]))])
    assert np.array_equal(prefix, z["score_xnor_prefix"].astype(prefix.dtype)), "stored prefix scores disagree with the reference"
    return dict(model=model, seed=seed, counts=c["counts"], labels=c["labels"].astype(int), thresh_int=z["thresh_int"], spikes=z["spikes"], X=z["X"], V=z["V"], W=W,
                class_hv=hv, a_bits=a, b_bits=b, prefix=prefix, pred=prefix[:, -1].argmax(axis=1))


def _decode_weights(model: str, seed: int):
    rows = G.read_mem(G.VEC / "weights" / f"weights_seedr1s{seed}_160b.mem")
    return G.LV.decode_planes(G.LV.unpack_rows(rows, 20))


def write_class_image(job_dir: Path, mdl: dict, factorized: bool) -> None:
    """cmain.mem / csign.mem / cbias.mem in the formats of hdc_regress_tb.sv."""
    hv = mdl["class_hv"]
    n = hv.shape[0]
    w = (n * 20 + 3) // 4
    with open(job_dir / "cmain.mem", "w") as f:
        if factorized:
            assert mdl["a_bits"] is not None, "the factorized build needs a factorized (r1) model"
            f.write(f"{sum(int(mdl['a_bits'][i, j]) << (20 * i + j) for i in range(n) for j in range(20)):0{w}x}\n")
            with open(job_dir / "csign.mem", "w") as g:
                for t in range(T):
                    g.write(f"{sum(int(mdl['b_bits'][i, t]) << i for i in range(n)):0{(n + 3) // 4}x}\n")
            with open(job_dir / "cbias.mem", "w") as g:
                g.write(f"{sum(int(mdl['a_bits'][i].sum()) << (5 * i) for i in range(n)):0{(n * 5 + 3) // 4}x}\n")
        else:
            for t in range(T):
                f.write(f"{sum(int(hv[i, t, j]) << (20 * i + j) for i in range(n) for j in range(20)):0{w}x}\n")


def write_job(job_dir: Path, mdl: dict, factorized: bool, samples: list, thresholds: list, thetas: list, exit_en: list, gap_mode: int = 0, sim_seed: int = 1,
              gap_seeds: list | None = None) -> None:
    """samples: [(aer words, counts_row)]. Extends golden.write_job with the class image and the per-sample (theta, exit_en)."""
    job_dir.mkdir(parents=True, exist_ok=True)
    for m, f in enumerate(weight_files(mdl["model"], mdl["seed"])):
        shutil.copyfile(f, job_dir / f"weights_macro{m}.mem")
    write_class_image(job_dir, mdl, factorized)
    with open(job_dir / "job.txt", "w") as fh:
        fh.write(f"0 {len(samples)} {gap_mode} {sim_seed}\n")
        for i, ((words, _), th) in enumerate(zip(samples, thresholds)):
            gs = (gap_seeds[i] if gap_seeds else sim_seed * 7919 + i) & 0x7FFFFFFF
            fh.write(f"{len(words)} " + " ".join(str(int(v)) for v in th) + f" {gs} {int(thetas[i])} {int(exit_en[i])}\n")
    with open(job_dir / "events.bin", "wb") as fh:
        for words, _ in samples:
            fh.write(words.astype(">u2").tobytes())


def parse_output(path: Path, n_class: int = N_CLASS):
    """-> per-sample dicts: t, S [t,20], X, V, stats [t,11], scores [t,N], top1_idx, top1, top2, fire, rows_gated, and the END record."""
    import gzip
    samples = []
    fh = gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)
    for line in fh:
        f = line.split()
        if not f:
            continue
        if f[0] == "TS":
            s = int(f[1])
            while len(samples) <= s:
                samples.append(dict(rows=[]))
            v = f[2:]
            samples[s]["rows"].append((int(v[0]), int(v[1], 16), [int(x) for x in v[2:22]], [int(x) for x in v[22:42]], [int(x) for x in v[42:53]],
                                       [int(x) for x in v[53:53 + n_class]], [int(x) for x in v[53 + n_class:58 + n_class]]))
        elif f[0] == "END":
            s = int(f[1])
            while len(samples) <= s:
                samples.append(dict(rows=[]))
            keys = ["cycles_inf", "cycles_ingest_unused", "cycles_query", "events_ingested", "stall_cycles", "idle_cycles", "events_total", "assert_cycles", "hdc_assert_cycles", "ts_seen",
                    "pred", "early", "pred_tstep", "reload_cycles"]
            samples[s]["end"] = {k: int(x) for k, x in zip(keys, f[2:])}
    out = []
    for sm in samples:
        rows = sorted(sm["rows"])
        S = np.array([[(r[1] >> j) & 1 for j in range(G.N_NEURON)] for r in rows], np.uint8)
        extra = np.array([r[6] for r in rows], np.int64).reshape(len(rows), 5)
        out.append(dict(t=np.array([r[0] for r in rows]), S=S, X=np.array([r[2] for r in rows], np.int64), V=np.array([r[3] for r in rows], np.int64),
                        stats=np.array([r[4] for r in rows], np.int64), scores=np.array([r[5] for r in rows], np.int64), top1_idx=extra[:, 0], top1=extra[:, 1], top2=extra[:, 2],
                        fire=extra[:, 3], rows_gated=extra[:, 4], end=sm.get("end")))
    return out


def reference_sample(mdl: dict, row: int, theta: int, exit_en: bool) -> dict:
    """Everything the DUT must produce for one sample, from the references only."""
    prefix = mdl["prefix"][row]
    t_exit, pred, fired = HQ.exit_point(prefix, theta if exit_en else HQ.THETA_NEVER)
    return dict(prefix=prefix, margins=HQ.margins(prefix), t_exit=t_exit, pred=pred, fired=fired, top2=[HQ.top2_tournament(p) for p in prefix])
