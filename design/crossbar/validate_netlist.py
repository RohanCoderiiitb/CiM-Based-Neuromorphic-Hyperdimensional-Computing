#!/usr/bin/env python3
"""Validate the generated crossbar netlist against the mesh solver (wire.mesh.solve_mesh_ext), which is the reference.

  A  the 1C suite: the same 300 random small arrays (odd block widths, rails, ground pads, spread) 1C used to validate the solver, now simulated from the GENERATED
     hierarchical netlist (wire/validate_mesh_ext.py calls the generator). Compared with 1C's recorded worst disagreement.
  B  the real geometry: a 512-row x 32-cell macro (64 bitlines), g = 8, rails/drivers at the 1C design values, 'sinh' devices: group position x active-row count x random
     weight pattern (log-normal spread, sigma_lnG = 0.10). Column currents, row-supply currents, rail and ground-rail voltages.
  C  the 5-macro array (512 x 160 cells), a few reads.
  D  the 'resistor' device flavour (fixed resistors at the read bias) against the same solver run with a LINEAR device (v0 -> 1e6, gap' = g0 ln R): the netlist is exact for
     what it models. And what the fixed-resistor approximation costs against the nonlinear device law (informational, not a netlist error).
  E  the reduced (active-rows-only, lumped) transient view against the full hierarchy: DC exactness, and the cost of the pi-lump (lump = 16 vs per-pitch).
  F  the access transistor as the PTM 45 nm BSIM4 card (tx = 'bsim') against the linear R_tx, informational (1A bounds this: 0.07 %).

Run from anywhere:  venv/bin/python design/crossbar/validate_netlist.py [--quick]      -> design/crossbar/results/netlist_validation.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crossbar_netlist import ArraySpec, TranSpec, full_deck, reduced_deck, run_full_op, weights_to_gaps  # noqa: E402
import device.constants as C  # noqa: E402
from device.constants import DEFAULT  # noqa: E402
from wire.mesh import solve_mesh_ext  # noqa: E402

OUT = Path(__file__).resolve().parent / "results" / "netlist_validation.json"
SIGMA = 0.10                       # sigma_lnG of the random weight patterns (the 1C default)


def spread_gaps(rng, rows: int, K: int, p=DEFAULT) -> np.ndarray:
    w = rng.integers(0, 2, (rows, K // 2)).astype(bool)
    return weights_to_gaps(w, p) - p.g0 * SIGMA * rng.standard_normal((rows, K))


def solver(spec: ArraySpec, gaps, act, lin: bool = False):
    """The reference. act = active physical rows (sorted)."""
    p = spec.p
    g = np.asarray(gaps)[act]
    if lin:                                                      # linear device: I = V / R exactly (sinh with v0 -> 1e6 is linear to 1e-15)
        R = spec.gap_to_state(gaps)[act] if spec.device == "resistor" else None
        p = p.with_(i0=1e6, v0=1e6, gmin=0.0)
        g = p.g0 * np.log(R)
    return solve_mesh_ext(g, act + 1.0, p, r_bl=spec.r_bl, r_wl=spec.r_wl, r_drv=spec.r_drv, r_s=spec.rs, blocks=spec.blocks, r_rail=spec.r_rail, rail_pos=spec.rail_pos_arr[act],
                          rail_length=spec.rail_len, r_gnd=spec.r_gnd, gnd_pad_pitches=spec.gnd_pad_pitches, gnd_pad_per_block=spec.gnd_pad_per_block,
                          drive_both_ends=spec.drive_both_ends, r_tx=p.r_tx)


def compare(spec: ArraySpec, gaps, act, lin: bool = False) -> dict:
    t0 = time.time()
    ng = run_full_op(spec, gaps, act)
    t_ng = time.time() - t0
    m = solver(spec, gaps, act, lin)
    return dict(rel_icol=float(np.max(np.abs(ng["i_col"] / m.i_col - 1))), abs_icol_a=float(np.max(np.abs(ng["i_col"] - m.i_col))), rel_irow=float(np.max(np.abs(ng["i_row"] / m.i_row - 1))),
                abs_vrail_v=float(np.max(np.abs(ng["v_rail"] - m.v_rail))) if spec.r_rail is not None else 0.0,
                abs_vgnd_v=float(np.max(np.abs(ng["v_gnd"] - m.v_gnd))) if spec.r_gnd is not None else 0.0, ngspice_s=round(t_ng, 2), i_col_min_a=float(np.min(m.i_col)))


# ---------------------------------------------------------------------------------------------------------------- A
def part_a(n: int) -> dict:
    import wire.validate_mesh_ext as V
    rng = np.random.default_rng(1331)
    rows = [V.one_case(c, rng) for c in range(n)]
    ref = json.loads((Path(C.__file__).resolve().parents[1] / "results" / "array_validation" / "mesh_ext_validation_summary.json").read_text())
    worst = max(rows, key=lambda r: r["rel_icol"])
    return dict(n=len(rows), worst_rel_icol=max(r["rel_icol"] for r in rows), worst_rel_irow=max(r["rel_irow"] for r in rows), worst_abs_vrail_v=max(r["abs_vrail_v"] for r in rows),
                worst_abs_vgnd_v=max(r["abs_vgnd_v"] for r in rows), recorded_1c=ref, worst_case=dict(case=worst["case"], blocks=worst["blocks"], n_active=worst["n_active"], rail=worst["rail"], gnd=worst["gnd"]),
                n_over_1c_worst=int(sum(r["rel_icol"] > ref["worst_rel_icol"] for r in rows)))


# ---------------------------------------------------------------------------------------------------------------- B, C, D
def _job_macro(args):
    rows, g, G, a, seed, device, lin, scatter = args
    spec = ArraySpec(rows=rows, blocks=(C.MACRO_BITLINES,), g=g, device=device)
    rng = np.random.default_rng([C.WIRE_SEED, rows, g, G, a, seed])
    gaps = spread_gaps(rng, rows, spec.K)
    act = np.sort(rng.choice(rows, a, replace=False)) if scatter else np.sort(G * g + rng.choice(min(g, rows - G * g), a, replace=False))
    r = compare(spec, gaps, act, lin)
    r.update(rows=rows, g=g, group=G, n_active=a, seed=seed, scatter=scatter, device=device)
    if device == "resistor" and not lin:
        pass
    return r


def part_b(rows: int, quick: bool) -> dict:
    groups = [0, 1, rows // 16 - 1, rows // 8 - 1] if quick else [0, 1, 2, rows // 16 - 1, rows // 8 - 2, rows // 8 - 1]
    jobs = [(rows, 8, G, a, s, "sinh", False, False) for G in groups for a in (1, 2, 4, 8) for s in range(1 if quick else 2)]
    jobs += [(rows, 8, 0, a, 90 + s, "sinh", False, True) for a in (8, 16) for s in range(2)]       # scattered rows over the whole macro
    with ProcessPoolExecutor(3) as ex:
        res = list(ex.map(_job_macro, jobs))
    return dict(rows=rows, n=len(res), worst_rel_icol=max(r["rel_icol"] for r in res), worst_abs_icol_a=max(r["abs_icol_a"] for r in res), worst_rel_irow=max(r["rel_irow"] for r in res),
                worst_abs_vrail_v=max(r["abs_vrail_v"] for r in res), worst_abs_vgnd_v=max(r["abs_vgnd_v"] for r in res), max_ngspice_s=max(r["ngspice_s"] for r in res), cases=res)


def _job_array(args):
    rows, G, a, seed = args
    spec = ArraySpec(rows=rows)
    rng = np.random.default_rng([C.WIRE_SEED, rows, 5, G, a, seed])
    gaps = spread_gaps(rng, rows, spec.K)
    act = np.sort(G * 8 + rng.choice(8, a, replace=False))
    r = compare(spec, gaps, act)
    r.update(rows=rows, group=G, n_active=a, seed=seed, macros=len(spec.blocks))
    return r


def part_c(rows: int, quick: bool) -> dict:
    jobs = [(rows, rows // 8 - 1, 8, 0), (rows, rows // 16, 4, 1)] + ([] if quick else [(rows, 0, 8, 2)])
    with ProcessPoolExecutor(3) as ex:
        res = list(ex.map(_job_array, jobs))
    return dict(rows=rows, n=len(res), worst_rel_icol=max(r["rel_icol"] for r in res), worst_rel_irow=max(r["rel_irow"] for r in res), worst_abs_vrail_v=max(r["abs_vrail_v"] for r in res),
                worst_abs_vgnd_v=max(r["abs_vgnd_v"] for r in res), max_ngspice_s=max(r["ngspice_s"] for r in res), cases=res)


def part_d(rows: int) -> dict:
    out, deltas = [], []
    for G, a, s in ((0, 8, 0), (rows // 16, 4, 1), (rows // 8 - 1, 8, 2), (3, 1, 3)):
        spec = ArraySpec(rows=rows, blocks=(C.MACRO_BITLINES,), device="resistor")
        rng = np.random.default_rng([C.WIRE_SEED, rows, 77, G, a, s])
        gaps = spread_gaps(rng, rows, spec.K)
        act = np.sort(G * 8 + rng.choice(8, a, replace=False))
        r = compare(spec, gaps, act, lin=True)                                      # netlist vs the solver with a linear device: exact
        nl = solver(spec.with_(device="sinh"), gaps, act)                           # the nonlinear device law
        ng = run_full_op(spec, gaps, act)
        r["fixed_resistor_vs_sinh_rel_icol_worst"] = float(np.max(np.abs(ng["i_col"] / nl.i_col - 1)))
        r["fixed_resistor_vs_sinh_rel_icol_median"] = float(np.median(np.abs(ng["i_col"] / nl.i_col - 1)))
        r["fixed_resistor_vs_sinh_diff_current_worst"] = float(np.max(np.abs((ng["i_col"][0::2] - ng["i_col"][1::2]) - (nl.i_col[0::2] - nl.i_col[1::2])) / np.abs(nl.i_col[0::2] - nl.i_col[1::2]).max()))
        r.update(group=G, n_active=a)
        out.append(r)
    return dict(n=len(out), worst_rel_icol_vs_linear_solver=max(r["rel_icol"] for r in out), worst_rel_irow=max(r["rel_irow"] for r in out), worst_fixed_resistor_vs_sinh=max(r["fixed_resistor_vs_sinh_rel_icol_worst"] for r in out),
                median_fixed_resistor_vs_sinh=float(np.median([r["fixed_resistor_vs_sinh_rel_icol_median"] for r in out])), cases=out)


# ---------------------------------------------------------------------------------------------------------------- E
def _tran_full(spec, gaps, active, t_stop, t_step=1e-12):
    import subprocess
    import tempfile
    deck, probes = full_deck(spec, gaps, active, analysis="tran", tran_stop=t_stop, tran_step=t_step, sources=f"Vsup sup 0 PWL(0 0 {C.T_RISE_S:.6g} {spec.p.v_read:.17g})")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "t.dat"
        (Path(td) / "d.cir").write_text(deck.replace("TRANOUT", str(out)))
        subprocess.run(["ngspice", "-b", str(Path(td) / "d.cir")], capture_output=True, text=True, timeout=3600)
        txt = out.read_text().splitlines()
    names = [h.lower() for h in txt[0].split()]
    data = np.array([[float(x) for x in ln.split()] for ln in txt[1:] if ln.strip()])
    col = {n: data[:, i] for i, n in enumerate(names)}
    return dict(t=data[:, 0], i_sup=-col["i(vsup)"], v_s=np.stack([col[f"v(s{j})"] for j in range(spec.K)], 1))


def part_e(quick: bool) -> dict:
    from scaleup.transient import TranConfig, build_tran_deck, currents, run_tran
    rows, K = 64, 16
    rng = np.random.default_rng(2024)
    res = {}
    for name, lump in (("lump1", 1), ("lump16", 16)):
        gaps = spread_gaps(rng if False else np.random.default_rng(5), rows, K)
        act = 8 * 3 + np.arange(8)
        spec = ArraySpec(rows=rows, blocks=(K,), r_rail=None, r_gnd=None, rail_feed_both_ends=False, r_s=C.RS_1C, drive_both_ends=True, caps=True, c_dec=0.0)
        full = _tran_full(spec, gaps, act, 0.6e-9)
        cfg = TranConfig(t_stop=0.6e-9, lump=lump, bl_len=rows)
        red = run_tran(build_tran_deck(gaps[act], act + 1.0, DEFAULT.with_(r_tx=spec.p.r_tx), cfg, C.RS_1C, blocks=(K,)), K)
        tt = np.linspace(0.05e-9, 0.6e-9, 56)
        i_f = np.stack([np.interp(tt, full["t"], full["v_s"][:, j]) for j in range(K)], 1)
        i_r = np.stack([np.interp(tt, red["t"], red["v_s"][:, j]) for j in range(K)], 1)
        scale = np.abs(i_f[-1]).max()
        res[name] = dict(worst_dv_over_final_max=float(np.max(np.abs(i_f - i_r)) / scale), dc_final_rel=float(np.max(np.abs(i_f[-1] / i_r[-1] - 1))),
                         i_sup_final_rel=float(abs(full["i_sup"][-1] / red["i_sup"][-1] - 1)))
    return res


# ---------------------------------------------------------------------------------------------------------------- F
def part_f() -> dict:
    rows = 16
    rng = np.random.default_rng(11)
    gaps = spread_gaps(rng, rows, 8)
    act = np.arange(8, 16)
    base = ArraySpec(rows=rows, blocks=(8,), g=8, r_rail=None, r_gnd=None, rail_feed_both_ends=False, r_s=C.RS_1C)
    a = run_full_op(base, gaps, act)["i_col"]
    b = run_full_op(base.with_(tx="bsim"), gaps, act)["i_col"]
    return dict(worst_rel_icol_bsim_vs_linear=float(np.max(np.abs(b / a - 1))), median=float(np.median(np.abs(b / a - 1))), note="PTM 45 nm LP BSIM4 NMOS in the cell vs the linear R_tx at the read bias (1A: 0.07 % on one branch)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="fewer cases (smoke test)")
    ap.add_argument("--rows", type=int, default=C.ROWS_TOTAL)
    ap.add_argument("--skip", nargs="*", default=[])
    a = ap.parse_args()
    res = {}
    t0 = time.time()
    for name, fn in (("A_1c_suite", lambda: part_a(60 if a.quick else 300)), ("B_macro", lambda: part_b(a.rows, a.quick)), ("C_array", lambda: part_c(a.rows, a.quick)),
                     ("D_resistor_flavour", lambda: part_d(a.rows)), ("E_reduced_view", lambda: part_e(a.quick)), ("F_bsim", part_f)):
        if name.split("_")[0] in a.skip:
            continue
        res[name] = fn()
        print(f"[{name}] done in {time.time() - t0:.0f}s: " + json.dumps({k: v for k, v in res[name].items() if k not in ("cases", "recorded_1c")}, default=str)[:600], flush=True)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
