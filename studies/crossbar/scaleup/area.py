"""C3(c): total area of the 512 x 160 array with periphery, and what drives it. Every number is tagged: [MODEL] computed from measured/derived quantities, [SIM] from ngspice,
[ASSUM] a layout/circuit density assumption (no layout exists; each is swept low/mid/high so the ranking of the contributors is not an artefact of one value).

Contributors
  cell array     : 512 x 160 cells x 40 F^2 (2T2R) at F = 45 nm                                            [MODEL]
  row drivers    : two per row per macro (both-end drive, 1C baseline). R_DRV sets the width: W = (R_tx * W)/R_DRV with R_tx * W = 548.7 ohm*um (1A, 20 F^2 cell) [SIM]; layout density
                   um^2 per um of width                                                                  [ASSUM]
  word-line bufs : one per row per macro                                                                    [ASSUM]
  row decoder    : per row                                                                                 [ASSUM]
  sense front-end: per column a current-mode input stage (differential I+ - I-, virtual ground) and g comparators (flash, one per ladder threshold)       [ASSUM]
  reference DACs : one per ladder threshold, shared by all columns                                          [ASSUM]
  ladder storage : thresholds (C1 table) + row-gain correction vectors (rank 2), SRAM bit area incl. periphery [bits MODEL/derived, density ASSUM]
  rails          : supply/ground straps: width = R_sheet * pitch / (ohm per pitch)                         [MODEL; R_sheet ASSUM, thick top metal]
  decoupling     : Q / dV with Q = I_array * T_pulse; only needed if the read supply is not ideal at the rail pads (it was ideal in 1C); reported separately.
Usage: python -m scaleup.area
"""
from __future__ import annotations

import paths as RP

import json
from itertools import product

import device.constants as C

F_UM = C.FEATURE_NM * 1e-3
CELL_UM2 = C.AREA_1C * 2 * F_UM ** 2                         # 2T2R = 2 x 20 F^2
RTX_W_OHM_UM = C.RTX_BY_AREA[C.AREA_1C] * (C.TX_FILL * C.AREA_1C * F_UM)      # [SIM] 1016.05 ohm x 0.54 um
LEVELS = {                                                   # (low, mid, high) [ASSUM] ranges
    "driver_um2_per_um": (0.15, 0.25, 0.50),                 # layout area per um of switch width (contacted-poly pitch ~0.18 um, multi-finger)
    "wl_buffer_um2": (1.5, 3.0, 6.0),
    "decoder_um2_per_row": (1.0, 2.0, 4.0),
    "sense_input_um2": (10.0, 20.0, 40.0),                   # per column
    "comparator_um2": (6.0, 12.0, 24.0),                     # per comparator (latch + preamp)
    "dac_um2": (200.0, 400.0, 800.0),                        # per reference DAC
    "sram_um2_per_bit": (0.35, 0.5, 0.8),                    # 6T cell 45 nm ~0.35 um^2; with sense/decode overhead
    "r_sheet_ohm_sq": (0.01, 0.02, 0.05),                    # thick top metal
    "decap_ff_um2": (5.0, 10.0, 20.0),                       # MOS capacitor density
}
GAIN_BITS = 3 * (C.CELLS_PER_MACRO_ROW + C.GROUPS_PER_COLUMN * C.G_1C) * 12      # rank-3 row-gain correction, 12-bit factors (scaleup.c2_budget)
OVERHEAD = 0.20                                              # [ASSUM] control, timing, power-grid, edge cells: +20% of the sum


def area(r_drv: float = 10.0, both_ends: bool = True, level: int = 1, table_bits: int | None = None, gain_bits: int | None = None, comps_per_col: int = C.G_1C, rho: float = C.RAIL_R_DEFAULT) -> dict:
    L = {k: v[level] for k, v in LEVELS.items()}
    n_rows_macro = C.ROWS_TOTAL * C.N_MACROS
    w_drv = RTX_W_OHM_UM / r_drv
    drivers = n_rows_macro * (2 if both_ends else 1) * w_drv * L["driver_um2_per_um"]
    parts = dict(
        cell_array=C.ROWS_TOTAL * C.FULL_CELLS * CELL_UM2,
        row_drivers=drivers,
        wordline_buffers=n_rows_macro * L["wl_buffer_um2"],
        row_decoder=C.ROWS_TOTAL * L["decoder_um2_per_row"],
        sense_front_ends=C.FULL_CELLS * (L["sense_input_um2"] + comps_per_col * L["comparator_um2"]),
        reference_dacs=comps_per_col * L["dac_um2"],
        ladder_and_gain_storage=((table_bits or 16140) + (gain_bits if gain_bits is not None else GAIN_BITS)) * L["sram_um2_per_bit"],
        supply_ground_straps=(C.ROWS_TOTAL + C.MACRO_BITLINES) * C.PITCH_UM_1C * (L["r_sheet_ohm_sq"] * C.PITCH_UM_1C / rho) * C.N_MACROS,   # per macro: vertical supply strap (512 pitches) + horizontal ground strap (64 pitches), width = R_sheet * pitch / rho
    )
    tot = sum(parts.values()) * (1 + OVERHEAD)
    parts["overhead_20pct"] = sum(parts.values()) * OVERHEAD
    return dict(parts_um2=parts, total_um2=tot, total_mm2=tot * 1e-6, driver_width_um=w_drv)


def decap_um2(i_array_a: float, t_pulse_s: float, dv_v: float, level: int = 1) -> float:
    return (i_array_a * t_pulse_s / dv_v) / (LEVELS["decap_ff_um2"][level] * 1e-15)


def main() -> None:
    out = dict(cell_um2=CELL_UM2, rtx_w_ohm_um=RTX_W_OHM_UM, levels=LEVELS, overhead=OVERHEAD, variants={}, sensitivity={}, decap={})
    for nm, kw in {"baseline: both-end drivers, R_DRV 10": dict(), "single-end driver R_DRV 2 (budget just closes)": dict(r_drv=2.0, both_ends=False), "both-end R_DRV 20": dict(r_drv=20.0),
                   "full ladder table (29 kbit) instead of half": dict(table_bits=29052)}.items():
        a = area(**kw); out["variants"][nm] = dict(total_mm2=a["total_mm2"], parts_mm2={k: v * 1e-6 for k, v in a["parts_um2"].items()}, driver_width_um=a["driver_width_um"])
        print(f"{nm}: {a['total_mm2']:.4f} mm2; " + ", ".join(f"{k} {v*1e-6:.4f}" for k, v in a["parts_um2"].items()))
    for lv, name in enumerate(("low", "mid", "high")):
        a = area(level=lv); out["sensitivity"][name] = a["total_mm2"]
    print("density sensitivity low/mid/high total mm2:", out["sensitivity"])
    for dv, T in product((0.001, 0.005, 0.010, 0.050), (0.25e-9, 0.5e-9, 1e-9)):
        out["decap"][f"dv={dv*1e3:.0f}mV,T={T*1e9}ns"] = decap_um2(0.0692, T, dv) * 1e-6
    print("decap mm2 for I = 69 mA:", {k: round(v, 3) for k, v in out["decap"].items()})
    RP.FULL_ARRAY.mkdir(parents=True, exist_ok=True)
    (RP.FULL_ARRAY / "area_model.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
