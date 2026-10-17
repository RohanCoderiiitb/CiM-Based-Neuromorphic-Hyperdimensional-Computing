"""1D-ii: pulse flow-map tables from the COMPILED compact model.

The device has one state variable (the gap), so one rectangular pulse (amplitude V, width w, the 1D-i cell around it) is a deterministic map gap_in -> gap_out. One ngspice
transient with 301 independent copies of the cell (initial gaps 0.2-1.7 nm) gives that map on a 5 pm grid, together with the energy drawn from the pulsed source, the peak
current and the largest device / transistor voltages. A table is the map over a grid of amplitudes x widths. The program-verify loop (program/verify.py) then composes maps:
exact for the model up to the interpolation between grid gaps (checked against direct ngspice pulse trains in program/validate_loop.py).

Cell (1D-i handoff): access transistor on the BITLINE side ("bl"; the only orientation in which a SET reaches the device), 20 F^2 (W = 0.54 um), word line 1.1 V (rated),
row-side series 17 ohm (both-end drivers 10 ohm each + half a macro row of 0.72 ohm/pitch + rail), bitline side 379 ohm (bitline driver 10 ohm + 512 pitches of 0.72 ohm:
the far row, the worst case), row-line and bitline capacitance 12.8 / 102 fF.
Usage: python -m program.tables [--which main|temp|width]"""
from __future__ import annotations

import argparse
import hashlib
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from program.cell import Cell, run_pulse

GAPS = np.round(np.linspace(0.2, 1.7, 301), 6)
WIDTHS = tuple(float(f"{10 ** (k / 4):.4g}") for k in range(-32, -3))      # 10 ns ... 100 ms, 4 per decade
V_SET = tuple(np.round(np.arange(0.6, 2.401, 0.05), 3))
V_RESET = tuple(np.round(np.arange(0.5, 2.401, 0.05), 3))
CELL = Cell(orientation="bl", r_rl=17.0, r_bl=379.0)
R_RL_NEAR, R_BL_NEAR = 17.0, 11.0      # ohm: a row next to the bitline drivers (sensitivity)


def key(cell: Cell, direction: str) -> str:
    h = hashlib.sha1(repr((cell, direction, GAPS.tobytes())).encode()).hexdigest()[:10]
    return f"{direction}_{cell.orientation}_W{cell.w_um:g}_wl{cell.v_wl:g}_T{cell.temp_c:g}_{h}"


def _one(a):
    cell, direction, v, w, gaps = a
    try:
        r = run_pulse(cell, direction, v, w, gaps)
        return (v, w, r)
    except Exception as e:                       # noqa: BLE001 - recorded, the table entry stays NaN
        return (v, w, dict(error=str(e)[-300:]))


def build(cell: Cell, direction: str, volts, widths, gaps=GAPS, procs: int = 30, force: bool = False) -> dict:
    RP.PROGRAM_TABLES.mkdir(parents=True, exist_ok=True)
    f = RP.PROGRAM_TABLES / (key(cell, direction) + f"_nv{len(volts)}_nw{len(widths)}.npz")
    if f.exists() and not force:
        z = np.load(f, allow_pickle=False)
        return {k: z[k] for k in z.files}
    jobs = [(cell, direction, float(v), float(w), gaps) for v in volts for w in widths]
    with Pool(procs) as p:
        res = p.map(_one, jobs, chunksize=1)
    shape = (len(volts), len(widths), len(gaps))
    out = {k: np.full(shape, np.nan) for k in ("gap_out", "energy_j", "i_peak_a", "v_dev_max", "v_tx_max", "v_gate_max")}
    errors = []
    vi = {float(v): i for i, v in enumerate(volts)}
    wi = {float(w): i for i, w in enumerate(widths)}
    for v, w, r in res:
        if "error" in r:
            errors.append(dict(v=v, w=w, error=r["error"]))
            continue
        for k in out:
            out[k][vi[v], wi[w]] = r[k]
    out.update(volts=np.asarray(volts, float), widths=np.asarray(widths, float), gaps=np.asarray(gaps, float))
    np.savez_compressed(f, **out)
    (f.with_suffix(".json")).write_text(json.dumps(dict(cell=repr(cell), direction=direction, errors=errors), indent=1))
    return out


def main_tables() -> dict:
    return dict(set=build(CELL, "set", V_SET, WIDTHS), reset=build(CELL, "reset", V_RESET, WIDTHS))


def temp_tables(temp_c: float = 85.0) -> dict:
    c = CELL.with_(temp_c=temp_c)
    vs = tuple(np.round(np.arange(0.6, 2.401, 0.1), 3))
    vr = tuple(np.round(np.arange(0.5, 2.401, 0.1), 3))
    ws = tuple(w for w in WIDTHS if abs(np.log10(w) - round(np.log10(w))) < 1e-9)
    return dict(set=build(c, "set", vs, ws), reset=build(c, "reset", vr, ws))


CELL_DESIGN = Cell(orientation="bl", w_um=5.4, v_wl=3.0, r_rl=17.0, r_bl=11.0)    # OUT OF ENVELOPE (d1_characterise): 200 F^2, thick-oxide 3 V word line, near-row bitline


def design_tables() -> dict:
    """The write device that reaches the design-adjacent states (0.35 / 1.55 nm) within 1 us - a DIFFERENT ARRAY, flagged wherever it is used."""
    ws = tuple(w for w in WIDTHS if w <= 1.01e-6)
    return dict(set=build(CELL_DESIGN, "set", V_SET, ws), reset=build(CELL_DESIGN, "reset", V_RESET, ws))


def near_tables() -> dict:
    c = CELL.with_(r_rl=R_RL_NEAR, r_bl=R_BL_NEAR)
    vs = tuple(np.round(np.arange(0.6, 2.401, 0.1), 3))
    ws = tuple(w for w in WIDTHS if abs(np.log10(w) - round(np.log10(w))) < 1e-9)
    return dict(set=build(c, "set", vs, ws))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", default="main", choices=("main", "temp", "near", "design", "all"))
    a = ap.parse_args()
    if a.which in ("main", "all"):
        t = main_tables()
        print("main tables:", {k: v["gap_out"].shape for k, v in t.items()}, "NaN entries:", {k: int(np.isnan(v["gap_out"]).sum()) for k, v in t.items()})
    if a.which in ("temp", "all"):
        t = temp_tables()
        print("85 C tables:", {k: v["gap_out"].shape for k, v in t.items()}, "NaN entries:", {k: int(np.isnan(v["gap_out"]).sum()) for k, v in t.items()})
    if a.which in ("design", "all"):
        t = design_tables()
        print("design-capable (out-of-envelope) tables:", {k: v["gap_out"].shape for k, v in t.items()})
    if a.which in ("near", "all"):
        t = near_tables()
        print("near-row tables:", {k: v["gap_out"].shape for k, v in t.items()})
