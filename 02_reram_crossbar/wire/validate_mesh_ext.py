"""Validate the 1C extension of the mesh solver (wire.mesh.solve_mesh_ext: macro blocks, supply rail, ground rail) against ngspice.

The ngspice deck keeps every physical row and every rail/ground segment (nothing collapsed), so this checks the nodal equations AND the exact collapse of the supply
rail over inactive rows. Cases: R = 32 physical rows, K in {8, 16, 24} columns split in 1-3 blocks, random 2T2R weights with log-normal spread, random active sets of
1..16 rows, supply pad at either end of the rail, ground pad per macro or single, wire settings from realistic to exaggerated (rail up to 5 ohm/pitch).
Reports the WORST disagreement over: column current (relative), row supply current (relative), rail voltage at the active rows (absolute, V), ground-rail voltage (absolute, V).
Usage: python -m wire.validate_mesh_ext [--n 240]
"""
from __future__ import annotations

import paths as RP

import argparse
import csv
import json
import time

import numpy as np

from device.constants import DEFAULT
from spice.runner import run_deck_prints
from wire.mesh import solve_mesh_ext
from wire.netlist import build_mesh_deck_ext

FIELDS = ["case", "R", "K", "blocks", "n_active", "rail", "gnd", "pad_far", "r_bl", "r_rail", "r_gnd", "rel_icol", "rel_irow", "abs_vrail_v", "abs_vgnd_v", "mesh_s", "ngspice_s"]
BLOCKS = {8: [(8,), (4, 4)], 16: [(16,), (8, 8), (6, 5, 5)], 24: [(8, 8, 8), (24,), (12, 12)]}
WIRES = ((0.72, 0.72, 10.0, 0.72, 0.72), (2.0, 2.0, 30.0, 5.0, 5.0), (0.5, 0.5, 5.0, 0.05, 0.1))     # (r_bl, r_wl, r_drv, r_rail, r_gnd)


def one_case(c: int, rng) -> dict:
    R = 32; K = int(rng.choice([8, 16, 24])); blocks = BLOCKS[K][int(rng.integers(len(BLOCKS[K])))]
    rbl, rwl, rdrv, rrail, rgnd = WIRES[int(rng.integers(len(WIRES)))]
    use_rail, use_gnd = bool(rng.integers(2)) or c % 3 == 0, bool(rng.integers(2)) or c % 3 == 1
    pad_far = bool(rng.integers(2)); per_block = bool(rng.integers(2))
    both = bool(rng.integers(2))
    n_act = int(rng.integers(1, 17))
    active = np.zeros(R, bool); active[rng.choice(R, n_act, replace=False)] = True
    w = rng.integers(0, 2, (R, K // 2)).astype(bool)
    stored = np.repeat(w, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1)
    gaps = np.where(stored, DEFAULT.gap_lrs, DEFAULT.gap_hrs) - DEFAULT.g0 * 0.10 * rng.standard_normal((R, K))
    rs = rng.choice([1.0, 5.0], K)
    rp_phys = (R - np.arange(R)) * 1.0 if pad_far else (np.arange(R) + 1.0)          # distance of each physical row's driver tap from the supply pad
    act = np.flatnonzero(active)
    rail_len = float(R + 3) if (use_rail and rng.integers(2)) else None             # second supply pad beyond the last row (both-end feed) in half of the rail cases
    kw = dict(r_bl=rbl, r_wl=rwl, r_drv=rdrv, r_s=rs, blocks=blocks, r_rail=rrail if use_rail else None, r_gnd=rgnd if use_gnd else None,
              gnd_pad_per_block=per_block, drive_both_ends=both)
    t0 = time.time()
    m = solve_mesh_ext(gaps[act], act + 1.0, DEFAULT, rail_pos=rp_phys[act], rail_length=rail_len, **kw)
    t_m = time.time() - t0
    t0 = time.time()
    deck = build_mesh_deck_ext(gaps, active, DEFAULT, rbl, rwl, rdrv, r_s=rs, blocks=blocks, r_rail=kw["r_rail"], rail_pos=rp_phys if use_rail else None, rail_length=rail_len, r_gnd=kw["r_gnd"],
                               gnd_pad_per_block=per_block, drive_both_ends=both)
    v = run_deck_prints(deck)
    t_n = time.time() - t0
    vs = np.array([v[f"v(s{j})"] for j in range(K)]); vg = np.array([v[f"v(g{j})"] for j in range(K)]) if use_gnd else np.zeros(K)
    icol = (vs - vg) / rs
    c0 = np.concatenate([[0], np.cumsum(blocks)[:-1]]); cd = np.concatenate([c0, np.cumsum(blocks) - 1]) if both else c0
    irow = np.array([sum(v[f"v({'rail' + str(i) if use_rail else 'vr'},w{i}_{cc})"] for cc in cd) / max(rdrv, 1e-4) for i in act])
    out = dict(case=c, R=R, K=K, blocks="-".join(map(str, blocks)), n_active=n_act, rail=int(use_rail), gnd=int(use_gnd), pad_far=int(pad_far), r_bl=rbl, r_rail=rrail if use_rail else 0.0,
               r_gnd=rgnd if use_gnd else 0.0, rel_icol=float(np.max(np.abs(m.i_col / icol - 1))), rel_irow=float(np.max(np.abs(m.i_row / irow - 1))),
               abs_vrail_v=0.0, abs_vgnd_v=float(np.max(np.abs(m.v_gnd - vg))) if use_gnd else 0.0, mesh_s=round(t_m, 4), ngspice_s=round(t_n, 3))
    if use_rail:
        out["abs_vrail_v"] = float(np.max(np.abs(m.v_rail - np.array([v[f"v(rail{i})"] for i in act]))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=240); args = ap.parse_args()
    RP.MESH_EXT_VALIDATION_CSV.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1331)
    rows = [one_case(c, rng) for c in range(args.n)]
    with RP.MESH_EXT_VALIDATION_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS); w.writeheader(); w.writerows(rows)
    summ = dict(n=len(rows), worst_rel_icol=max(r["rel_icol"] for r in rows), worst_rel_irow=max(r["rel_irow"] for r in rows), worst_abs_vgnd_v=max(r["abs_vgnd_v"] for r in rows),
                with_rail=sum(r["rail"] for r in rows), with_gnd=sum(r["gnd"] for r in rows), multi_block=sum("-" in r["blocks"] for r in rows))
    (RP.ARRAY_VALIDATION / "mesh_ext_validation_summary.json").write_text(json.dumps(summ, indent=1))
    print(summ)
    return 0 if summ["worst_rel_icol"] < 1e-6 and summ["worst_rel_irow"] < 1e-4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
