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
N_SPK_OF = {"asldvs": 40, "cifar10dvs_large": 40}           # neurons of the chip a dataset's model is built for (default 20: NeuroHDC-small); asldvs -> the large chip
N_CLASS_OF = {"asldvs": 24, "cifar10dvs_large": 24}      # cifar10dvs_large: CIFAR10-DVS on the large chip, 10 classes in 24 slots (slots 10..23 copy class 0)


def weight_files(model: str, seed: int, dataset: str = "dvsgesture") -> list[Path]:
    tag = G.weight_tag(dataset, seed) if model == "base" else r1_tag(dataset, seed, model)
    return [G.VEC / "weights" / f"weights_seed{tag}_macro{m}_32b.mem" for m in range(N_SPK_OF.get(dataset, 20) // 4)]      # 4 neurons per 32-bit macro


def r1_tag(dataset: str, seed: int, model: str = "r1") -> str:
    """weight-image tag of an R=1 checkpoint: DVS-Gesture r1s<k>, CIFAR10-DVS c10r1s<k> (studies/algorithm/phase4_more_datasets); model 'unf' (the large chip's full class store): ASL-DVS aslunfs<k>, CIFAR10-DVS c10Lunfs<k>."""
    if model == "unf":
        return {"cifar10dvs_large": f"c10Lunfs{seed}"}.get(dataset, f"aslunfs{seed}")
    return {"cifar10dvs": f"c10r1s{seed}", "asldvs": f"aslr1s{seed}"}.get(dataset, f"r1s{seed}")


def load_model(model: str, seed: int, dataset: str = "dvsgesture") -> dict:
    """counts, labels, per-sample thresholds, golden SNN trace, class hypervector and the reference prefix scores/predictions."""
    c = np.load(G.VEC / dataset / "counts.npz")
    if model == "base":
        z = np.load(G.VEC / dataset / f"seed{seed}.npz")
        hv = np.load(G.P0 / "artifacts" / "phase0" / (f"class_hv_nmnist{seed}.npy" if dataset == "nmnist" else f"class_hv_seed{seed}.npy"))
        a = b = None
    elif model == "r1":
        z = np.load(G.VEC / (dataset if dataset in ("cifar10dvs", "asldvs") else "dvsgesture") / f"r1_seed{seed}.npz")
        hv, a, b = z["class_hv"], z["a_bits"], z["b_bits"]
    elif model == "unf":                  # unfactorized class store of a phase4 dataset (ASL-DVS on the large chip): class_hv only
        z = np.load(G.VEC / dataset / f"unf_seed{seed}.npz")
        hv, a, b = z["class_hv"], None, None
    else:
        raise ValueError(model)
    W = G.load_dataset(dataset, seed)[3] if model == "base" else _decode_weights(model, seed, dataset)
    prefix = np.stack([HQ.prefix_scores(HQ.agree_unfactorized(z["spikes"][i], hv)) for i in range(len(z["spikes"]))])
    assert np.array_equal(prefix, z["score_xnor_prefix"].astype(prefix.dtype)), "stored prefix scores disagree with the reference"
    return dict(model=model, seed=seed, dataset=dataset, counts=c["counts"], labels=c["labels"].astype(int), thresh_int=z["thresh_int"], spikes=z["spikes"], X=z["X"], V=z["V"], W=W,
                class_hv=hv, a_bits=a, b_bits=b, prefix=prefix, pred=prefix[:, -1].argmax(axis=1))


def _decode_weights(model: str, seed: int, dataset: str = "dvsgesture"):
    n = N_SPK_OF.get(dataset, 20)
    rows = G.read_mem(G.VEC / "weights" / f"weights_seed{r1_tag(dataset, seed, model)}_{8 * n}b.mem")
    return G.LV.decode_planes(G.LV.unpack_rows(rows, n))


def write_class_image(job_dir: Path, mdl: dict, factorized: bool) -> None:
    """cmain.mem / csign.mem / cbias.mem in the formats of hdc_regress_tb.sv."""
    hv = mdl["class_hv"]
    n = hv.shape[0]
    k = hv.shape[2]                                   # spike-vector width: 20 (small chip), 40 (large)
    wa = k.bit_length()                               # agree / bias width = clog2(k + 1)
    w = (n * k + 3) // 4
    with open(job_dir / "cmain.mem", "w") as f:
        if factorized:
            assert mdl["a_bits"] is not None, "the factorized build needs a factorized (r1) model"
            f.write(f"{sum(int(mdl['a_bits'][i, j]) << (k * i + j) for i in range(n) for j in range(k)):0{w}x}\n")
            with open(job_dir / "csign.mem", "w") as g:
                for t in range(T):
                    g.write(f"{sum(int(mdl['b_bits'][i, t]) << i for i in range(n)):0{(n + 3) // 4}x}\n")
            with open(job_dir / "cbias.mem", "w") as g:
                g.write(f"{sum(int(mdl['a_bits'][i].sum()) << (wa * i) for i in range(n)):0{(n * wa + 3) // 4}x}\n")
        else:
            for t in range(T):
                f.write(f"{sum(int(hv[i, t, j]) << (k * i + j) for i in range(n) for j in range(k)):0{w}x}\n")


def write_job(job_dir: Path, mdl: dict, factorized: bool, samples: list, thresholds: list, thetas: list, exit_en: list, gap_mode: int = 0, sim_seed: int = 1,
              gap_seeds: list | None = None) -> None:
    """samples: [(aer words, counts_row)]. Extends golden.write_job with the class image and the per-sample (theta, exit_en)."""
    job_dir.mkdir(parents=True, exist_ok=True)
    for m, f in enumerate(weight_files(mdl["model"], mdl["seed"], mdl.get("dataset", "dvsgesture"))):
        shutil.copyfile(f, job_dir / f"weights_macro{m}.mem")
    write_class_image(job_dir, mdl, factorized)
    with open(job_dir / "job.txt", "w") as fh:
        fh.write(f"{G.GEOM[mdl.get('dataset', 'dvsgesture')][2]} {len(samples)} {gap_mode} {sim_seed}\n")
        for i, ((words, _), th) in enumerate(zip(samples, thresholds)):
            gs = (gap_seeds[i] if gap_seeds else sim_seed * 7919 + i) & 0x7FFFFFFF
            fh.write(f"{len(words)} " + " ".join(str(int(v)) for v in th) + f" {gs} {int(thetas[i])} {int(exit_en[i])}\n")
    with open(job_dir / "events.bin", "wb") as fh:
        for words, _ in samples:
            fh.write(words.astype(">u4" if G.pkg_int("W_AER") > 16 else ">u2").tobytes())      # the testbench reads uint32 words when W_AER > 16


def parse_output(path: Path, n_class: int = N_CLASS, n_spk: int = 20):
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
            o = 2 + 2 * n_spk                          # after t, spikes: n_spk X, n_spk V, 11 stats, n_class scores, 5 extras
            samples[s]["rows"].append((int(v[0]), int(v[1], 16), [int(x) for x in v[2:2 + n_spk]], [int(x) for x in v[2 + n_spk:o]], [int(x) for x in v[o:o + 11]],
                                       [int(x) for x in v[o + 11:o + 11 + n_class]], [int(x) for x in v[o + 11 + n_class:o + 16 + n_class]]))
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
        S = np.array([[(r[1] >> j) & 1 for j in range(n_spk)] for r in rows], np.uint8)
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
