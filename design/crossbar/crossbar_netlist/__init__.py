"""Parameterised SPICE netlist generator for the CIM-NeuroHDC ReRAM crossbar (cell -> group -> macro -> array). See gen.py and ../README.md."""
from .spec import ArraySpec, R_FLOOR, device_resistance, weights_to_gaps  # noqa: F401
from .gen import TRAN_OPTIONS, TranSpec, full_deck, read_full, reduced_deck  # noqa: F401


def run_full_op(spec, gaps, active, **kw):
    """Generate the hierarchical netlist, solve it with ngspice (.op) and return the column currents etc. (see gen.read_full)."""
    from spice.runner import run_deck_prints
    deck, probes = full_deck(spec, gaps, active, **kw)
    return read_full(spec, probes, run_deck_prints(deck), active)
