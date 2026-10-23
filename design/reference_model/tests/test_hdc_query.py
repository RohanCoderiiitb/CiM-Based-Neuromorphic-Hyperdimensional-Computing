"""
Data-free tests of the Phase 2-4 reference (model/fixedpoint/hdc_query.py): the structural identities the RTL relies on, on random data and on the exported golden rasters.
Run:  python tests/test_hdc_query.py   (or pytest)
Written BEFORE the RTL (Phase 2-4 method: extend the reference first, export vectors, then write the RTL against them).
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model", "fixedpoint"))
import hdc_query as HQ  # noqa: E402
from int_model import xnor_scores_prefix  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
VEC = os.path.join(HERE, "..", "tb", "vectors", "dvsgesture")
T, N = 100, 10


def rand_case(rng, dens=0.4):
    S = (rng.random((T, 20)) < dens).astype(np.uint8)
    a = rng.integers(0, 2, (N, 20)).astype(np.uint8)
    b = rng.integers(0, 2, (N, T)).astype(np.uint8)
    return S, a, b


def test_factorized_is_identical_to_unfactorized_on_the_expansion():
    rng = np.random.default_rng(1)
    for dens in (0.0, 0.1, 0.5, 0.9, 1.0):
        S, a, b = rand_case(rng, dens)
        hv = HQ.expand_r1(a, b)
        assert np.array_equal(HQ.agree_unfactorized(S, hv), HQ.agree_factorized(S, a, b)), dens


def test_unfactorized_agrees_with_the_phase0_score_definition():
    rng = np.random.default_rng(2)
    S, a, b = rand_case(rng)
    hv = HQ.expand_r1(a, b)
    ref = xnor_scores_prefix(S, hv)                                          # Phase 0: the definition of the score
    assert np.array_equal(HQ.prefix_scores(HQ.agree_unfactorized(S, hv)), ref)
    assert ref.max() <= HQ.SCORE_MAX and ref.min() >= 0


def test_unipolar_identity_at_every_prefix():
    rng = np.random.default_rng(3)
    for _ in range(5):
        S = (rng.random((T, 20)) < rng.random()).astype(np.uint8)
        hv = rng.integers(0, 2, (N, T, 20)).astype(np.uint8)                  # unconstrained class hypervector
        x = xnor_scores_prefix(S, hv)
        u = HQ.unipolar_prefix(S, hv)
        assert np.array_equal(x, u + HQ.class_independent_offset(S)[:, None])      # exact, not only argmax-equal
        assert np.array_equal(x.argmax(axis=1), u.argmax(axis=1))


def test_top2_tournament_equals_sort_with_ties():
    rng = np.random.default_rng(4)
    for n in (2, 7, 10, 16, 24):
        for hi in (2, 5, 2000):
            for _ in range(300):
                v = rng.integers(0, hi + 1, n)
                i, v1, v2 = HQ.top2_tournament(v)
                s = np.sort(v)[::-1]
                assert (v1, v2) == (s[0], s[1]) and i == int(np.argmax(v))


def test_exit_point_semantics():
    prefix = np.array([[0, 0, 0], [5, 3, 0], [9, 4, 1], [12, 5, 1]])           # margins 0, 2, 5, 7
    assert HQ.exit_point(prefix, 5) == (2, 0, True)                            # first t with margin >= 5
    assert HQ.exit_point(prefix, 6) == (3, 0, True)
    assert HQ.exit_point(prefix, 8) == (3, 0, False)                           # never fires: last timestep, final argmax
    assert HQ.exit_point(np.array([[3, 3, 0]]), 1) == (0, 0, False)            # tie: margin 0, lowest index
    # the prediction emitted at exit is the argmax OF THAT TIMESTEP, not of the final scores
    p = np.array([[10, 0], [10, 1], [10, 12]])                                  # margins 10, 9, 2; the final leader is class 1
    assert HQ.exit_point(p, 9) == (0, 0, True)                                  # exits at t = 0 with class 0, although class 1 wins at the end
    assert HQ.exit_point(p, 13) == (2, 1, False)


def test_theta_from_bipolar_is_exact():
    rng = np.random.default_rng(5)
    S, a, b = rand_case(rng)
    pre = HQ.prefix_scores(HQ.agree_unfactorized(S, HQ.expand_r1(a, b)))
    bip = 2 * pre - 20 * (np.arange(T)[:, None] + 1)                           # the software study's bipolar prefix score
    m_bip = np.sort(bip, axis=1)[:, -1] - np.sort(bip, axis=1)[:, -2]
    assert np.array_equal(m_bip, 2 * HQ.margins(pre))
    for th in (1.0, 2.0, 5.0, 64.0, 129.0):
        assert (m_bip >= th).tolist() == (HQ.margins(pre) >= HQ.theta_from_bipolar(th)).tolist()


def test_sweep_matches_exit_point_per_sample():
    rng = np.random.default_rng(6)
    pres, labels = [], rng.integers(0, N, 20)
    for _ in range(20):
        S, a, b = rand_case(rng, rng.random())
        pres.append(HQ.prefix_scores(HQ.agree_unfactorized(S, HQ.expand_r1(a, b))))
    pres = np.stack(pres)
    for th in (1, 3, 10, 40, 300, HQ.THETA_NEVER):
        row = HQ.sweep(pres, labels, [th])[0]
        pr = [HQ.exit_point(p, th) for p in pres]
        assert abs(row["mean_exit_timestep"] - np.mean([t + 1 for t, _, _ in pr])) < 1e-12
        assert abs(row["accuracy"] - np.mean([p == l for (_, p, _), l in zip(pr, labels)])) < 1e-12


def test_never_threshold_exceeds_every_possible_margin():
    assert HQ.THETA_NEVER > HQ.SCORE_MAX and HQ.THETA_NEVER == (1 << HQ.W_THETA) - 1


def test_replay_of_the_stored_software_sweep():
    """The integer reference reproduces studies/algorithm/phase3_experiments exp2_early_exit.json (accuracy and mean exit timestep, every threshold) for the frozen baseline."""
    f = os.path.join(REPO, "studies", "algorithm", "phase3_experiments", "artifacts", "tables", "exp2_early_exit.json")
    if not (os.path.exists(f) and os.path.exists(os.path.join(VEC, "seed0.npz"))):
        return
    exp2 = json.load(open(f))
    c = np.load(os.path.join(VEC, "counts.npz"))
    labels = c["labels"].astype(int)
    for seed in (0, 1, 2):
        z = np.load(os.path.join(VEC, f"seed{seed}.npz"))
        pre = z["score_xnor_prefix"].astype(np.int64)
        sw = exp2[f"dvsgesture_seed{seed}"]["theta_sweep"]
        mine = HQ.sweep(pre, labels, [HQ.theta_from_bipolar(r["theta"]) for r in sw])
        for a, b in zip(sw, mine):
            assert abs(a["accuracy_at_exit"] - b["accuracy"]) < 1e-12 and abs(a["mean_exit_timestep"] - b["mean_exit_timestep"]) < 1e-9


def test_r1_golden_vectors_factorized_equals_unfactorized():
    f = os.path.join(VEC, "r1_seed0.npz")
    if not os.path.exists(f):
        return
    z = np.load(f)
    for i in range(0, 240, 17):
        assert np.array_equal(HQ.prefix_scores(HQ.agree_factorized(z["spikes"][i], z["a_bits"], z["b_bits"])), z["score_xnor_prefix"][i])


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
