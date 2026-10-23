#!/usr/bin/env python3
"""Aggregate the Phase 2-4 regression results into one JSON (results/hdc/summary_phase234.json) and two figures; make_report_hdc.py prints it.

Every number here is read from a regression run (results/hdc/*.json, the canonical logs results/hdc/*.out.txt.gz) or computed from the Phase 2-4 reference
(design/reference_model/model/fixedpoint/hdc_query.py, imported, never reimplemented)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))
from tb.common import hdc_golden as H  # noqa: E402

HQ = H.HQ
HDC = ROOT / "results" / "hdc"
GRID = [1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80, 96, 128, 192, 256, 512]
EXTRA_THETA = {"r1": [47, 50], "base": [37]}
SEEDS = (0, 1, 2)
FINE = sorted(set(range(1, 241)) | set(GRID) | {47, 50, 37, 4095})        # every threshold the hardware runs, plus the fine grid for the knees


def js(tag: str):
    f = HDC / f"{tag}.json"
    return json.loads(f.read_text()) if f.exists() else None


def run_stats(tag: str) -> dict | None:
    d = js(tag)
    if d is None:
        return None
    s, per = d["summary"], d["samples"]
    ok = [p for p in per if p.get("ok")]
    return dict(tag=tag, samples=s["samples"], mismatching=s["mismatching_samples"], assert_messages=s["assert_fail_messages"], accuracy=s["accuracy"], n_ts=float(np.mean([p["n_timesteps"] for p in ok])) if ok else None,
                events_fraction=float(np.mean([p["events_ingested"] / p["n_events"] for p in ok])) if ok else None, cycles=float(np.mean([p["cycles_inf"] for p in ok])) if ok else None,
                events=float(np.mean([p["events_ingested"] for p in ok])) if ok else None, query=float(np.mean([p["cycles_query"] for p in ok])) if ok else None,
                stall_and_other=float(np.mean([p["mvm_and_other_cycles"] for p in ok])) if ok else None, reload=float(np.mean([p["reload_cycles"] for p in ok])) if ok else None,
                rows_gated=float(np.sum([p["rows_gated_total"] for p in ok]) / np.sum([p["n_timesteps"] for p in ok])) if ok else None,
                early_fraction=float(np.mean([p["early"] for p in ok])) if ok else None, wall_s=s["sim_wall_s"], simulator=s["simulator"], g=s["g"], cols=s.get("n_parallel_cols", 160))


def reference_sweeps() -> dict:
    out = {}
    for kind in ("base", "r1"):
        mods = [H.load_model(kind, s) for s in SEEDS]
        res = [HQ.sweep(m["prefix"], m["labels"], FINE) for m in mods]
        out[kind] = dict(full_acc=[r[0]["accuracy_full_T"] for r in res], acc=np.array([[r[i]["accuracy"] for r in res] for i in range(len(FINE))]).tolist(),
                         exit=np.array([[r[i]["mean_exit_timestep"] for r in res] for i in range(len(FINE))]).tolist())
    return out


def knee(acc: np.ndarray, full: np.ndarray, tol: float) -> int:
    m, fm = acc.mean(1), full.mean()
    ok = m >= fm - tol - 1e-12
    for i in range(len(FINE)):
        if ok[i:].all():
            return FINE[i]
    return FINE[-1]


IDX = {th: i for i, th in enumerate(FINE)}


def figure_early_exit(S: dict) -> None:
    """Figure 30: accuracy and mean exit timestep against theta (RTL points, both models), knees marked. Style as studies/crossbar/margin/figstyle.py (Okabe-Ito, 3.5 in wide)."""
    import csv
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5, "axes.labelsize": 7.5, "axes.titlesize": 7.5, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.2,
                         "legend.frameon": False, "axes.linewidth": 0.6, "lines.linewidth": 1.1, "lines.markersize": 3.6, "pdf.fonttype": 42, "svg.fonttype": "none", "savefig.bbox": "tight",
                         "savefig.pad_inches": 0.03, "axes.grid": True, "grid.linewidth": 0.3, "grid.alpha": 0.5})
    out = REPO / "figures"
    col = {"r1": "#0072B2", "base": "#D55E00"}
    lab = {"r1": "R=1 factorized (jointly trained)", "base": "baseline unfactorized"}
    fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.5))
    rows = []
    for kind in ("r1", "base"):
        pts = sorted([r for r in S["hw_sweep"] if r["model"] == kind and r["theta"] < 4095], key=lambda r: r["theta"])
        th = [r["theta"] for r in pts]
        ax[0].semilogx(th, [100 * r["acc_mean"] for r in pts], marker="o", color=col[kind], label=lab[kind])
        ax[1].semilogx(th, [r["exit_mean"] for r in pts], marker="o", color=col[kind], label=lab[kind])
        full = 100 * float(np.mean(S["knees"][kind]["full_acc_by_seed"]))
        ax[0].axhline(full, color=col[kind], lw=0.6, ls=":")
        k = S["knees"][kind]["strict"]["theta"]
        for a in ax:
            a.axvline(k, color=col[kind], lw=0.6, ls="--")
        for r in pts:
            rows.append(dict(model=kind, theta=r["theta"], accuracy_pct=100 * r["acc_mean"], mean_exit_timestep=r["exit_mean"], events_ingested_fraction=r["events_fraction_mean"], full_run_accuracy_pct=full))
    ax[0].set_xlabel("exit threshold theta (margin, XNOR-score units)")
    ax[0].set_ylabel("accuracy (%, 3-seed mean, 240 samples)")
    ax[1].set_xlabel("exit threshold theta (margin, XNOR-score units)")
    ax[1].set_ylabel("mean exit timestep (of 100)")
    ax[0].legend(loc="lower right")
    ax[0].set_title("dotted: full-run accuracy; dashed: strict knee", fontsize=6.5)
    for ext, kw in (("pdf", {}), ("svg", {}), ("png", {"dpi": 300})):
        fig.savefig(out / f"fig30_early_exit.{ext}", **kw)
    plt.close(fig)
    with open(out / "fig30_early_exit.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0])); w.writeheader(); w.writerows(rows)


def main() -> int:
    ref = reference_sweeps()
    S: dict = {"reference_sweep": {}, "knees": {}, "runs": {}}
    for kind in ("base", "r1"):
        acc, ex, full = np.array(ref[kind]["acc"]), np.array(ref[kind]["exit"]), np.array(ref[kind]["full_acc"])
        S["knees"][kind] = {name: dict(theta=(k := knee(acc, full, tol)), acc_mean=float(acc[IDX[k]].mean()), exit_mean=float(ex[IDX[k]].mean()), acc_by_seed=acc[IDX[k]].tolist())
                            for name, tol in (("strict", 0.0), ("one_sample", 1 / 720), ("half_pp", 0.005), ("one_pp", 0.01))}
        S["knees"][kind]["full_acc_by_seed"] = full.tolist()
        S["reference_sweep"][kind] = {str(th): dict(acc_by_seed=acc[IDX[th]].tolist(), exit_by_seed=ex[IDX[th]].tolist()) for th in FINE}
    # --- hardware sweep vs the reference sweep (the knee search only looks at thresholds up to 240), every (model, seed, theta) that was run
    sweep_rows, mism = [], []
    for kind, tagn in (("r1", "r1fact"), ("base", "base")):
        for th in sorted(set(GRID + EXTRA_THETA[kind] + [4095])):
            per_seed = []
            for s in SEEDS:
                tag = f"sw_{tagn}_s{s}_t{th}" if th != 4095 else (f"dis_r1fact_s{s}" if kind == "r1" else f"dis_base_s{s}")
                r = run_stats(tag)
                if r is None:
                    continue
                refacc, refex = ref[kind]["acc"][IDX[th]][s], ref[kind]["exit"][IDX[th]][s]
                per_seed.append(dict(seed=s, acc=r["accuracy"], exit=r["n_ts"], events_fraction=r["events_fraction"], mismatching=r["mismatching"], ref_acc=refacc, ref_exit=refex,
                                     equal=bool(abs(r["accuracy"] - refacc) < 1e-12 and abs(r["n_ts"] - refex) < 1e-9), cycles=r["cycles"]))
            if per_seed:
                sweep_rows.append(dict(model=kind, theta=th, seeds=per_seed, acc_mean=float(np.mean([p["acc"] for p in per_seed])), exit_mean=float(np.mean([p["exit"] for p in per_seed])),
                                       events_fraction_mean=float(np.mean([p["events_fraction"] for p in per_seed])), all_equal_reference=all(p["equal"] for p in per_seed),
                                       n_seeds=len(per_seed), cycles_mean=float(np.mean([p["cycles"] for p in per_seed]))))
    S["hw_sweep"] = sweep_rows
    # --- the named runs
    names = {}
    for s in SEEDS:
        for k in ("p3_base", "p3_r1fact", "p3_r1unfact", "dis_base", "dis_r1fact", "l4_real_gaps", "l4_sorted_gaps", "l4_shuffled_nogap"):
            r = run_stats(f"{k}_s{s}")
            if r:
                names[f"{k}_s{s}"] = r
    S["runs"] = names
    ab = {}
    for g in (4, 8):
        for b, t in (("full", "ab_full"), ("ee_off", "ab_eeoff"), ("fact_off", "ab_factoff"), ("both_off", "ab_bothoff")):
            for s in SEEDS:
                r = run_stats(f"{t}_g{g}_s{s}")
                if r:
                    ab[f"{b}_g{g}_s{s}"] = r
    S["ablation_runs"] = ab
    S["icarus"] = {t.name[3:-5]: run_stats(t.name[:-5]) for t in sorted(HDC.glob("ic_*.json")) if not t.name.endswith("timesteps.json")}
    S["compare"] = json.loads((HDC / "compare_summary.json").read_text()) if (HDC / "compare_summary.json").exists() else []
    c20 = run_stats("c20_check_s0")
    S["c20_check"] = c20
    (HDC / "summary_phase234.json").write_text(json.dumps(S, indent=1))
    figure_early_exit(S)
    print("runs:", len(names), "ablation runs:", len(ab), "sweep points:", len(sweep_rows), "icarus runs:", len(S["icarus"]), "comparisons:", len(S["compare"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
