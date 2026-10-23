#!/usr/bin/env python3
"""Generate a crossbar netlist from the command line.

    python design/crossbar/generate.py --macros 1 --g 8 --device resistor --caps --active-group 3 -o design/crossbar/examples/macro_512x32_g8.sp
    python design/crossbar/generate.py --macros 5 --g 4 -o /tmp/array_512x160_g4.sp          # the whole array (large)

Every dimension and resistance defaults to its name in studies/crossbar/device/constants.py (see crossbar_netlist/spec.py). The weights are a seeded random
bit matrix (the netlist needs SOME stored state; a trained weight image is loaded by the RTL, not the netlist), the active rows are one group of g rows.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crossbar_netlist import ArraySpec, full_deck, weights_to_gaps  # noqa: E402
import device.constants as C  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=C.ROWS_TOTAL)
    ap.add_argument("--macros", type=int, default=1, help=f"macros of {C.CELLS_PER_MACRO_ROW} cells; the full array has {C.N_MACROS}")
    ap.add_argument("--g", type=int, default=C.G_1C)
    ap.add_argument("--device", default="sinh", choices=["sinh", "resistor"])
    ap.add_argument("--tx", default="switch", choices=["switch", "linear", "bsim"])
    ap.add_argument("--caps", action="store_true", help="include the parasitic capacitance")
    ap.add_argument("--active-group", type=int, default=0, help="index of the group of g rows whose word lines are asserted")
    ap.add_argument("--seed", type=int, default=0, help="seed of the stored weight bits")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    spec = ArraySpec(rows=a.rows, blocks=(C.MACRO_BITLINES,) * a.macros, g=a.g, device=a.device, tx=a.tx, caps=a.caps)
    rng = np.random.default_rng(a.seed)
    w = rng.integers(0, 2, (spec.rows, spec.K // 2)).astype(bool)
    gaps = weights_to_gaps(w, spec.p)
    active = np.arange(a.active_group * a.g, min((a.active_group + 1) * a.g, spec.rows))
    deck, _ = full_deck(spec, gaps, active, title=(f"2T2R ReRAM crossbar: {spec.rows} rows x {spec.K // 2} cells ({a.macros} macro(s)), g = {a.g}, device = {a.device}, tx = {a.tx}, "
                                                     f"weights seed {a.seed}, rows {active[0]}..{active[-1]} selected"))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(deck)
    print(f"wrote {a.out}: {deck.count(chr(10))} lines, {len(deck) / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
