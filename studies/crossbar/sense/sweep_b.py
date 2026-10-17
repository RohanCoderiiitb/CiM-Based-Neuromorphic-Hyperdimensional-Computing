"""F2 design sweep of the chosen front-end (b): noise (device level), step fidelity, bias power, gate area and common-mode gain for combinations of copy ratio k, conveyor width W1, OTA bias vb, OTA1 input width and
PMOS-mirror size. Usage: python -m sense.sweep_b  (writes results/sense_frontend/sweep_b.json)"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import paths as RP
from sense import mc, port as P


def one(kw):
    dz = mc.Design(vs=0.45, **kw)
    try:
        n = mc.noise(dz)
        fid = {f"{T*1e9:g}": mc.fidelity(dz, T) for T in (0.5e-9, 1e-9)}
        cm = mc.cmrr(dz, P.FAR_POS0)
        return dict(design=kw, sigma_uA={f"{T*1e9:g}": v * 1e6 for T, v in n["sigma"].items()}, step_ratio_min={k: v["step_ratio_min"] for k, v in fid.items()}, vn_mV={k: v["vn_mV"] for k, v in fid.items()},
                    i_bias_uA=mc.bias_current(dz)["i_vdd_a"] * 1e6, gate_area_um2=mc.gate_area_um2(dz), cm_gain=cm)
    except Exception as e:                                      # a non-converging point is reported, not hidden
        return dict(design=kw, error=str(e)[:200])


def main() -> None:
    grid = []
    for vb, (wp, lp), k, w1, wi1 in itertools.product((0.42, 0.46, 0.50), ((4e-6, 90e-9), (8e-6, 180e-9), (16e-6, 360e-9)), (2.0, 4.0), (8e-6, 15e-6), (8e-6, 16e-6)):
        grid.append(dict(vb=vb, wp=wp, lp=lp, k=k, w1=w1, wi1=wi1))
    with Pool(10) as p:
        res = p.map(one, grid, chunksize=1)
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "sweep_b.json").write_text(json.dumps(res, indent=1))
    for r in res:
        if "error" in r:
            print("FAIL", r["design"], r["error"])
            continue
        d = r["design"]
        print(f"vb {d['vb']} wp {d['wp']*1e6:g} k {d['k']:g} w1 {d['w1']*1e6:g} wi1 {d['wi1']*1e6:g}: sig(0.5/1/2) {r['sigma_uA']['0.5']:.2f}/{r['sigma_uA']['1']:.2f}/{r['sigma_uA']['2']:.2f} step {r['step_ratio_min']['0.5']:.2f}/{r['step_ratio_min']['1']:.2f} I {r['i_bias_uA']:.0f} uA area {r['gate_area_um2']:.0f} cm {r['cm_gain']:.4f}")


if __name__ == "__main__":
    main()
