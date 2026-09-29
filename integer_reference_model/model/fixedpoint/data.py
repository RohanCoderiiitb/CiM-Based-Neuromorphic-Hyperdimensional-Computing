"""
Data loading. Reuses the ORIGINAL pipeline (neurohdc.DVSGestureDataset / NMNISTDataset ->
events_to_frames -> np.bincount) unchanged; the integer counts c[t,addr] are read back
out of its output with input_scaling="raw" (float32 tensors holding exact integers).
"""
import os
import numpy as np
import _paths  # noqa: F401
from neurohdc import DVSGestureDataset, NMNISTDataset


def _to_counts(frames):
    f = frames.numpy()
    c = np.rint(f).astype(np.int64)
    assert np.array_equal(c, f), "events_to_frames output is not integer-valued"
    assert c.min() >= 0 and c.max() < 65536
    return c.astype(np.uint16)


def _collect(ds, indices, paths):
    counts, labels, n_ev, n_e = [], [], [], []
    for i in indices:
        fr, lab, ne, nE = ds[i]
        counts.append(_to_counts(fr)); labels.append(lab); n_ev.append(ne); n_e.append(nE)
    return dict(counts=np.stack(counts), labels=np.array(labels, np.int16),
                n_events=np.array(n_ev, np.int32), N_e=np.array(n_e, np.int32),
                paths=np.array([paths[i] for i in indices]))


def load_dvs(root):
    ds = DVSGestureDataset(root, T=100, input_scaling="raw", event_dropout=0.0)
    idx = range(len(ds))
    return _collect(ds, idx, [s[0] for s in ds.samples])


def load_nmnist(root, per_class=None, seed=0):
    """Returns the subsample plus `ref_index`: each sample's row in the reference raster
    (recorded on the FULL sorted test set, limit_per_class=None)."""
    full = NMNISTDataset(root, T=100, input_scaling="raw")
    pos = {p: i for i, (p, _) in enumerate(full.samples)}
    ds = NMNISTDataset(root, T=100, input_scaling="raw", limit_per_class=per_class, seed=seed)
    out = _collect(ds, range(len(ds)), [s[0] for s in ds.samples])
    out["ref_index"] = np.array([pos[p] for p in out["paths"]], np.int64)
    return out


def match_reference(d, ref):
    """Map DVS samples (os.listdir order is filesystem dependent) to reference-raster rows
    via (label, n_events, N_e). Requires a unique match."""
    key = {}
    for i, k in enumerate(zip(ref["labels"].tolist(), ref["n_events"].tolist(), ref["N_e"].tolist())):
        key.setdefault(k, []).append(i)
    idx = []
    for k in zip(d["labels"].tolist(), d["n_events"].tolist(), d["N_e"].tolist()):
        assert len(key.get(k, [])) == 1, f"ambiguous/missing reference match for {k}"
        idx.append(key[k][0])
    assert len(set(idx)) == len(idx)
    return np.array(idx, np.int64)


def float_frames(counts, N_e, normalise):
    """Exactly what the float model was fed. 'raw' (DVS): counts. 'per_sample_norm' (N-MNIST):
    frames / max(N_e,1), float32, as in NMNISTDataset.__getitem__."""
    f = counts.astype(np.float32)
    if normalise:
        f = np.stack([f[i] / max(int(N_e[i]), 1) for i in range(len(f))])
    return f
