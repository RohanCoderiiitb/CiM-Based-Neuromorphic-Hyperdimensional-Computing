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
