"""Accuracy-vs-R figure (both factor modes, error bars over seeds), plus the
random-init-vs-SVD-init comparison at R=4 if available. Run any time; only
plots whatever run sidecars currently exist on disk."""
import os
import glob
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts")
P1_ART = os.path.join(os.path.dirname(ROOT), "phase1_firing_characterization", "artifacts")

BASELINE_TEST = []
for s in [0, 1, 2]:
    d = json.load(open(f"{P1_ART}/dvs_accuracy/frozen_seed{s}.json"))
    BASELINE_TEST.append(d["test_acc"])
BASELINE_MEAN, BASELINE_STD = float(np.mean(BASELINE_TEST)), float(np.std(BASELINE_TEST))


def collect(prefix_filter):
    """Returns {(rank, mode, init): [test_acc, ...]} for run_name matching prefix_filter(run_name)."""
    out = {}
    for path in sorted(glob.glob(f"{ART}/tables/*.json")):
        name = os.path.basename(path)[:-5]
        if not prefix_filter(name):
            continue
        d = json.load(open(path))
        if "rank" not in d or d.get("test_acc") is None:
            continue
        key = (d["rank"], d["factor_mode"], d["init"])
        out.setdefault(key, []).append(d["test_acc"])
    return out


def main():
    svd_runs = collect(lambda n: "svd" in n and n.startswith("r"))
    random_runs = collect(lambda n: "random" in n)

    ranks = sorted(set(k[0] for k in svd_runs))
    fig, ax = plt.subplots(figsize=(7, 5))
    for mode, color, marker in [("binary", "#3b6fa0", "o"), ("fp", "#a05a3b", "s")]:
        xs, ys, es = [], [], []
        for r in ranks:
            key = (r, mode, "svd")
            if key in svd_runs and len(svd_runs[key]) > 0:
                xs.append(r)
                ys.append(np.mean(svd_runs[key]))
                es.append(np.std(svd_runs[key]))
        if xs:
            ax.errorbar(xs, ys, yerr=es, marker=marker, color=color, capsize=3,
                        label=f"factor_mode={mode} (SVD init)", linestyle="-")

    ax.axhline(BASELINE_MEAN, color="black", linestyle="--", linewidth=1,
               label=f"unfactorized baseline ({BASELINE_MEAN:.3f}±{BASELINE_STD:.3f})")
    ax.axhspan(BASELINE_MEAN - 0.01, BASELINE_MEAN + 0.01, color="green", alpha=0.08,
               label="within 1.0pp (LIVE threshold)")
    ax.axhspan(BASELINE_MEAN - 0.02, BASELINE_MEAN - 0.01, color="orange", alpha=0.08)
    ax.axhline(BASELINE_MEAN - 0.02, color="red", linestyle=":", linewidth=1,
               label="2.0pp below baseline (DEAD threshold)")

    ax.set_xlabel("rank R")
    ax.set_ylabel("test accuracy")
    ax.set_title("Experiment 1: accuracy vs. rank R (error bars = std over 3 seeds)")
    ax.legend(fontsize=7, loc="lower right")
    ax.set_xscale("log", base=2)
    ax.set_xticks(ranks if ranks else [1, 2, 4, 8, 16])
    ax.set_xticklabels([str(r) for r in (ranks if ranks else [1, 2, 4, 8, 16])])
    fig.tight_layout()
    os.makedirs(f"{ART}/figures", exist_ok=True)
    fig.savefig(f"{ART}/figures/exp1_accuracy_vs_rank.png", dpi=150)
    plt.close(fig)
    print(f"wrote {ART}/figures/exp1_accuracy_vs_rank.png")
    print("ranks plotted:", ranks)
    if random_runs:
        print("random-init runs found:", list(random_runs.keys()))


if __name__ == "__main__":
    main()
