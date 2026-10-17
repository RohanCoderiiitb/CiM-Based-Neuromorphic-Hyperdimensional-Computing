"""1D-i D1: can the read-sized array carry a write at all. Row-parallel SET of the whole selected row on the full five-macro row deck (BSIM4 access transistors, row line,
both-end drivers, supply rail, bitline wire, ground rail), at the write voltage.

Snapshots (DC, the device a fixed resistor at its state):
  before        every target still HRS: the voltage that reaches each target device when the pulse arrives (the threshold check)
  last          every target already LRS except ONE per macro at its worst row-line position: the voltage left for the last device to switch while all its neighbours draw
                their post-switch current (a target that does not reach threshold here is not slowly programmed, it is not programmed)
  after         every target LRS: the peak write current through drivers, row line and rails
Swept: v_drive 0.8-2.5 V, physical row (1, 256 = rail worst, 512 = bitline worst), driver resistance, rail resistance, orientation; parallelism N cells per pulse.
The device thresholds are SWEPT (0.8-2.0 V) in post-processing: a target is written iff its 'before' AND 'last' voltages exceed vth (for a time > tmin, see the transient).
Usage: python -m write.d1_parallel"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from spice import osdi
from write import rowdeck as RD, run as R

V_DRIVE = tuple(np.round(np.arange(0.8, 2.51, 0.1), 2))
V_TH = tuple(np.round(np.arange(0.8, 2.01, 0.1), 2))
V_WL = (1.1, 1.5, 1.8, 2.5)     # V: 1.1 = the core device's rating [1A]; above it is gate overstress of a 1.1 V device, evaluated to show what a write would need
ROWS = (1, 256, 512)
R_WDRV = (5.0, 10.0, 20.0, 50.0)
R_RAIL = (0.0072, 0.072)
SEED = 11
TX_RATING_V = 1.1           # V [ASSUM, 1A] the PTM 45 nm LP core device's nominal supply, used as the terminal-voltage rating


def weights(seed: int = SEED) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 2, RD.N_BL // 2)


def set_targets(wbits: np.ndarray, n_par: int | None = None) -> np.ndarray:
    """The LRS device of every cell (stored 1 -> '+', even bitline; 0 -> '-'), optionally only the first n_par cells of each macro, spread evenly over macros."""
    tg = np.zeros(RD.N_BL, bool)
    tg[0::2] = wbits == 1
    tg[1::2] = wbits == 0
    if n_par is not None and n_par < RD.N_BL // 2:
        keep = np.zeros(RD.N_BL // 2, bool)
        per = [n_par // RD.N_MACROS + (1 if m < n_par % RD.N_MACROS else 0) for m in range(RD.N_MACROS)]
        for m, k in enumerate(per):
            cells = np.arange(m * 32, m * 32 + 32)
            centre_first = cells[np.argsort(np.abs(cells - (m * 32 + 15.5)))]      # worst row-line positions first
            keep[centre_first[:k]] = True
        tg &= np.repeat(keep, 2)
    return tg


def last_mask(tg: np.ndarray) -> np.ndarray:
    """One target per macro, the one nearest the row-line middle (largest row-line IR with both-end drive), stays HRS."""
    out = np.zeros_like(tg)
    for m in range(RD.N_MACROS):
        idx = np.flatnonzero(tg[m * 64:(m + 1) * 64]) + m * 64
        if idx.size:
            out[idx[np.argmin(np.abs((idx - m * 64) - 31.5))]] = True
    return out


def snap(w: RD.RowWrite, tg: np.ndarray) -> dict:
    """SET: targets go HRS -> LRS; RESET: targets go LRS -> HRS (their partners, already LRS after the SET phase in a real sequence, are held at the row level)."""
    lm = last_mask(tg)
    res = {}
    a, b = (RD.R_HRS, RD.R_LRS) if w.mode == "set" else (RD.R_LRS, RD.R_HRS)
    other = RD.R_HRS if w.mode == "set" else RD.R_LRS
    for name, r in (("before", np.where(tg, a, other)), ("last", np.where(tg & ~lm, b, np.where(tg, a, other))), ("after", np.where(tg, b, other))):
        d = R.dc(w, tg, r)
        sel = lm if name == "last" else tg
        vd = np.abs(d["v_dev"])
        res[name] = dict(v_dev_min=float(vd[sel].min()), v_dev_max=float(vd[sel].max()), i_dev_mean=float(d["i_dev"][tg].mean()),
                         i_dev_max=float(d["i_dev"][tg].max()), i_supply=d["i_supply"], v_rail_droop=d["v_rail_droop"], i_driver_max=d["i_driver_max"],
                         v_driver_drop_max=d["v_driver_drop_max"], row_droop_max=float(w.v_drive - d["v_row"].min()) if w.mode == "set" else float(d["v_row"].max()),
                         vds_max=float(d["v_ds"].max()), vds_max_target=float(d["v_ds"][tg].max()), gate_term_max=float(d["v_gate_term"].max()),
                         nontarget_vdev_max=float(np.abs(d["v_dev"][~tg]).max()) if (~tg).any() else 0.0)
        if name == "last":
            res[name]["v_dev_profile"] = d["v_dev"].tolist()
            res[name]["v_row_profile"] = d["v_row"].tolist()
    return res


def _job(a):
    kind, kw, n_par = a
    w = RD.RowWrite(**kw)
    tg = set_targets(weights(), n_par)
    if w.mode == "reset":
        tg = ~tg if n_par is None else tg
    try:
        return dict(kind=kind, params=kw, n_par=int(tg.sum()), **snap(w, tg))
    except osdi.ToolchainError as e:
        return dict(kind=kind, params=kw, n_par=int(tg.sum()), error=str(e)[-400:])


def jobs() -> list:
    J = []
    for v, row, ori, vwl, mode in itertools.product(V_DRIVE, ROWS, ("bl", "rl"), V_WL, ("set", "reset")):
        J.append(("base", dict(v_drive=float(v), row=row, orientation=ori, v_wl=vwl, mode=mode), None))
    for v, rd, rr in itertools.product((1.2, 1.6, 2.0), R_WDRV, R_RAIL):
        J.append(("drivers_rails", dict(v_drive=v, row=256, r_wdrv=rd, r_rail=rr), None))
        J.append(("drivers_rails", dict(v_drive=v, row=512, r_wdrv=rd, r_rail=rr), None))
    for v, n in itertools.product((1.2, 1.6, 2.0), (1, 5, 10, 20, 40, 80, 120, 160)):
        J.append(("parallel", dict(v_drive=v, row=512), n))
    return J


def delivery(rows: list) -> dict:
    """For each (mode, vth, row, orientation, v_wl): the smallest v_drive at which every target reaches vth both 'before' and 'last' (the target in its starting state
    sees at least vth), and the transistor stress at that point. None = not deliverable at any v_drive <= 2.5 V."""
    out = {}
    for mode, row, ori, vwl in itertools.product(("set", "reset"), ROWS, ("bl", "rl"), V_WL):
        sel = sorted([r for r in rows if r["kind"] == "base" and r["params"]["row"] == row and r["params"]["orientation"] == ori and r["params"]["v_wl"] == vwl
                      and r["params"]["mode"] == mode and "error" not in r], key=lambda r: r["params"]["v_drive"])
        best = max(min(r["before"]["v_dev_min"], r["last"]["v_dev_min"]) for r in sel)
        for vth in V_TH:
            ok = [r for r in sel if min(r["before"]["v_dev_min"], r["last"]["v_dev_min"]) > vth]
            key = f"{mode}|{vth}|{row}|{ori}|{vwl}"
            if ok:
                r = ok[0]
                stress = max(r["after"]["vds_max_target"], r["before"]["vds_max_target"])
                out[key] = dict(v_drive_min=r["params"]["v_drive"], headroom_v=r["params"]["v_drive"] - vth, last_v=r["last"]["v_dev_min"], before_v=r["before"]["v_dev_min"],
                                vds_max=stress, gate_term_max=max(r["after"]["gate_term_max"], r["before"]["gate_term_max"]), within_tx_rating=bool(stress <= TX_RATING_V and vwl <= TX_RATING_V),
                                i_supply_after=r["after"]["i_supply"], i_dev_after_mean=r["after"]["i_dev_mean"], v_rail_droop=r["after"]["v_rail_droop"])
            else:
                out[key] = dict(v_drive_min=None, best_v_dev=best)
    return out


def main() -> None:
    osdi.check_ngspice()
    J = jobs()
    with Pool(24) as p:
        rows = p.map(_job, J, chunksize=2)
    RP.WRITE.mkdir(parents=True, exist_ok=True)
    out = dict(v_drive=list(V_DRIVE), v_th=list(V_TH), rows=rows, delivery=delivery(rows), tx_rating_v=TX_RATING_V,
               note="device = fixed resistor at the 1A read-bias resistance (541.82 / 218586 ohm); thresholds swept in post-processing")
    for r in rows:                     # keep the per-bitline profiles only for the reference case (far row, SET, bitline side, rated word line): they are large
        p = r.get("params", {})
        if not (r["kind"] == "base" and p.get("row") == 512 and p.get("mode") == "set" and p.get("orientation") == "bl" and p.get("v_wl") == 1.1) and "last" in r:
            r["last"].pop("v_dev_profile", None); r["last"].pop("v_row_profile", None)
    (RP.WRITE / "d1_parallel.json").write_text(json.dumps(out, separators=(",", ":")))
    for k, v in out["delivery"].items():
        if "|512|" in k and k.split("|")[1] in ("0.8", "1.2", "1.6", "2.0"):
            print(k, {kk: round(vv, 4) if isinstance(vv, float) else vv for kk, vv in v.items()})
    errs = [r for r in rows if "error" in r]
    print(f"{len(rows)} jobs, {len(errs)} errors")


if __name__ == "__main__":
    main()
