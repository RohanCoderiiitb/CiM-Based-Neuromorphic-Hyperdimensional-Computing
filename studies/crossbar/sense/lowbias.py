"""Item 9 support: the front-end noise at LOWER bias than 1F simulated (vb 0.42 .. 0.50): vb 0.52 .. 0.62 (less tail current), device-level noise over the integration window, bias current, power-up time
and step fidelity. A plane that tolerates more noise (sense.plane_readout) can use these points. Usage: python -m sense.lowbias"""
from __future__ import annotations

import json

import paths as RP
from sense import mc
from sense.cal import DESIGN
from sense.enable import power_up
from sense.sweep_b import one


def main() -> None:
    rows = []
    for vb in (0.42, 0.46, 0.50, 0.52, 0.54, 0.56, 0.58, 0.60):
        des = dict(DESIGN); des["vb"] = vb
        dz = mc.Design(**des)
        kw = {k: v for k, v in des.items() if k not in ("vs",)}
        try:
            n = mc.noise(dz, windows=(0.5e-9, 1e-9, 2e-9))
            fid = {f"{T*1e9:g}": mc.fidelity(dz, T) for T in (0.5e-9, 1e-9)}
            pu = power_up(dz, t_end=12e-9)
            r = dict(vb=vb, sigma_uA={f"{T*1e9:g}": v * 1e6 for T, v in n["sigma"].items()}, step_ratio_min={k: v["step_ratio_min"] for k, v in fid.items()}, i_bias_uA=mc.bias_current(dz)["i_vdd_a"] * 1e6, t_powerup_ns=pu["t_settle_ns"], i_idle_uA=pu["i_final_uA"])
        except Exception as e:                      # reported, not hidden
            r = dict(vb=vb, error=str(e)[:200])
        rows.append(r)
        print(r, flush=True)
    (RP.SENSE / "lowbias.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
