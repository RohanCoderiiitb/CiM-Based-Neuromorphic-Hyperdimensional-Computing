"""Figures for Experiments 2 and 3 (no training dependency)."""
import os
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts")
FIG = os.path.join(ART, "figures")
os.makedirs(FIG, exist_ok=True)


def fig_exp2():
    d = json.load(open(f"{ART}/tables/exp2_early_exit.json"))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, key, title in [(axes[0], "dvsgesture_seed0", "DVS-Gesture (seed 0, 84.6% full-T acc)"),
                            (axes[1], "nmnist_seed0", "N-MNIST (seed 0, 94.9% full-T acc)")]:
        rows = d[key]["theta_sweep"]
        exit_t = [r["mean_exit_timestep"] for r in rows]
        acc = [r["accuracy_at_exit"] for r in rows]
        saved = [r["mean_events_not_ingested_fraction"] * 100 for r in rows]
        full_acc = d[key]["full_T_accuracy"]

        ax.plot(exit_t, acc, "o-", color="#3b6fa0", label="accuracy at exit")
        ax.axhline(full_acc, color="black", linestyle="--", linewidth=1, label=f"full-T acc={full_acc:.3f}")
        ax.set_xlabel("mean exit timestep (of 100)")
        ax.set_ylabel("accuracy at exit", color="#3b6fa0")
        ax.set_title(title)
        ax2 = ax.twinx()
        ax2.plot(exit_t, saved, "s--", color="#a05a3b", label="events not ingested (%)")
        ax2.set_ylabel("mean events not ingested (%)", color="#a05a3b")
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc="lower right")
    fig.suptitle("Experiment 2: accuracy vs. exit timestep, with events-saved on a second axis")
    fig.tight_layout()
    fig.savefig(f"{FIG}/exp2_accuracy_vs_exit_timestep.png", dpi=150)
    plt.close(fig)
    print(f"wrote {FIG}/exp2_accuracy_vs_exit_timestep.png")


def fig_exp3():
    npz = np.load(f"{ART}/tables/exp3_occupancy_fractions.npz")
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(npz["dvsgesture"] * 100, bins=50, alpha=0.6, label="DVS-Gesture", color="#3b6fa0", density=True)
    ax.hist(npz["nmnist"] * 100, bins=50, alpha=0.6, label="N-MNIST", color="#a05a3b", density=True)
    ax.set_xlabel("active addresses per timestep (% of 512)")
    ax.set_ylabel("density")
    ax.set_title("Experiment 3: input-frame (SNN-side) address occupancy per timestep")
    ax.legend()
    fig.tight_layout()
    fig.savefig(f"{FIG}/exp3_input_sparsity_histogram.png", dpi=150)
    plt.close(fig)
    print(f"wrote {FIG}/exp3_input_sparsity_histogram.png")


if __name__ == "__main__":
    fig_exp2()
    fig_exp3()
