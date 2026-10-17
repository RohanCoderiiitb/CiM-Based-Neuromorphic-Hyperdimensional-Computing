"""Loader + self-consistency verifier for the golden vectors (importable by testbenches)."""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "fixedpoint"))
from int_model import snn_forward, xnor_scores_prefix  # noqa: E402
from export_weights import read_mem, unpack_rows, decode_planes  # noqa: E402


def load(vec_root, dataset, seed, weight_tag=None):
    weight_tag = seed if weight_tag is None else weight_tag
    d = f"{vec_root}/{dataset}"
    man = json.load(open(f"{d}/manifest.json"))
    c = dict(np.load(f"{d}/counts.npz"))
    s = dict(np.load(f"{d}/seed{seed}.npz"))
    W = decode_planes(unpack_rows(read_mem(f"{vec_root}/weights/weights_seed{weight_tag}_160b.mem"), 20))
    return man, c, s, W


def verify(vec_root, dataset, seed, class_hv, n=None, weight_tag=None):
    """Re-run the integer model from the exported counts + weight image and require every
    exported X/Vp/V/spike/score value to match. Returns number of samples checked."""
    man, c, s, W = load(vec_root, dataset, seed, weight_tag)
    n = n or len(c["labels"])
    for i in range(n):
        tr = snn_forward(c["counts"][i], W, s["thresh_int"][i])
        assert np.array_equal(tr.X, s["X"][i]) and np.array_equal(tr.Vp, s["Vp"][i])
        assert np.array_equal(tr.V, s["V"][i]) and np.array_equal(tr.S, s["spikes"][i])
        sc = xnor_scores_prefix(tr.S, class_hv)
        assert np.array_equal(sc, s["score_xnor_prefix"][i])
        assert int(np.argmax(sc[-1])) == int(s["pred"][i])
    return n


def load_events(vec_root, dataset):
    """Exported AER streams. Returns dict; stream of exported sample i is
    aer[offset[i]:offset[i+1]] and belongs to counts.npz row sample_row[i]."""
    return dict(np.load(f"{vec_root}/{dataset}/events.npz"))


def unpack_aer(words, dataset):
    sh = 7 if dataset == "dvsgesture" else 6
    w = words.astype(np.int64)
    return w & ((1 << sh) - 1), (w >> sh) & ((1 << sh) - 1), w >> (2 * sh)       # x, y, p


def verify_events(vec_root, dataset, n_counter_check=2):
    """Every exported stream -> addr_gen (eq. 19) -> timestep rule must give the exported addr and
    that sample's counts exactly. The event-by-event boundary counter is checked on the shortest
    `n_counter_check` streams (pure-python loop). Returns number of streams checked."""
    from events import GEOM, address, stream_counts, boundary_counter_bins, timestep_of_event
    ev = load_events(vec_root, dataset)
    counts = np.load(f"{vec_root}/{dataset}/counts.npz")["counts"]
    H, W = GEOM[dataset]
    off = ev["offset"]
    for i, row in enumerate(ev["sample_row"]):
        x, y, p = unpack_aer(ev["aer"][off[i]:off[i + 1]], dataset)
        a = address(x, y, p, H, W)
        assert np.array_equal(a, ev["addr"][off[i]:off[i + 1]]), f"addr mismatch, stream {i}"
        assert np.array_equal(stream_counts(a), counts[row]), f"counts mismatch, stream {i}"
    for i in np.argsort(ev["n_events"])[:n_counter_check]:
        n = int(ev["n_events"][i])
        assert np.array_equal(boundary_counter_bins(n), timestep_of_event(n))
    return int(len(ev["sample_row"]))
