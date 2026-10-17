"""F5/F7: 1C's area table (scaleup.area) re-run with the real sense periphery in place of the assumed 'sense input 20 um2 + 8 comparators x 12 um2 per column + 8 reference DACs'.

Per column (160 columns), each term low / mid / high like 1C's densities [ASSUM], from the transistors actually simulated:
  conveyor + OTAs + copy + mirror : sum of W x L of the differential channel (sense.mc.gate_area_um2) x layout factor (analog layout with guard rings, dummies, routing: 3 / 5 / 8) [SIM area, ASSUM factor]
  integration capacitors          : 2 x C_INT at MIM/MOM density 20 / 10 / 5 fF/um2 [ASSUM]
  decision stage                  : preamplifier (W = 32 um pair/tail, gate area x layout factor) + latch 12 um2 [SIM + ASSUM]
  threshold capacitor array       : 10-bit, 250 um2 (low 150 / high 400) [ASSUM]
  calibration trims               : 2 channels x 10 bits (switch + latch) x 1.5 um2/bit  [ASSUM]
Shared: the threshold storage and rank-3 gain factors (bits as 1C, + per-column calibration words), the decoupling capacitance at the 0.35 V rail (C_dec / 5.0 - 8.2 fF/um2 measured on the PTM card, sense.pdn).
Usage: python -m sense.area_1f"""
from __future__ import annotations

import json

import device.constants as C
import paths as RP
from scaleup import area as A
from sense import mc
from sense.cal import DESIGN
from sense.pareto import C_INT, PRE_W

LAYOUT = (3.0, 5.0, 8.0)
CAP_DENSITY = (20.0, 10.0, 5.0)          # fF/um2 MIM/MOM: low area = high density
THR_ARRAY = (150.0, 250.0, 400.0)
LATCH = (8.0, 12.0, 20.0)
TRIM_PER_BIT = (1.0, 1.5, 3.0)
DECAP_DENSITY = (8.2, 6.0, 5.0)          # fF/um2 at 0.35 V (SIM, sense.pdn): accumulation-mode isolated well, mid, NMOS over ground


def sense_area_per_col(level: int) -> dict:
    dz = mc.Design(**DESIGN)
    gate = mc.gate_area_um2(dz) * LAYOUT[level]
    caps = 2 * C_INT * 1e15 / CAP_DENSITY[level]
    pre = (2 * PRE_W * 90e-9 + PRE_W * 90e-9 + 2 * 4e-6 * 180e-9) * 1e12 * LAYOUT[level] + LATCH[level]
    return dict(conveyor_channel=gate, integration_caps=caps, decision=pre, threshold_cap_array=THR_ARRAY[level], trims=2 * 10 * TRIM_PER_BIT[level])


def area_table(c_dec_f: float = 0.0, level: int = 1, trim_bits: int = 160 * 2 * 20) -> dict:
    base = A.area(level=level)                         # 1C baseline (rank-3 storage etc.)
    parts = dict(base["parts_um2"])
    old = parts.pop("sense_front_ends") + parts.pop("reference_dacs")
    s = sense_area_per_col(level)
    parts["sense_front_ends_1f"] = C.FULL_CELLS * sum(s.values())
    parts["calibration_storage"] = trim_bits * A.LEVELS["sram_um2_per_bit"][level]
    if c_dec_f:
        parts["decoupling"] = c_dec_f * 1e15 / DECAP_DENSITY[level]
    over = parts.pop("overhead_20pct")
    tot = sum(parts.values()) * (1 + A.OVERHEAD)
    parts["overhead_20pct"] = sum(parts.values()) * A.OVERHEAD
    return dict(parts_um2=parts, total_um2=tot, total_mm2=tot * 1e-6, sense_per_col=s, replaced_1c_um2=old, total_1c_mm2=base["total_mm2"])


def main() -> None:
    out = {}
    for c_dec in (0.0, 1e-9, 2e-9, 20e-9):
        for lv, nm in enumerate(("low", "mid", "high")):
            t = area_table(c_dec, lv)
            out[f"c_dec={c_dec*1e9:g}nF|{nm}"] = t
    for c_dec in (0.0, 1e-9, 20e-9):
        t = out[f"c_dec={c_dec*1e9:g}nF|mid"]
        print(f"C_dec {c_dec*1e9:g} nF mid: total {t['total_mm2']:.4f} mm2 (1C table {t['total_1c_mm2']:.4f}); " + ", ".join(f"{k} {v*1e-6:.4f}" for k, v in t["parts_um2"].items()))
    print("sense per column (mid, um2):", {k: round(v, 1) for k, v in out["c_dec=0nF|mid"]["sense_per_col"].items()}, "vs 1C 116 um2")
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "area_table_1f.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
