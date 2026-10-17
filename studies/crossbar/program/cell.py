"""1D-ii: one write cell in ngspice with the COMPILED compact model (OSDI) and the PTM 45 nm LP BSIM4 access transistor.

    write driver --R_rl-- [row line] --(device t)--RRAM--(device b)-- ... --R_bl-- bitline driver          orientation "bl": access transistor between device and bitline
                                     --NMOS--(device t)--RRAM--(b)--R_bl--                              orientation "rl": access transistor between row line and device
SET  : the row line is pulsed to +V, the bitline held at 0          (V(t,b) > 0 closes the gap)
RESET: the row line is held at 0, the bitline pulsed to +V           (V(t,b) < 0 opens it)
Many independent copies of the cell (each with its own initial gap, its own sources and optionally its own model card) share one deck: one transient gives the flow map
gap_in -> gap_out of a single pulse for every initial gap at once. Per cell the deck measures the final gap, the energy drawn from the pulsed source, the peak current, and the
largest voltage that appears across the device and across the access transistor's terminals (for the 1.1 V rating check).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from spice import osdi
from spice.netlist import PTM_LIB

T_EDGE_S = 1e-9          # [CHOICE] rise/fall of every write pulse. The array's own RC is 10-100 ps (1D-i); 1 ns is the write driver's slew, conservative for short pulses
T_HOLD_S = 20e-9         # [CHOICE] zero-bias settle after the pulse before the gap is read off
TX_W_20F2_UM = 0.54      # um [MODEL] 1A: W = 0.6 x 20 F^2 x 45 nm (R_tx 1016 ohm, Idsat 280 uA at 1.1 V)
TX_L_UM = 0.045
C_LINE_PER_PITCH_F = 0.2e-15   # F/pitch [ASSUM, 1A/1C] the related-work line capacitance
C_RL_F = 64 * C_LINE_PER_PITCH_F    # [MODEL] a 64-bitline macro row line (12.8 fF), lumped at the cell
C_BL_F = 512 * C_LINE_PER_PITCH_F   # [MODEL] a 512-row bitline (102 fF), lumped at the cell


@dataclass(frozen=True)
class Cell:
    orientation: str = "bl"          # "bl" | "rl"   (where the access transistor sits)
    w_um: float = TX_W_20F2_UM
    v_wl: float = 1.1                # V   [CHOICE] word line at the core device's rated 1.1 V (1A)
    temp_c: float = 27.0
    r_rl: float = 10.0               # ohm series on the row-line side (driver + row wire to the cell) - 1D-i gives the delivered value
    r_bl: float = 10.0               # ohm series on the bitline side (bitline driver + bitline wire)
    model: tuple = field(default_factory=tuple)   # (('Vel0', 12.0), ...) overrides of rram.va parameters
    c_rl: float = C_RL_F             # F   row-line capacitance at the cell
    c_bl: float = C_BL_F             # F   bitline capacitance at the cell

    def with_(self, **kw) -> "Cell":
        return replace(self, **kw)


def _f(x: float) -> str:
    return f"{x:.12g}"


def model_card(name: str, params: dict | tuple = ()) -> str:
    kv = " ".join(f"{k}={_f(v)}" for k, v in dict(params).items())
    return f".model {name} RRAM {kv}".rstrip()


def pulse_deck(cell: Cell, direction: str, v: float, width_s: float, gaps_in, models: list[dict] | None = None, t_edge: float = T_EDGE_S,
               v_bias_rl: float = 0.0, v_bias_bl: float = 0.0) -> tuple[str, float]:
    """Deck applying ONE pulse (amplitude v, flat top width_s, edges t_edge) to len(gaps_in) independent cells. models: optional per-cell parameter dicts."""
    gaps = np.atleast_1d(np.asarray(gaps_in, float))
    n = gaps.size
    t1, t2, t3 = t_edge, t_edge + width_s, 2 * t_edge + width_s
    t_end = t3 + T_HOLD_S
    pwl = f"PWL(0 0 {_f(t1)} {_f(v)} {_f(t2)} {_f(v)} {_f(t3)} 0 {_f(t_end)} 0)"
    L = ["write cell pulse", f".include {PTM_LIB}", f".temp {_f(cell.temp_c)}",
         ".options method=gear reltol=1e-6 abstol=1e-12 vntol=1e-7 gmin=1e-15 itl4=500",   # abstol 1e-12 (A; on the gap node m/s = 1e-3 nm/s). 1e-15 collapses the step at the clamp
         f"Vwl wl 0 DC {_f(cell.v_wl)}", model_card("rr", cell.model)]
    if models is not None:
        for i, m in enumerate(models):
            L.append(model_card(f"rr{i}", {**dict(cell.model), **m}))
    w = f"W={_f(cell.w_um * 1e-6)} L={_f(TX_L_UM * 1e-6)}"
    for i in range(n):
        mod = f"rr{i}" if models is not None else "rr"
        src_rl = pwl if direction == "set" else f"DC {_f(v_bias_rl)}"
        src_bl = pwl if direction == "reset" else f"DC {_f(v_bias_bl)}"
        L += [f"Vr{i} s{i} 0 {src_rl}", f"Vb{i} q{i} 0 {src_bl}", f"Rr{i} s{i} r{i} {_f(max(cell.r_rl, 1e-3))}", f"Rb{i} c{i} q{i} {_f(max(cell.r_bl, 1e-3))}",
              f"Cr{i} r{i} 0 {_f(cell.c_rl)}", f"Cb{i} c{i} 0 {_f(cell.c_bl)}"]
        if cell.orientation == "bl":           # r --RRAM(t=r, b=m)-- m --NMOS-- c
            L += [f"N{i} r{i} m{i} g{i} {mod}", f"M{i} m{i} wl c{i} 0 ptm45n_lp {w}"]
            dev_t, dev_b, tx_a, tx_b = f"r{i}", f"m{i}", f"m{i}", f"c{i}"
        elif cell.orientation == "rl":         # r --NMOS-- m --RRAM(t=m, b=c)-- c
            L += [f"M{i} r{i} wl m{i} 0 ptm45n_lp {w}", f"N{i} m{i} c{i} g{i} {mod}"]
            dev_t, dev_b, tx_a, tx_b = f"m{i}", f"c{i}", f"r{i}", f"m{i}"
        else:
            raise ValueError(cell.orientation)
        L.append(f".ic v(g{i})={_f(gaps[i])}")
    # time step: the pulse edges must be resolved; ngspice's LTE control does the rest
    tmax = max(min(t_edge / 4, width_s / 20), t_end / 4000)
    L.append(f".tran {_f(t_edge / 20)} {_f(t_end)} 0 {_f(tmax)} uic")
    ctl = [".control", *osdi.control_preamble(), "set noaskquit", "set numdgt=12", "run"]
    for i in range(n):
        dev_t, dev_b, tx_a, tx_b = ((f"r{i}", f"m{i}", f"m{i}", f"c{i}") if cell.orientation == "bl" else (f"m{i}", f"c{i}", f"r{i}", f"m{i}"))
        drv = f"Vr{i}" if direction == "set" else f"Vb{i}"
        node = f"s{i}" if direction == "set" else f"q{i}"
        ctl += [f"let gg{i} = v(g{i})-v({dev_b})", f"meas tran gap{i} find gg{i} at={_f(t_end - 0.25 * T_HOLD_S)}",
                f"let pw{i} = -v({node})*i({drv})", f"meas tran e{i} integ pw{i} from=0 to={_f(t_end)}",
                f"let ia{i} = abs(i({drv}))", f"meas tran ip{i} max ia{i}",
                f"let vd{i} = abs(v({dev_t})-v({dev_b}))", f"meas tran vd{i} max vd{i}",
                f"let vx{i} = abs(v({tx_a})-v({tx_b}))", f"meas tran vx{i} max vx{i}",
                f"let vg{i} = max(abs(v(wl)-v({tx_a})),abs(v(wl)-v({tx_b})))", f"meas tran vg{i} max vg{i}"]
    ctl += [".endc", ".end"]
    return "\n".join(L + ctl) + "\n", t_end


def run_pulse(cell: Cell, direction: str, v: float, width_s: float, gaps_in, models: list[dict] | None = None, t_edge: float = T_EDGE_S, timeout: float = 7200.0) -> dict:
    gaps = np.atleast_1d(np.asarray(gaps_in, float))
    deck, _ = pulse_deck(cell, direction, v, width_s, gaps, models, t_edge)
    out = osdi.run(deck, timeout=timeout)
    s = osdi.scalars(out)
    n = gaps.size
    try:
        res = {k: np.array([s[f"{k}{i}"] for i in range(n)]) for k in ("gap", "e", "ip", "vd", "vx", "vg")}
    except KeyError as e:
        raise osdi.ToolchainError(f"pulse deck failed (missing {e}); tail:\n" + "\n".join(out.splitlines()[-25:]))
    res["e"] = np.abs(res["e"])
    return dict(gap_in=gaps, gap_out=res["gap"], energy_j=res["e"], i_peak_a=res["ip"], v_dev_max=res["vd"], v_tx_max=res["vx"], v_gate_max=res["vg"])


def read_current(gap, r_tx: float = 1016.0459, v_read: float = 0.1) -> np.ndarray:
    """[MODEL] 1F read conditions as 1F's port models them (sense/port.py): V_READ across (linear R_tx + device). Solved exactly with the sinh device (bisection, vectorised)."""
    from program.model import current
    gap = np.asarray(gap, float)
    lo, hi = np.zeros_like(gap), np.full_like(gap, v_read)
    for _ in range(80):
        vd = 0.5 * (lo + hi)
        f = current(vd, gap) * r_tx + vd - v_read
        lo, hi = np.where(f < 0, vd, lo), np.where(f < 0, hi, vd)
    return current(0.5 * (lo + hi), gap)
