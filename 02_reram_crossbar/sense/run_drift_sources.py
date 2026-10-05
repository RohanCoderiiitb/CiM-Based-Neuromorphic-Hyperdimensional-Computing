"""F2: which mismatch source makes the per-column calibration go stale when the temperature moves (and so whether autozero of the amplifier offset would help)? Calibrate (gain + offset, 2 parameters per channel)
at 27 C on DC channel currents with ONE group of devices mismatched at a time, read at 47 and 67 C. Usage: python -m sense.run_drift_sources"""
from __future__ import annotations

import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from sense import cal, mc

SOURCES = {"all": lambda n: True, "OTA1 only": lambda n: n.startswith("a"), "copy devices only": lambda n: n[:2] in ("M1", "M2"), "PMOS mirror only": lambda n: n.startswith("Mp"), "OTA2 only": lambda n: n.startswith("b")}


def main(n: int = 60) -> None:
    dz = mc.Design(**cal.DESIGN)
    rng = np.random.default_rng(31)
    draws = [mc.draw(dz, rng) for _ in range(n)]
    out = {}
    with Pool(10) as pool:
        nom = {T: np.array(pool.map(cal._job, [(dz, m, pos, None, T) for pos, m in cal.POINTS])) for T in (27.0, 47.0, 67.0)}
        for name, sel in SOURCES.items():
            dv = [{k: v for k, v in d.items() if sel(k)} for d in draws]
            meas = {T: np.array([pool.map(cal._job, [(dz, m, pos, d, T) for pos, m in cal.POINTS]) for d in dv]) for T in nom}
            par = [cal.to_physical(cal.fit(meas[27.0][i], nom[27.0]), nom[27.0]) for i in range(n)]
            row = {}
            for T in nom:
                res = np.array([cal.residual(meas[T][i], nom[T], par[i]) for i in range(n)])
                row[f"{T:g}"] = dict(sigma_worst_point_uA=float(res.std(0).max() * 1e6), rms_uA=float(np.sqrt(np.mean(res ** 2)) * 1e6))
            out[name] = row
            print(name, {T: (round(v["rms_uA"], 3), round(v["sigma_worst_point_uA"], 3)) for T, v in row.items()}, flush=True)
    (RP.SENSE / "drift_by_source.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
