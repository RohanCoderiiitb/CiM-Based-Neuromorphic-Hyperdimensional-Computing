"""Per-column calibration of the differential front-end (b) and what is left after it.

The mismatch Monte-Carlo (sense.mc) shows that the whole static error of a column is captured by two numbers PER CHANNEL: the copy gain g (errors proportional to the current) and the input-referred offset
voltage V of the regulating amplifier (error V x G_array(state), because the sense node is held V away from V_VG). Model of one channel:   I(G, m) = g I_nom(G, m) + V G_array(G, m).
A calibration measurement with known cells (both groups, m = 0..8) gives the two numbers (least squares), they are quantised to the trim resolution and used to correct the column. Because I_nom is nearly
0.1 V x G_array (the two regressors differ only by the ~3-7% group-to-group variation of the front-end gain), V is expressed on the component of G_array orthogonal to I_nom (well conditioned); g is the
effective gain. What is left (the "calibration residual") has three parts, each measured here:
  model residual   : what the 2-parameter model does not capture                                         [SIM]
  trim quantisation: parameters rounded to the trim LSB (range +/- 4 sigma, uniform steps)               [CHOICE of bits, SIM of the effect]
  temperature      : parameters fixed at the calibration temperature, the column read at another         [SIM]
Usage: python -m sense.cal"""
from __future__ import annotations

import json
from multiprocessing import Pool

import numpy as np

import device.constants as C
import paths as RP
from sense import mc, port as P


DESIGN = dict(vs=0.45, wp=16e-6, lp=360e-9, vb=0.46, k=4.0, w1=15e-6, wi1=8e-6)
POINTS = [(pos, m) for pos in (P.FAR_POS0, P.NEAR_POS0) for m in range(9)]
TEMPS = (27.0, 47.0, 67.0, 87.0)


def _job(a):
    dz, m, pos, dv, temp = a
    return mc.i_channels(dz, m, pos, dv, temp=temp)


def _gcond():
    gp = np.array([1 / (1 / P.branch_g(m, 8 - m) + P.wire_r(pos)) for pos, m in POINTS])
    gn = np.array([1 / (1 / P.branch_g(8 - m, m) + P.wire_r(pos)) for pos, m in POINTS])
    return gp, gn


def basis(nom: np.ndarray, ch: int, orth: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Regressors of channel ch: r1 = nominal current, r2 = array conductance (orthogonalised against r1 when orth)."""
    g = _gcond()[ch]
    r1 = nom[:, ch]
    return r1, (g - (g @ r1) / (r1 @ r1) * r1) if orth else g


def fit(meas: np.ndarray, nom: np.ndarray, two: bool = True) -> np.ndarray:
    """(2 x 2) array [channel][kappa, delta] (delta = 0 when two is False)."""
    out = np.zeros((2, 2))
    for ch in (0, 1):
        r1, r2 = basis(nom, ch)
        A = np.stack([r1, r2], 1) if two else r1[:, None]
        c, *_ = np.linalg.lstsq(A, meas[:, ch], rcond=None)
        out[ch, :len(c)] = c
    return out


def to_physical(par: np.ndarray, nom0: np.ndarray) -> np.ndarray:
    """(kappa_orth, delta) -> (kappa, V): I = kappa I_nom + V G_array (the regressors the circuit really has)."""
    out = par.copy()
    for ch in (0, 1):
        r1, r2 = basis(nom0, ch)
        a = (_gcond()[ch] @ r1) / (r1 @ r1)
        out[ch, 0] = par[ch, 0] - par[ch, 1] * a
    return out


def residual(meas: np.ndarray, nom: np.ndarray, par: np.ndarray) -> np.ndarray:
    """Differential current error left after the correction with PHYSICAL parameters (kappa, V) at the temperature of `nom`, per point (A): (measured p - model p) - (measured n - model n)."""
    r = []
    for ch in (0, 1):
        r.append(meas[:, ch] - (par[ch, 0] * nom[:, ch] + par[ch, 1] * _gcond()[ch]))
    return r[0] - r[1]


def _tjob(a):
    dz, m, pos, dv, T, tail = a
    return mc.charges(dz, m, pos, dv, T, t_tail=tail)


def run_transient(T: float = 1e-9, n: int = 40, seed: int = 12, tail: float = 0.3e-9, design: dict | None = None) -> dict:
    """The same calibration analysis on TRANSIENT charges (the calibration measurement uses the real read pulse of length T, integrated to T + tail): quantity = charge / T in uA-equivalents."""
    des = dict(DESIGN); des.update(design or {})
    dz = mc.Design(**des)
    rng = np.random.default_rng(seed)
    draws = [mc.draw(dz, rng) for _ in range(n)]
    with Pool(10) as pool:
        nom = np.array(pool.map(_tjob, [(dz, m, pos, None, T, tail) for pos, m in POINTS])) / T
        meas = np.array([pool.map(_tjob, [(dz, m, pos, d, T, tail) for pos, m in POINTS]) for d in draws]) / T
    raw = np.array([(meas[i][:, 0] - meas[i][:, 1]) - (nom[:, 0] - nom[:, 1]) for i in range(n)])
    p2 = np.array([fit(meas[i], nom) for i in range(n)]); p1 = np.array([fit(meas[i], nom, two=False) for i in range(n)])
    res2 = np.array([residual(meas[i], nom, to_physical(p2[i], nom)) for i in range(n)])
    res1 = np.array([residual(meas[i], nom, to_physical(p1[i], nom)) for i in range(n)])
    return dict(T=T, tail=tail, design=des, n=n, raw_rms_uA=float(np.sqrt(np.mean(raw ** 2)) * 1e6), gain_only=dict(rms_uA=float(np.sqrt(np.mean(res1 ** 2)) * 1e6), sigma_worst_point_uA=float(res1.std(0).max() * 1e6)),
                gain_and_offset=dict(rms_uA=float(np.sqrt(np.mean(res2 ** 2)) * 1e6), sigma_worst_point_uA=float(res2.std(0).max() * 1e6), max_abs_uA=float(abs(res2).max() * 1e6),
                                     sigma_by_point_uA=(res2.std(0) * 1e6).tolist()), kappa_sigma=float(p2[:, :, 0].std()))


def run(n: int = 100, seed: int = 11) -> dict:
    dz = mc.Design(**DESIGN)
    rng = np.random.default_rng(seed)
    draws = [mc.draw(dz, rng) for _ in range(n)]
    with Pool(10) as pool:
        nom = {T: np.array(pool.map(_job, [(dz, m, pos, None, T) for pos, m in POINTS])) for T in TEMPS}
        meas = {T: np.array([pool.map(_job, [(dz, m, pos, d, T) for pos, m in POINTS]) for d in draws]) for T in TEMPS}
    T0 = TEMPS[0]
    out = dict(design=DESIGN, n=n, points=POINTS, temps=list(TEMPS), avt_mv_um=C.AVT_MV_UM)
    raw = np.array([(meas[T0][i][:, 0] - meas[T0][i][:, 1]) - (nom[T0][:, 0] - nom[T0][:, 1]) for i in range(n)])
    out["raw"] = dict(rms_uA=float(np.sqrt(np.mean(raw ** 2)) * 1e6), sigma_by_point_uA=(raw.std(0) * 1e6).tolist())
    p2 = np.array([fit(meas[T0][i], nom[T0]) for i in range(n)])
    p1 = np.array([fit(meas[T0][i], nom[T0], two=False) for i in range(n)])
    out["kappa_mean"] = float(p2[:, :, 0].mean()); out["kappa_sigma"] = float(p2[:, :, 0].std())
    sk, sd = p2[:, :, 0].std(), p2[:, :, 1].std()

    def stats(par_all, T):
        res = np.array([residual(meas[T][i], nom[T], to_physical(par_all[i], nom[T0])) for i in range(n)])
        return dict(rms_uA=float(np.sqrt(np.mean(res ** 2)) * 1e6), sigma_worst_point_uA=float(res.std(0).max() * 1e6), max_abs_uA=float(abs(res).max() * 1e6), sigma_by_point_uA=(res.std(0) * 1e6).tolist())

    out["gain_only"] = {f"{T:g}": stats(p1, T) for T in TEMPS}
    out["gain_and_offset"] = {f"{T:g}": stats(p2, T) for T in TEMPS}
    out["quantised"] = {}
    for bits in (6, 7, 8, 9, 10, 12):
        lk, ld = 8 * sk / 2 ** bits, 8 * sd / 2 ** bits
        q = p2.copy(); q[:, :, 0] = np.round(q[:, :, 0] / lk) * lk; q[:, :, 1] = np.round(q[:, :, 1] / ld) * ld
        out["quantised"][str(bits)] = dict(lsb_kappa_percent=100 * lk, at_27C=stats(q, T0))
    return out


def main() -> None:
    o = run()
    o["transient"] = {f"{T*1e9:g}": run_transient(T) for T in (0.5e-9, 1e-9, 2e-9)}
    for k, v in o["transient"].items():
        print("transient T", k, "ns: raw", round(v["raw_rms_uA"], 2), "gain-only", {a: round(b, 3) for a, b in v["gain_only"].items()}, "gain+offset", {a: round(b, 3) for a, b in v["gain_and_offset"].items() if a != "sigma_by_point_uA"})
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "calibration_mc.json").write_text(json.dumps(o, indent=1))
    print("raw rms uA", o["raw"]["rms_uA"], "kappa mean/sigma", o["kappa_mean"], o["kappa_sigma"])
    for k in ("gain_only", "gain_and_offset"):
        print(k, {T: (round(v["rms_uA"], 3), round(v["sigma_worst_point_uA"], 3), round(v["max_abs_uA"], 2)) for T, v in o[k].items()})
    for b, v in o["quantised"].items():
        print(b, "bits: lsb kappa %.3f %%" % v["lsb_kappa_percent"], round(v["at_27C"]["sigma_worst_point_uA"], 3))


if __name__ == "__main__":
    main()
