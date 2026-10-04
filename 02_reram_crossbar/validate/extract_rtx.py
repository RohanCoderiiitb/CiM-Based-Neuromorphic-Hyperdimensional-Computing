"""Fix 1: access-transistor R_tx from the PTM 45nm LP card. Writes results/transistor.json.

Usage: python -m validate.extract_rtx
"""
from __future__ import annotations

import json
from pathlib import Path

import device.constants as C
from device.constants import Params
from spice.transistor import branch_rtx, cell_pitch_um, idsat_per_um, rdsw_floor_ohm, width_um
from validate import analysis as A

ROOT = Path(__file__).resolve().parents[1]
AREAS = (20, 40, 60, 100)
RDSW = 210.0   # ohm*um, from the card (nmos rdsw); the card is rdsmod=0, wr=1


def main() -> None:
    p0 = Params()
    out = {"idsat_ma_per_um": idsat_per_um(p0), "rdsw_ohm_um": RDSW, "fill": C.TX_FILL, "feature_nm": C.FEATURE_NM,
           "v_wl": C.V_WL, "rows": []}
    for area in AREAS:
        w = width_um(area, C.TX_FILL, C.FEATURE_NM)
        p = p0.with_(tx_w_um=w)
        lrs, hrs = branch_rtx(C.GAP_LRS, p), branch_rtx(C.GAP_HRS, p)
        p_lin = p.with_(r_tx=lrs["r_tx"])
        row = dict(area_f2=area, w_um=w, pitch_um=cell_pitch_um(area, C.FEATURE_NM), rdsw_floor=rdsw_floor_ohm(w, RDSW),
                   rtx_lrs=lrs["r_tx"], i_lrs=lrs["i"], rtx_hrs=hrs["r_tx"], i_hrs=hrs["i"], leff_nm=lrs["leff_m"] * 1e9,
                   idsat_ua=out["idsat_ma_per_um"] * 1e3 * w,
                   single_gap_g32=float(A.level_gap_single_column(32, p_lin)[-1]),
                   r_eff=float(A.r_eff_lrs(p_lin)))
        out["rows"].append(row)
    nominal = next(r for r in out["rows"] if r["area_f2"] == C.CELL_AREA_F2)
    out["nominal"] = nominal
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "transistor.json").write_text(json.dumps(out, indent=2))
    print(f"Idsat = {out['idsat_ma_per_um']:.4f} mA/um")
    for r in out["rows"]:
        print({k: round(v, 4) for k, v in r.items()})


if __name__ == "__main__":
    main()
