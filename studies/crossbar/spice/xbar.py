"""Import shim: the crossbar netlist generator lives in design/crossbar/crossbar_netlist (the design artefact); the studies call it through here.

    from spice.xbar import ArraySpec, full_deck, reduced_deck, TranSpec, run_full_op
"""
from __future__ import annotations

import sys
from pathlib import Path

_GEN = Path(__file__).resolve().parents[3] / "design" / "crossbar"
if str(_GEN) not in sys.path:
    sys.path.insert(0, str(_GEN))

from crossbar_netlist import (ArraySpec, R_FLOOR, TRAN_OPTIONS, TranSpec, device_resistance, full_deck, read_full, reduced_deck, run_full_op, weights_to_gaps)  # noqa: E402,F401
