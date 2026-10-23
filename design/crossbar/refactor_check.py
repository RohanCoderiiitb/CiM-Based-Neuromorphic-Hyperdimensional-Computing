#!/usr/bin/env python3
"""The refactor of the study code onto the netlist generator must not change a result. This script re-runs, with the generator, the cases whose outputs were recorded from the
OLD decks (results/baseline_old_decks/, captured immediately before the old deck-building code was removed) and compares:

  dc    the first 60 cases of wire/validate_mesh_ext.py (seed 1331): the validation metrics (|ngspice - mesh solver|) the old decks gave, vs the generated netlist's
  tran  ten 1C transient jobs (energy/latency, supply dynamics, crosstalk, bit-plane crosstalk, five-macro array): every number the old decks gave, vs the generated reduced deck's

Usage:  venv/bin/python design/crossbar/refactor_check.py [dc|tran|both]  (from anywhere)   ->  design/crossbar/results/refactor_equivalence.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "studies" / "crossbar"))
import numpy as np  # noqa: E402

OUT = HERE / "results" / "refactor_equivalence.json"
BASE = HERE / "results" / "baseline_old_decks"


def check_dc() -> dict:
    import wire.validate_mesh_ext as V
    before = json.loads((BASE / "dc_60cases_old_decks.json").read_text())["cases"]
    rng = np.random.default_rng(1331)
    keys = ("rel_icol", "rel_irow", "abs_vrail_v", "abs_vgnd_v")
    new = [V.one_case(c, rng) for c in range(len(before))]
    return dict(cases=len(before), **{f"worst_abs_difference_{k}": max(abs(n[k] - o[k]) for n, o in zip(new, before)) for k in keys},
                **{f"old_max_{k}": max(o[k] for o in before) for k in keys}, **{f"new_max_{k}": max(n[k] for n in new) for k in keys},
                same_cases=all(n["blocks"] == o["blocks"] and n["n_active"] == o["n_active"] for n, o in zip(new, before)))


def check_tran() -> dict:
    import scaleup.run_array_transient as AT
    import scaleup.run_crosstalk as XT
    import scaleup.run_crosstalk_bitplane as XB
    import scaleup.run_energy_latency as EL
    import scaleup.run_supply_dynamics as SD
    new = dict(el_a=EL.one_group((0, 8, 0, 0.72)), el_b=EL.one_group((63, 4, 1, 0.72)), sd_a=SD.job((63, 100e-12, 0)), sd_b=SD.job((0, 0.0, 1)), sd_c=SD.job((0, 1e-9, 2)),
               xt=XT.job((0, 0.5, 0)), xt2=XT.job((63, 0.75, 10)), xb=XB.job((63, 0.75, 3)), at=AT.job((32, 8)), at2=AT.job((63, 4)))
    old = json.loads((BASE / "tran_10jobs_old_decks.json").read_text())

    def walk(a, b, path=""):
        if isinstance(a, dict):
            for k in a:
                yield from walk(a[k], b[k], f"{path}/{k}")
        elif isinstance(a, list):
            for i, (x, y) in enumerate(zip(a, b)):
                yield from walk(x, y, f"{path}[{i}]")
        elif isinstance(a, (int, float)):
            yield path, float(a), float(b)

    by_key: dict[str, float] = {}
    n = exact = 0
    for k in new:
        for path, x, y in walk(new[k], old[k], k):
            n += 1
            exact += x == y
            d = abs(x - y) / abs(y) if y != 0 else (0.0 if x == 0 else float("inf"))
            key = path.split("/")[-1].split("[")[0]
            by_key[key] = max(by_key.get(key, 0.0), d)
    physical = {k: v for k, v in by_key.items() if k not in ("err_a", "i_sup_flatness")}
    return dict(jobs=len(new), numbers_compared=n, bit_identical=exact, worst_relative_difference_by_quantity=by_key,
                worst_relative_difference_physical_quantities=max(physical.values()),
                note="err_a (the settled-error samples, ~1e-16 A) and i_sup_flatness (a 1e-13 noise-floor ratio) are residuals at the ngspice noise floor, not results: the first differs by 1e-15 A absolute")


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    if which in ("dc", "both"):
        res["dc"] = check_dc()
        print("dc:", {k: v for k, v in res["dc"].items()})
    if which in ("tran", "both"):
        res["tran"] = check_tran()
        print("tran:", res["tran"]["numbers_compared"], "numbers,", res["tran"]["bit_identical"], "bit-identical, worst physical relative difference", res["tran"]["worst_relative_difference_physical_quantities"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
