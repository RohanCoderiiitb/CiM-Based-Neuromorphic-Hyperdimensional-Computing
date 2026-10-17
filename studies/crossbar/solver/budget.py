"""The margin-budget framework (1B).

Units: every term is an error current in amps, and every result is also expressed as a FRACTION OF THE WORST DIFFERENTIAL
STEP Delta (measured per operating point at its actual location, never assumed).

Decision margin: a count k is told from k+1 when the measured value lands nearer k, so the total error budget is Delta/2.

Combination rule (plan, PHASE1B_PLAN.md):
    total_error = sum(uncorrectable deterministic terms) + sqrt(sum((random terms at n-sigma)^2))
    closes  <=>  total_error < (Delta/2) * (1 - headroom)

Compression is deliberately NOT a term: it is what makes Delta smaller than its uncompressed value, so it is already inside Delta.
`add_term` refuses a term named like compression to make double-counting a loud error rather than a silent one.
Correctable terms are applied by the readout (ladder / per-group offset) and enter only through their RESIDUAL, passed in as a term.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

RANDOM = "random"            # already scaled to n-sigma by the caller; combined in quadrature
DETERMINISTIC = "deterministic"   # uncorrectable; adds linearly
_FORBIDDEN = ("compress",)   # compression lives inside Delta


@dataclass(frozen=True)
class Term:
    name: str
    kind: str
    value_a: float      # error current in amps, >= 0 (for RANDOM: already at n-sigma)

    def __post_init__(self):
        if self.kind not in (RANDOM, DETERMINISTIC):
            raise ValueError(f"term kind must be {RANDOM!r} or {DETERMINISTIC!r}, got {self.kind!r}")
        if self.value_a < 0 or not np.isfinite(self.value_a):
            raise ValueError(f"term {self.name!r}: value must be finite and >= 0, got {self.value_a}")
        if any(f in self.name.lower() for f in _FORBIDDEN):
            raise ValueError(f"term {self.name!r}: compression is not a budget line (it is inside Delta); double-counting refused")


@dataclass
class BudgetResult:
    closes: bool
    delta_a: float
    headroom: float
    limit_a: float                  # (Delta/2) * (1 - headroom)
    total_error_a: float
    random_rss_a: float
    deterministic_sum_a: float
    breakdown: dict = field(default_factory=dict)   # name -> {'kind','value_a','frac_of_delta','frac_of_limit'}
    binding: str = ""               # term with the largest standalone value; "" if no terms
    margin_left_a: float = 0.0      # limit - total (negative if over budget)

    @property
    def margin_left_frac_of_limit(self) -> float:
        return self.margin_left_a / self.limit_a if self.limit_a > 0 else float("-inf")


def close_budget(delta_a: float, terms: list[Term], headroom: float) -> BudgetResult:
    """Combine terms. Returns (closes?, breakdown, binding term) as a BudgetResult."""
    if not (0.0 <= headroom < 1.0):
        raise ValueError("headroom must be in [0, 1)")
    if not np.isfinite(delta_a) or delta_a <= 0:
        raise ValueError(f"Delta must be finite and positive, got {delta_a}")
    names = [t.name for t in terms]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate term names: {names}")
    det = sum(t.value_a for t in terms if t.kind == DETERMINISTIC)
    rss = float(np.sqrt(sum(t.value_a ** 2 for t in terms if t.kind == RANDOM)))
    total = det + rss
    limit = 0.5 * delta_a * (1.0 - headroom)
    br = {t.name: dict(kind=t.kind, value_a=t.value_a, frac_of_delta=t.value_a / delta_a, frac_of_limit=t.value_a / limit)
          for t in terms}
    binding = max(terms, key=lambda t: t.value_a).name if terms else ""
    # strict inequality, per the plan's rule
    return BudgetResult(closes=bool(total < limit), delta_a=delta_a, headroom=headroom, limit_a=limit, total_error_a=total,
                        random_rss_a=rss, deterministic_sum_a=det, breakdown=br, binding=binding, margin_left_a=limit - total)
