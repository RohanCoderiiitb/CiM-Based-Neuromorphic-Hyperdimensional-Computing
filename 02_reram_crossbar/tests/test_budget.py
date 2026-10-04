"""Budget framework: hand-computed cases."""
import math

import pytest

from solver.budget import DETERMINISTIC, RANDOM, Term, close_budget


def test_hand_case_closes():
    # Delta = 100 uA -> Delta/2 = 50; headroom 20% -> limit 40.
    # random 5-sigma terms 9 and 12 -> rss = 15 ; deterministic 3 + 4 = 7 ; total 22 < 40
    r = close_budget(100e-6, [Term("spread", RANDOM, 9e-6), Term("comp", RANDOM, 12e-6),
                              Term("leak", DETERMINISTIC, 3e-6), Term("resid", DETERMINISTIC, 4e-6)], 0.2)
    assert r.limit_a == pytest.approx(40e-6)
    assert r.random_rss_a == pytest.approx(15e-6)
    assert r.deterministic_sum_a == pytest.approx(7e-6)
    assert r.total_error_a == pytest.approx(22e-6)
    assert r.closes and r.margin_left_a == pytest.approx(18e-6)
    assert r.binding == "comp"
    assert r.breakdown["spread"]["frac_of_delta"] == pytest.approx(0.09)
    assert r.breakdown["leak"]["frac_of_limit"] == pytest.approx(3 / 40)


def test_hand_case_fails_and_quadrature_not_linear():
    # random 30 and 40 -> rss 50 (NOT 70). limit 40 -> fails because 50 > 40
    r = close_budget(100e-6, [Term("a", RANDOM, 30e-6), Term("b", RANDOM, 40e-6)], 0.2)
    assert r.random_rss_a == pytest.approx(50e-6) and not r.closes
    # the same numbers treated as deterministic add linearly to 70
    r2 = close_budget(100e-6, [Term("a", DETERMINISTIC, 30e-6), Term("b", DETERMINISTIC, 40e-6)], 0.2)
    assert r2.total_error_a == pytest.approx(70e-6)


def test_strict_boundary_and_headroom():
    # total exactly equal to the limit does not close (strict)
    assert not close_budget(100e-6, [Term("x", DETERMINISTIC, 40e-6)], 0.2).closes
    assert close_budget(100e-6, [Term("x", DETERMINISTIC, 40e-6)], 0.0).closes     # limit 50 with no headroom
    assert close_budget(100e-6, [Term("x", DETERMINISTIC, 39.99e-6)], 0.2).closes


def test_no_terms_closes_and_has_no_binding():
    r = close_budget(10e-6, [], 0.2)
    assert r.closes and r.total_error_a == 0 and r.binding == ""


def test_compression_is_refused_as_a_term():
    with pytest.raises(ValueError, match="compression"):
        Term("sense-resistor compression", DETERMINISTIC, 1e-6)
    with pytest.raises(ValueError, match="compression"):
        Term("Compress", RANDOM, 1e-6)


def test_input_validation():
    with pytest.raises(ValueError):
        Term("x", "bogus", 1.0)
    with pytest.raises(ValueError):
        Term("x", RANDOM, -1.0)
    with pytest.raises(ValueError):
        close_budget(0.0, [], 0.2)
    with pytest.raises(ValueError):
        close_budget(1.0, [Term("x", RANDOM, 1), Term("x", RANDOM, 1)], 0.2)
    with pytest.raises(ValueError):
        close_budget(1.0, [], 1.0)


def test_binding_is_largest_standalone_value():
    r = close_budget(1.0, [Term("small", RANDOM, 0.01), Term("big", DETERMINISTIC, 0.05), Term("mid", RANDOM, 0.03)], 0.2)
    assert r.binding == "big" and math.isclose(r.total_error_a, 0.05 + math.hypot(0.01, 0.03))
