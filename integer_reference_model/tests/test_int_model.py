"""
Data-free tests of the integer reference model. Run:  python tests/test_int_model.py   (or pytest)

These use the REAL frozen weights/thresholds but SYNTHETIC event streams (pushed through the
original events_to_frames). They validate the machinery; the actual Phase-0 gate is
model/fixedpoint/run_phase0.py on the real datasets.
"""
import os, sys, tempfile
from fractions import Fraction
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model", "fixedpoint"))
import _paths as P  # noqa: E402
sys.path.insert(0, os.path.join(P.MODEL_DIR, "export"))
from neurohdc import events_to_frames  # noqa: E402  (original, unmodified)
from quantize import load_int_params, exact_ceil_div, thresholds  # noqa: E402
from int_model import (snn_forward, snn_forward_batch, event_serial_X, bitplane_X,  # noqa: E402
                       xnor_scores_prefix, bipolar_scores, predict)
import pipeline as PL  # noqa: E402
import export_weights as EW  # noqa: E402
import export_vectors as EV  # noqa: E402
import load_vectors as LV  # noqa: E402
from run_phase0 import extraction_check  # noqa: E402

CK = [f"{P.CKPT_DIR}/frozen_seed{s}.pt" for s in (0, 1, 2)]


def synth_counts(rng, n_events=120_000, T=100):
    """Hot-spot synthetic sensor stream -> (counts [T,512], n_events)."""
    lam = rng.lognormal(0, 1.5, size=(2, 16, 16)); lam /= lam.sum()
    cell = rng.choice(512, size=n_events, p=lam.reshape(-1))
    p, r, c = cell // 256, (cell % 256) // 16, cell % 16
    x = c * 8 + rng.integers(0, 8, n_events); y = r * 8 + rng.integers(0, 8, n_events)
    fr, ne, _ = events_to_frames(x, y, p, T, 128, 128)
    return np.rint(fr).astype(np.uint16), ne


def test_exact_ceil():
    assert exact_ceil_div(566.5, 0.5) == 1133                 # exactly representable, true value is 1133
    assert exact_ceil_div(566.5000001, 0.5) == 1134
    # float ceil(v/s) can disagree with the exact ceil somewhere near integers; exact must equal the Fraction ceil
    rng = np.random.default_rng(1); bad = 0
    for _ in range(20000):
        s = float(np.float32(rng.uniform(1e-3, 2e-3))); k = int(rng.integers(5000, 12000))
        v = float(np.float32(k * s))                            # v ~= k*s, usually NOT exactly
        ex = exact_ceil_div(v, s); assert ex == -((-Fraction(v) // Fraction(s)))
        bad += int(np.ceil(v / s) != ex)
    print(f"  (naive float ceil disagreed with exact ceil in {bad}/20000 near-integer trials)")


def test_extraction_bit_exact():
    for c in CK + [f"{P.CKPT_DIR}/nmnist_seed0.pt"]:
        prm = load_int_params(c)
        assert extraction_check(prm) and prm.W.dtype == np.int8 and prm.W.min() >= -127
        assert (np.abs(prm.W).max(1) == 127).all()             # per-channel scale => each row hits 127
        assert np.array_equal(prm.thresh_int, thresholds(prm.v_thresh, prm.scale))


def test_int_vs_float_synthetic():
    rng = np.random.default_rng(0)
    for ck in CK:
        prm = load_int_params(ck)
        counts = np.stack([synth_counts(rng, int(rng.integers(60_000, 400_000)))[0] for _ in range(30)])
        Sf, Pf = PL.float_run(ck, counts.astype(np.float32))
        tr, thr, pred = PL.int_run(prm, counts)
        cmp = PL.compare(tr.S, Sf, tr, thr)
        rate = tr.S.mean()
        assert 0.05 < rate < 0.95, f"degenerate synthetic firing rate {rate}"
        print(f"  {os.path.basename(ck)}: rate {rate:.3f}, differing spikes {cmp['differing_spikes']}/{cmp['spikes_compared']}, "
              f"pred equal {(pred == Pf).sum()}/30, first margins {[f['margin_int'] for f in cmp['first_divergences']]}")
        assert cmp["differing_spikes"] == 0 or cmp["max_abs_first_margin"] <= 2  # any difference must be a near-threshold tie


def test_identities_and_planes():
    rng = np.random.default_rng(3)
    prm = load_int_params(CK[0]); planes = EW.weight_planes(prm.W)
    assert np.array_equal(EW.decode_planes(planes), prm.W)
    counts, _ = synth_counts(rng, 50_000)
    for t in range(0, 100, 7):
        X = counts[t].astype(np.int64) @ prm.W.astype(np.int64).T
        assert np.array_equal(event_serial_X(counts[t], prm.W), X)
        assert np.array_equal(bitplane_X(counts[t], planes, 16), X)


def test_sign_plane_directed():
    """k=7 sign handling: weights -128, -127, -1, 0, +1, +127 in one row; counts incl. max."""
    W = np.zeros((20, 512), np.int8)
    W[0, :6] = [-128, -127, -1, 0, 1, 127]
    pl = EW.weight_planes(W); assert np.array_equal(EW.decode_planes(pl), W)
    for c in ([1, 1, 1, 1, 1, 1], [65535, 0, 0, 0, 0, 0], [0, 65535, 3, 9, 65535, 65535]):
        ct = np.zeros(512, np.uint16); ct[:6] = c
        X = ct.astype(np.int64) @ W.astype(np.int64).T
        assert np.array_equal(bitplane_X(ct, pl, 16), X)


def test_score_forms_agree():
    rng = np.random.default_rng(5); prm = load_int_params(CK[0])
    for _ in range(20):
        S = (rng.random((100, 20)) < 0.4).astype(np.uint8)
        x = xnor_scores_prefix(S, prm.class_hv)[-1]; b = bipolar_scores(S, prm.class_hv)
        assert np.array_equal(b, 2 * x - 2000) and np.argmax(b) == predict(S, prm.class_hv)[0]


def test_reset_semantics():
    W = np.zeros((20, 512), np.int8); W[:, 0] = 10
    c = np.zeros((6, 512), np.uint16); c[:, 0] = 1                   # X = 10 per step
    tr = snn_forward(c, W, np.full(20, 25))
    assert tr.Vp[:, 0].tolist() == [10, 20, 30, 10, 20, 30]           # fires at 30>=25, hard reset to 0
    assert tr.S[:, 0].tolist() == [0, 0, 1, 0, 0, 1] and tr.V[:, 0].tolist() == [10, 20, 0, 10, 20, 0]
    tr = snn_forward(c, W, np.full(20, 20))                            # equality fires (>=)
    assert tr.S[:, 0].tolist() == [0, 1, 0, 1, 0, 1]


def test_nmnist_normalised_path():
    """N-MNIST model sees c/N_e -> integer threshold is ceil(v_thresh*N_e/s_j) per sample."""
    rng = np.random.default_rng(11); ck = f"{P.CKPT_DIR}/nmnist_seed0.pt"
    prm = load_int_params(ck); counts, N_e = [], []
    for _ in range(40):
        n = int(rng.integers(2000, 9000)); c, ne = synth_counts(rng, n); counts.append(c); N_e.append(ne // 100)
    counts = np.stack(counts); N_e = np.array(N_e)
    Sf, Pf = PL.float_run(ck, D_frames(counts, N_e), bs=20)
    tr, thr, pred = PL.int_run(prm, counts, N_e, normalised=True)
    cmp = PL.compare(tr.S, Sf, tr, thr)
    print(f"  nmnist: rate {tr.S.mean():.3f}, differing spikes {cmp['differing_spikes']}/{cmp['spikes_compared']}, "
          f"first margins {[f['margin_int'] for f in cmp['first_divergences']]}, pred equal {(pred == Pf).sum()}/40")
    assert 0.02 < tr.S.mean() < 0.98


def D_frames(counts, N_e):
    import data as D
    return D.float_frames(counts, N_e, normalise=True)


def test_vector_roundtrip():
    rng = np.random.default_rng(9); prm = load_int_params(CK[0])
    n = 4; counts = np.stack([synth_counts(rng, 90_000)[0] for _ in range(n)])
    tr, thr, pred = PL.int_run(prm, counts)
    with tempfile.TemporaryDirectory() as td:
        EW.export_weight_image(f"{td}/weights", 0, prm.W, prm.thresh_int, 15); EW.verify_image(f"{td}/weights", 0, prm.W)
        d = f"{td}/ds"; os.makedirs(d)
        EV.export_counts(d, dict(counts=counts, labels=np.zeros(n, np.int16), n_events=np.zeros(n, np.int32),
                                 N_e=np.zeros(n, np.int32), paths=np.array(["s"] * n)))
        pref = np.stack([xnor_scores_prefix(tr.S[i], prm.class_hv) for i in range(n)])
        EV.export_seed(d, 0, tr, thr, pred, pref, pred, np.ones(n))
        EV.write_manifest(d, "ds", {})
        assert LV.verify(td, "ds", 0, prm.class_hv) == n


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            print(name); fn()
    print("ALL PASSED")
