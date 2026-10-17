"""
Compute per-sample and dataset-level firing-rate statistics from captured
NeuroHDC output spike rasters, and render the required figures.

Reads:  artifacts/rasters/{dataset}_n20_T100_seed{s}.npz (+ .json sidecar)
Writes: artifacts/tables/firing_rate_stats.csv        (one row per sample)
        artifacts/tables/firing_rate_summary.json     (one entry per dataset)
        artifacts/figures/*.png
"""
import os
import sys
import json
import itertools
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(__file__))
ART = os.path.join(ROOT, "artifacts")
# "dvsgesture_frozen" (84.6% test acc, Phase 4 of dvs_accuracy_report.md)
# supersedes the original "dvsgesture" capture (58-60% test acc, a
# methodologically-flawed test-set-selected run). The original capture and
# its analysis are preserved in archive_dvsgesture_v1_provisional/, not
# deleted -- see firing_rate_results.md "Superseded results" section.
DATASETS = ["nmnist", "dvsgesture_frozen"]
SEED = 0


def gini(x):
    x = np.sort(np.asarray(x, dtype=np.float64))
    n = len(x)
    if x.sum() == 0:
        return 0.0
    cum = np.cumsum(x)
    return (n + 1 - 2 * np.sum(cum) / cum[-1]) / n


def load(name):
    npz = np.load(f"{ART}/rasters/{name}_n20_T100_seed{SEED}.npz")
    with open(f"{ART}/rasters/{name}_n20_T100_seed{SEED}.json") as f:
        sidecar = json.load(f)
    return npz, sidecar


def per_sample_rows(name, npz):
    raster = npz["raster"].astype(np.float32)  # [M,T,n]
    labels = npz["labels"]
    pred = npz["pred"]
    n_events = npz["n_events"]
    N_e = npz["N_e"]
    M, T, n = raster.shape

    total_spikes = raster.sum(axis=(1, 2))
    firing_rate = total_spikes / (n * T)
    per_neuron = raster.mean(axis=1)          # [M, n]
    active_neurons = (raster.sum(axis=1) > 0).sum(axis=1)
    frac_active_neurons = active_neurons / n
    k_t = raster.sum(axis=2)                  # [M, T] spikes per timestep
    silent_timesteps = (k_t == 0).sum(axis=1)
    frac_silent_timesteps = silent_timesteps / T
    per_timestep = raster.mean(axis=2)        # [M, T] rate per timestep (=k_t/n)

    rows = pd.DataFrame({
        "dataset": name,
        "sample_idx": np.arange(M),
        "label": labels,
        "pred": pred,
        "correct": (labels == pred).astype(int),
        "n_events": n_events,
        "N_e": N_e,
        "total_spikes": total_spikes.astype(int),
        "firing_rate": firing_rate,
        "n_active_neurons": active_neurons,
        "frac_active_neurons": frac_active_neurons,
        "n_silent_timesteps": silent_timesteps,
        "frac_silent_timesteps": frac_silent_timesteps,
        "spikes_per_timestep_mean": k_t.mean(axis=1),
        "spikes_per_timestep_std": k_t.std(axis=1),
        "spikes_per_timestep_max": k_t.max(axis=1),
        "per_neuron_rate_mean": per_neuron.mean(axis=1),
        "per_neuron_rate_std": per_neuron.std(axis=1),
        "per_neuron_rate_min": per_neuron.min(axis=1),
        "per_neuron_rate_max": per_neuron.max(axis=1),
        "per_timestep_rate_mean": per_timestep.mean(axis=1),
        "per_timestep_rate_std": per_timestep.std(axis=1),
    })
    return rows


def dataset_summary(name, npz, sidecar, rows):
    raster = npz["raster"].astype(np.float32)
    M, T, n = raster.shape
    r_m = rows["firing_rate"].values
    s_m = rows["total_spikes"].values

    r_global = float(raster.mean())
    r_j = raster.mean(axis=(0, 1))   # [n] per-neuron rate
    r_t = raster.mean(axis=(0, 2))   # [T] per-timestep rate
    k_t = raster.sum(axis=2)         # [M,T]
    sigma_global = float((k_t == 0).mean())  # fraction of completely silent timesteps
    dead_neurons = int((r_j == 0).sum())

    # Burstiness: observed silent-timestep fraction vs. the independent-Bernoulli
    # prediction (1-r)^n. B >> 1 means timesteps are silent far more often than
    # independent per-neuron firing would predict -> temporal/neuron correlation.
    indep_pred = (1 - r_global) ** n if r_global < 1 else 0.0
    burstiness = float(sigma_global / indep_pred) if indep_pred > 0 else float("inf")

    def pct(a, p):
        return float(np.percentile(a, p))

    # --- k_t (per-timestep spike count) distribution, pooled over all (m,t) ---
    k_t_flat = k_t.reshape(-1)
    k_t_hist = np.bincount(k_t_flat.astype(int), minlength=n + 1)[: n + 1]
    zeros_per_timestep = n - k_t_flat  # "20 - k_t", NOT the same as the global bit-zero fraction (1-r)

    # --- per-sample silent-timestep fraction (sigma), distribution across samples ---
    sigma_m = rows["frac_silent_timesteps"].values

    # --- consecutive silent/active timestep run lengths (F10 + its active-run dual) ---
    is_silent = (k_t == 0)
    silent_runs, active_runs = run_lengths(is_silent)

    def dist(a, integer=False):
        a = np.asarray(a, dtype=np.float64)
        d = dict(
            mean=float(a.mean()), median=float(np.median(a)), std=float(a.std()),
            min=(int(a.min()) if integer else float(a.min())),
            max=(int(a.max()) if integer else float(a.max())),
            p10=pct(a, 10), p25=pct(a, 25), p75=pct(a, 75), p90=pct(a, 90),
            n=int(a.size),
        )
        return d

    summary = dict(
        dataset=name,
        n_samples=int(M),
        n_neurons=int(n),
        T=int(T),
        test_accuracy=sidecar.get("test_accuracy"),
        paper_reported_accuracy=sidecar.get("paper_reported_accuracy"),
        v_thresh_final=sidecar.get("v_thresh_final"),
        n_events=dict(
            mean=float(npz["n_events"].mean()),
            p10=pct(npz["n_events"], 10), p50=pct(npz["n_events"], 50), p90=pct(npz["n_events"], 90),
        ),
        N_e=dict(
            mean=float(npz["N_e"].mean()),
            p10=pct(npz["N_e"], 10), p50=pct(npz["N_e"], 50), p90=pct(npz["N_e"], 90),
        ),
        global_firing_rate=r_global,
        per_sample_firing_rate=dict(
            mean=float(r_m.mean()), median=float(np.median(r_m)), std=float(r_m.std()),
            min=float(r_m.min()), max=float(r_m.max()),
            p10=pct(r_m, 10), p25=pct(r_m, 25), p75=pct(r_m, 75), p90=pct(r_m, 90),
            cv=float(r_m.std() / r_m.mean()) if r_m.mean() > 0 else None,
        ),
        spikes_per_sample=dict(
            mean=float(s_m.mean()), median=float(np.median(s_m)), std=float(s_m.std()),
            min=int(s_m.min()), max=int(s_m.max()),
            p10=pct(s_m, 10), p25=pct(s_m, 25), p75=pct(s_m, 75), p90=pct(s_m, 90),
        ),
        per_neuron_firing_rate=dict(
            values=r_j.tolist(), mean=float(r_j.mean()), std=float(r_j.std()),
            min=float(r_j.min()), max=float(r_j.max()), gini=float(gini(r_j)),
            n_dead_neurons=dead_neurons, frac_dead_neurons=dead_neurons / n,
        ),
        per_timestep_firing_rate=dict(
            values=r_t.tolist(), mean=float(r_t.mean()), std=float(r_t.std()),
            min=float(r_t.min()), max=float(r_t.max()), gini=float(gini(r_t)),
            cv=float(r_t.std() / r_t.mean()) if r_t.mean() > 0 else None,
        ),
        frac_completely_silent_timesteps=sigma_global,
        frac_active_neurons_mean=float(rows["frac_active_neurons"].mean()),
        burstiness_ratio=burstiness,
        # --- timestep/vector-granularity characterization (this task) ---
        # k_t = number of active (of n) neurons at one timestep, pooled over
        # every (sample, timestep) pair. This is the "how sparse is one
        # 20-bit timestep vector" view -- distinct from the global bit-level
        # rate r (which pools over every individual bit).
        k_t_distribution=dict(
            **dist(k_t_flat, integer=True),
            mode=int(np.argmax(k_t_hist)),
            histogram_k_0_to_n=k_t_hist.tolist(),  # counts for k_t = 0, 1, ..., n
        ),
        # "20 - k_t": zeros within one timestep vector. NOT the same quantity
        # as the global bit-zero fraction (1-r): this is per-timestep-vector,
        # (1-r) is the mean of this divided by n, pooled differently -- see
        # firing_rate_results.md for the explicit distinction.
        zeros_per_timestep_vector=dist(zeros_per_timestep, integer=True),
        # Per-SAMPLE silent-timestep fraction sigma_m, distribution ACROSS
        # samples (distinct from the single pooled global sigma above).
        per_sample_sigma=dist(sigma_m),
        silent_run_lengths=dict(**dist(silent_runs, integer=True), count=len(silent_runs)) if silent_runs else None,
        active_run_lengths=dict(**dist(active_runs, integer=True), count=len(active_runs)) if active_runs else None,
        class_hv_l1=dict(
            values=npz["class_l1"].tolist(),
            mean=float(npz["class_l1"].mean()), std=float(npz["class_l1"].std()),
            min=int(npz["class_l1"].min()), max=int(npz["class_l1"].max()),
            spread=int(npz["class_l1"].max() - npz["class_l1"].min()),
        ),
    )
    return summary


def run_lengths(is_silent):
    """
    F10 (firing_rate_experiment_spec.md): distribution of maximal runs of
    consecutive silent timesteps, per sample, pooled across all samples.
    Extended here symmetrically to active-timestep runs using the same
    "maximal run" definition (the spec only defines the silent case).

    is_silent: bool [M, T], True where k_t == 0 for that (sample, timestep).
    Returns (silent_run_lengths, active_run_lengths) as flat lists of ints,
    one entry per maximal run found in any sample.
    """
    silent_runs, active_runs = [], []
    for m in range(is_silent.shape[0]):
        for val, group in itertools.groupby(is_silent[m].tolist()):
            length = sum(1 for _ in group)
            (silent_runs if val else active_runs).append(length)
    return silent_runs, active_runs


def zero_group_fraction(raster, family, g):
    """F11-style zero-group fraction. raster: [M,T,n]."""
    M, T, n = raster.shape
    if family == "spatial":
        if n % g != 0:
            return None
        r = raster.reshape(M, T, n // g, g)
        groups = r.sum(axis=3)
    elif family == "temporal":
        if T % g != 0:
            return None
        r = raster.reshape(M, T // g, g, n)
        groups = r.sum(axis=2)
    else:
        raise ValueError(family)
    return float((groups == 0).mean())


def make_plots(name, npz, rows, summary):
    fig_dir = f"{ART}/figures"
    os.makedirs(fig_dir, exist_ok=True)
    raster = npz["raster"]
    labels = npz["labels"]
    M, T, n = raster.shape

    # 1. firing-rate distribution
    plt.figure(figsize=(5, 3.5))
    plt.hist(rows["firing_rate"], bins=40, color="#3b6fa0")
    for p, ls in [(10, ":"), (50, "-"), (90, ":")]:
        v = np.percentile(rows["firing_rate"], p)
        plt.axvline(v, color="black", linestyle=ls, linewidth=1)
    plt.xlabel("per-sample firing rate r_m")
    plt.ylabel("count")
    plt.title(f"{name}: per-sample firing-rate distribution")
    plt.tight_layout()
    plt.savefig(f"{fig_dir}/{name}_firing_rate_hist.png", dpi=150)
    plt.close()

    # 2. spikes/sample distribution
    plt.figure(figsize=(5, 3.5))
    plt.hist(rows["total_spikes"], bins=40, color="#a05a3b")
    plt.xlabel("spikes per sample (of n*T=2000)")
    plt.ylabel("count")
    plt.title(f"{name}: spikes-per-sample distribution")
    plt.tight_layout()
    plt.savefig(f"{fig_dir}/{name}_spikes_per_sample_hist.png", dpi=150)
    plt.close()

    # 3. per-neuron firing-rate distribution
    r_j = np.array(summary["per_neuron_firing_rate"]["values"])
    plt.figure(figsize=(6, 3.5))
    plt.bar(np.arange(n), r_j, color="#3b8f6a")
    plt.axhline(summary["global_firing_rate"], color="black", linestyle="--", linewidth=1, label="global rate")
    plt.xlabel("neuron index j")
    plt.ylabel("firing rate r_j")
    plt.title(f"{name}: per-neuron firing rate (n={n})")
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{fig_dir}/{name}_per_neuron_rate.png", dpi=150)
    plt.close()

    # 4. per-timestep firing-rate distribution
    r_t = np.array(summary["per_timestep_firing_rate"]["values"])
    plt.figure(figsize=(7, 3.5))
    plt.plot(np.arange(T), r_t, color="#7a3ba0")
    plt.axhline(summary["global_firing_rate"], color="black", linestyle="--", linewidth=1, label="global rate")
    plt.xlabel("timestep t")
    plt.ylabel("firing rate r_t")
    plt.title(f"{name}: per-timestep firing rate (T={T})")
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{fig_dir}/{name}_per_timestep_rate.png", dpi=150)
    plt.close()

    # 5a. histogram of k_t (spikes per timestep, 0..n), pooled over all (m,t)
    k_t = raster.astype(np.int32).sum(axis=2)
    hist = np.array(summary["k_t_distribution"]["histogram_k_0_to_n"])
    plt.figure(figsize=(6, 3.5))
    plt.bar(np.arange(n + 1), hist, color="#3b6fa0")
    plt.axvline(summary["k_t_distribution"]["mean"], color="black", linestyle="--",
                linewidth=1, label=f"mean={summary['k_t_distribution']['mean']:.2f}")
    plt.xlabel("k_t (active neurons out of n, per timestep)")
    plt.ylabel("count (over all sample x timestep pairs)")
    plt.title(f"{name}: per-timestep spike-count distribution (n={n})")
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{fig_dir}/{name}_kt_histogram.png", dpi=150)
    plt.close()

    # 5b. distribution of per-sample silent-timestep fraction (sigma_m) across samples
    plt.figure(figsize=(5, 3.5))
    plt.hist(rows["frac_silent_timesteps"], bins=30, color="#a03b6f")
    plt.axvline(summary["frac_completely_silent_timesteps"], color="black", linestyle="--",
                linewidth=1, label=f"global sigma={summary['frac_completely_silent_timesteps']:.4f}")
    plt.xlabel("per-sample silent-timestep fraction (sigma_m)")
    plt.ylabel("count (samples)")
    plt.title(f"{name}: distribution of per-sample sigma across samples")
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{fig_dir}/{name}_sigma_per_sample_hist.png", dpi=150)
    plt.close()

    # 5. representative 20xT rasters, one per class (first correctly-classified
    #    sample found for that class; falls back to first sample of the class)
    classes = sorted(np.unique(labels).tolist())
    n_show = min(len(classes), 10)
    ncols = 5
    nrows = int(np.ceil(n_show / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.2 * ncols, 2.2 * nrows))
    axes = np.atleast_1d(axes).reshape(-1)
    correct = npz["labels"] == npz["pred"]
    for i, c in enumerate(classes[:n_show]):
        idxs = np.where(labels == c)[0]
        correct_idxs = idxs[correct[idxs]]
        pick = correct_idxs[0] if len(correct_idxs) > 0 else idxs[0]
        ax = axes[i]
        ax.imshow(raster[pick].T, aspect="auto", cmap="Greys", interpolation="nearest", vmin=0, vmax=1)
        ax.set_title(f"class {c} (sample {pick})", fontsize=8)
        ax.set_xlabel("timestep", fontsize=7)
        ax.set_ylabel("neuron", fontsize=7)
        ax.tick_params(labelsize=6)
    for j in range(n_show, len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"{name}: representative {n}x{T} output spike rasters (rows=neurons, cols=timesteps)")
    fig.tight_layout()
    fig.savefig(f"{fig_dir}/{name}_raster_examples.png", dpi=150)
    plt.close(fig)


def main():
    all_rows = []
    all_summaries = {}
    granularity_rows = []
    for name in DATASETS:
        npz_path = f"{ART}/rasters/{name}_n20_T100_seed{SEED}.npz"
        if not os.path.exists(npz_path):
            print(f"SKIP {name}: {npz_path} not found")
            continue
        npz, sidecar = load(name)
        rows = per_sample_rows(name, npz)
        summary = dataset_summary(name, npz, sidecar, rows)
        all_rows.append(rows)
        all_summaries[name] = summary
        make_plots(name, npz, rows, summary)

        raster = npz["raster"]
        for g in [1, 2, 4, 5, 10, 20]:
            z = zero_group_fraction(raster, "spatial", g)
            granularity_rows.append(dict(dataset=name, family="spatial", g=g, z=z))
        for g in [1, 2, 4, 5, 10, 20, 25, 50, 100]:
            z = zero_group_fraction(raster, "temporal", g)
            granularity_rows.append(dict(dataset=name, family="temporal", g=g, z=z))

        print(f"{name}: r={summary['global_firing_rate']:.4f} "
              f"sigma={summary['frac_completely_silent_timesteps']:.4f} "
              f"B={summary['burstiness_ratio']:.3f} "
              f"acc={summary['test_accuracy']:.4f} (paper {summary['paper_reported_accuracy']})")

    os.makedirs(f"{ART}/tables", exist_ok=True)
    stats_csv = pd.concat(all_rows, ignore_index=True)
    stats_csv.to_csv(f"{ART}/tables/firing_rate_stats.csv", index=False)

    with open(f"{ART}/tables/firing_rate_summary.json", "w") as f:
        json.dump(all_summaries, f, indent=2)

    pd.DataFrame(granularity_rows).to_csv(f"{ART}/tables/granularity.csv", index=False)

    # granularity curve figure
    plt.figure(figsize=(6, 4))
    for name in all_summaries:
        sub = [r for r in granularity_rows if r["dataset"] == name and r["family"] == "spatial"]
        sub = sorted(sub, key=lambda r: r["g"])
        plt.plot([r["g"] for r in sub], [r["z"] for r in sub], marker="o", label=f"{name} (spatial)")
    plt.xlabel("group size g (consecutive neurons within a timestep)")
    plt.ylabel("zero-group fraction z(g)")
    plt.title("Zero-group fraction vs. spatial access granularity")
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{ART}/figures/granularity_curve_spatial.png", dpi=150)
    plt.close()

    print("wrote firing_rate_stats.csv, firing_rate_summary.json, granularity.csv, figures")


if __name__ == "__main__":
    main()
