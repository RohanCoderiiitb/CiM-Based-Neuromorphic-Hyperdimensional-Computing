"""Array read energy per INFERENCE from 1E's measured read pattern.

1E issues one group read per (count bit-row b, group G) of every timestep; the number of ACTIVE rows a of each read is the popcount of the 8 count bits of that bit-row in
that group. Phase 0's golden count vectors give exactly that pattern, so the energy of the SNN computation is
    E = sum over (sample, timestep, non-skipped bit-row, group) of E_read(G, a, T) + word-line energy,   E_read(G, 0) = 0 (no row is driven),
with E_read(G, a, T) = N_MACRO * V_read * I_macro(G, a) * (T - tau) + a * N_MACRO * C_WL * V_WL^2.
I_macro(G, a): supply current of one macro on the validated mesh (both-end row drive, supply/ground rails at the 1C baseline r = 0.0072 ohm/pitch fed from both ends), mean of
random weight draws and random active-row subsets. tau: the pulse-start loss (rise and settling) extracted from the ngspice transients (E(T) = V I (T - tau)); the full-array
transient (C3d) confirms array energy = 5 x macro energy to 0.5%. T is the supply-pulse length (set by the sense stage, NOT designed in 1C): a table over T is reported.
Usage: python -m scaleup.energy_inference"""
from __future__ import annotations

import paths as RP

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import device.constants as C
from margin.core import params_for
from scaleup.analyze_c1d import c_wl_macro
from wire.mesh import solve_mesh_ext

T_GRID = (0.25e-9, 0.5e-9, 1e-9, 2e-9, 5e-9, 10e-9)
N_DRAW = 6


def _imacro(args):
    G, a = args
    p = params_for(C.AREA_1C, C.RS_1C)
    rng = np.random.default_rng([C.WIRE_SEED, 777, G, a])
    out = []
    for _ in range(N_DRAW):
        rows = np.sort(8 * G + rng.choice(8, a, replace=False))
        W = rng.random((a, C.CELLS_PER_MACRO_ROW)) < 0.5
        gaps = np.where(np.repeat(W, 2, axis=1) ^ (np.arange(C.MACRO_BITLINES)[None, :] % 2 == 1), p.gap_lrs, p.gap_hrs)
        m = solve_mesh_ext(gaps, rows + 1.0, p, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=C.RS_1C, drive_both_ends=True, r_rail=C.RAIL_R_DEFAULT, rail_length=C.ROWS_TOTAL + 1.0, r_gnd=C.RAIL_R_DEFAULT)
        out.append(float(m.i_row.sum()))
    return G, a, float(np.mean(out))


def tau_pulse() -> float:
    """Pulse-start loss tau in E(T) = V I (T - tau), from the single-macro transients (T = 1 ns, ideal supply)."""
    res = json.loads((RP.TRANSIENT / "group_read_energy_latency_macro.json").read_text())
    taus = [1e-9 - r["energy_J"]["1e-09"] / (C.V_READ * r["i_sup_final_A"]) for r in res]
    return float(np.mean(taus))


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "03_rtl" / "tb" / "common"))
    import golden as GD                                               # Phase 0 / 1E golden count vectors (read only)
    with ProcessPoolExecutor(9) as ex:
        tab = {(G, a): i for G, a, i in ex.map(_imacro, [(G, a) for G in range(64) for a in range(1, 9)], chunksize=8)}
    I = np.zeros((64, 9)); 
    for (G, a), i in tab.items():
        I[G, a] = i
    tau = tau_pulse()
    man, c, s, W = GD.load_dataset("dvsgesture", 0)
    counts = c["counts"].astype(np.int64)                           # (240, 100, 512)
    n_s, T_ts, _ = counts.shape
    # a[G, b] per (sample, timestep): popcount of bit b over the 8 addresses of group G
    bits = ((counts[..., None] >> np.arange(11)) & 1).astype(np.uint8)  # (240,100,512,11)
    A = bits.reshape(n_s, T_ts, 64, 8, 11).sum(axis=3, dtype=np.int16)  # (240,100,64,11)  active rows per (group, bit-row)
    row_nz = (A.sum(axis=2) > 0)                                       # bit-row not all zero -> read (plane skipping)
    reads_issued = row_nz.sum(axis=(1, 2)) * 64
    nonzero_reads = (A > 0).sum(axis=(1, 2, 3)); active_rows = A.sum(axis=(1, 2, 3))
    iA = np.zeros(A.shape, float)
    for a in range(1, 9):
        iA += np.where(A == a, I[None, None, :, a, None], 0.0)
    cwl = c_wl_macro()
    out = dict(tau_s=tau, reads_issued_per_inference=float(reads_issued.mean()), nonzero_reads_per_inference=float(nonzero_reads.mean()), zero_read_fraction=float(1 - nonzero_reads.mean() / reads_issued.mean()),
               active_row_reads_per_inference=float(active_rows.mean()), mean_active_rows_per_nonzero_read=float(active_rows.mean() / nonzero_reads.mean()),
               n_macros=C.N_MACROS, e_wl_per_active_row_array_J=C.N_MACROS * cwl * C.V_WL ** 2, energy_per_inference_J={}, mean_array_power_during_read_W=float((iA.sum(axis=(1, 2, 3)) * C.N_MACROS * C.V_READ).mean() / max(nonzero_reads.mean(), 1)))
    for T in T_GRID:
        e_arr = C.N_MACROS * C.V_READ * iA.sum(axis=(1, 2, 3)) * (T - tau)                 # sum over reads of 5 macros' static+dynamic read energy
        e_wl = active_rows * C.N_MACROS * cwl * C.V_WL ** 2
        out["energy_per_inference_J"][str(T)] = dict(array_J=float(e_arr.mean()), wordline_J=float(e_wl.mean()), total_J=float((e_arr + e_wl).mean()), per_nonzero_read_pJ=float((e_arr + e_wl).mean() / nonzero_reads.mean() * 1e12),
                                                      per_issued_read_pJ=float((e_arr + e_wl).mean() / reads_issued.mean() * 1e12))
    I8 = I[:, 8]
    out["i_macro_a8_near_far_A"] = [float(I8[0]), float(I8[-1])]; out["i_macro_table_A"] = I.tolist()
    (RP.FULL_ARRAY / "energy_per_inference.json").write_text(json.dumps(out, indent=1))
    print({k: v for k, v in out.items() if k not in ("energy_per_inference_J", "i_macro_table_A")})
    for T, d in out["energy_per_inference_J"].items():
        print(f"T={float(T)*1e9:.2f} ns: array {d['array_J']*1e9:.1f} nJ + WL {d['wordline_J']*1e9:.1f} nJ = {d['total_J']*1e9:.1f} nJ per inference ({d['per_issued_read_pJ']:.3f} pJ per issued read, {d['per_nonzero_read_pJ']:.3f} pJ per non-zero read)")


if __name__ == "__main__":
    main()
