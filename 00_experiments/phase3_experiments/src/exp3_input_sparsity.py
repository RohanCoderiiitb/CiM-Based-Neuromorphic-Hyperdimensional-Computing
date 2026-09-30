"""
Experiment 3: input-frame sparsity.

For each sample, per timestep, compute the raw SumPooled input frame D(t)
over the 512 addresses (addr = p*256 + floor(y/beta)*16 + floor(x/beta),
eq. 19), using the EXACT existing data pipeline
(phase1_firing_characterization/src/neurohdc.py: events_to_frames,
_read_nmnist_bin, DVSGestureDataset event loading). No preprocessing is
changed; input_scaling is irrelevant here since we report address
OCCUPANCY (>=1 event) and RELATIVE count concentration, both invariant to
any positive rescaling.

Reports (both datasets, full test split):
  - fraction of 512 addresses with >=1 event, per timestep: mean/P10/P50/P90
  - distribution of per-address (nonzero) event counts, pooled
  - number of distinct addresses needed to reach 50%/90% of a timestep's
    total events (per-timestep concentration)
  - overlap of the active-address SET between consecutive timesteps
"""
import sys
import os
import json
import numpy as np

P1_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "..", "phase1_firing_characterization", "src")
P1_SRC = os.path.normpath(P1_SRC)
sys.path.insert(0, P1_SRC)
from neurohdc import events_to_frames, _read_nmnist_bin, NMNISTDataset, DVSGestureDataset  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.path.join(os.path.dirname(ROOT), "data")
ART = os.path.join(ROOT, "artifacts")


def concentration_needed(sorted_desc_counts, frac):
    """How many top addresses (by count, descending) are needed to reach
    `frac` of the timestep's total event count. Returns an int >= 1 (or 0
    if the timestep has zero events)."""
    total = sorted_desc_counts.sum()
    if total == 0:
        return 0
    cum = np.cumsum(sorted_desc_counts)
    return int(np.searchsorted(cum, frac * total) + 1)


def analyze_dataset(name, samples_iter, T=100, H=None, W=None, max_samples=None):
    """
    samples_iter: iterable of (x, y, p) arrays (already time-sorted), one
    per sample, in the dataset's native pixel coordinates.
    """
    occ_frac_all = []          # fraction of 512 addrs active, per (sample,timestep)
    nonzero_counts_all = []    # pooled nonzero per-address counts (subsampled if huge)
    need50_all, need90_all = [], []
    overlap_all = []           # consecutive-timestep active-set overlap, per (sample, t)
    n_samples = 0

    for x, y, p in samples_iter:
        if max_samples is not None and n_samples >= max_samples:
            break
        frames, n_events, N_e = events_to_frames(x, y, p, T, H, W)  # [T,512] raw counts
        active = frames > 0  # [T,512] bool
        occ_frac_all.append(active.sum(axis=1) / 512.0)  # [T]

        for t in range(T):
            row = frames[t]
            nz = row[row > 0]
            if nz.size > 0:
                # subsample pooled per-address counts to keep memory bounded
                if np.random.rand() < 0.02:
                    nonzero_counts_all.append(nz)
                sorted_desc = np.sort(nz)[::-1]
                need50_all.append(concentration_needed(sorted_desc, 0.5))
                need90_all.append(concentration_needed(sorted_desc, 0.9))
            else:
                need50_all.append(0)
                need90_all.append(0)

        for t in range(T - 1):
            a, b = active[t], active[t + 1]
            union = np.logical_or(a, b).sum()
            inter = np.logical_and(a, b).sum()
            overlap_all.append(inter / union if union > 0 else 1.0)

        n_samples += 1

    occ_frac_all = np.concatenate(occ_frac_all)  # [n_samples*T]
    nonzero_counts_all = np.concatenate(nonzero_counts_all) if nonzero_counts_all else np.array([0.0])
    need50_all = np.array(need50_all); need90_all = np.array(need90_all)
    overlap_all = np.array(overlap_all)

    def pct(a, p):
        return float(np.percentile(a, p))

    result = dict(
        dataset=name, n_samples=n_samples, T=T, n_addresses=512,
        active_address_fraction=dict(
            mean=float(occ_frac_all.mean()), median=float(np.median(occ_frac_all)),
            std=float(occ_frac_all.std()),
            p10=pct(occ_frac_all, 10), p50=pct(occ_frac_all, 50), p90=pct(occ_frac_all, 90),
        ),
        per_address_nonzero_count=dict(
            mean=float(nonzero_counts_all.mean()), median=float(np.median(nonzero_counts_all)),
            std=float(nonzero_counts_all.std()), max=float(nonzero_counts_all.max()),
            p50=pct(nonzero_counts_all, 50), p90=pct(nonzero_counts_all, 90), p99=pct(nonzero_counts_all, 99),
        ),
        addresses_for_50pct_of_events=dict(
            mean=float(need50_all.mean()), median=float(np.median(need50_all)),
            p10=pct(need50_all, 10), p90=pct(need50_all, 90),
        ),
        addresses_for_90pct_of_events=dict(
            mean=float(need90_all.mean()), median=float(np.median(need90_all)),
            p10=pct(need90_all, 10), p90=pct(need90_all, 90),
        ),
        consecutive_timestep_active_set_overlap_jaccard=dict(
            mean=float(overlap_all.mean()), median=float(np.median(overlap_all)),
            p10=pct(overlap_all, 10), p90=pct(overlap_all, 90),
        ),
    )
    return result, occ_frac_all


def nmnist_iter(root, limit=None):
    ds = NMNISTDataset(root, T=100)  # only used for the file list
    n = len(ds.samples) if limit is None else min(limit, len(ds.samples))
    for i in range(n):
        path, label = ds.samples[i]
        x, y, p, t = _read_nmnist_bin(path)
        yield x, y, p


def dvsgesture_iter(root):
    ds = DVSGestureDataset(root, T=100)
    for path, label in ds.samples:
        ev = np.load(path)
        x, y, p, t = ev[:, 0], ev[:, 1], ev[:, 2], ev[:, 3]
        order = np.argsort(t, kind="stable")
        yield x[order], y[order], p[order]


def main():
    np.random.seed(0)
    results = {}
    hists = {}

    print("Analyzing DVS-Gesture test set (240 samples)...")
    r, occ = analyze_dataset("dvsgesture", dvsgesture_iter(f"{DATA_ROOT}/DVSGesture/ibmGestureTest"),
                              T=100, H=DVSGestureDataset.SENSOR_H, W=DVSGestureDataset.SENSOR_W)
    results["dvsgesture"] = r
    hists["dvsgesture"] = occ
    print(json.dumps(r, indent=2))

    print("\nAnalyzing N-MNIST test set (10,000 samples)...")
    r, occ = analyze_dataset("nmnist", nmnist_iter(f"{DATA_ROOT}/NMNIST/Test"),
                              T=100, H=NMNISTDataset.SENSOR_H, W=NMNISTDataset.SENSOR_W)
    results["nmnist"] = r
    hists["nmnist"] = occ
    print(json.dumps(r, indent=2))

    os.makedirs(f"{ART}/tables", exist_ok=True)
    with open(f"{ART}/tables/exp3_input_sparsity.json", "w") as f:
        json.dump(results, f, indent=2)

    np.savez_compressed(f"{ART}/tables/exp3_occupancy_fractions.npz",
                         dvsgesture=hists["dvsgesture"], nmnist=hists["nmnist"])
    print(f"\nwrote {ART}/tables/exp3_input_sparsity.json")


if __name__ == "__main__":
    main()
