"""F2(b): static mismatch of the chosen front-end (b), by source. Pelgrom Vth mismatch (AVT [ASSUM] from 1A) imposed device by device through delvto on the whole differential channel; the quantity is the
differential input-referred current error (sample - nominal) of a read, per group and level m, and the split by group of devices (each group mismatched alone). No calibration applied here (sense.cal does that).
Also the common-mode gain (CMRR) measured with equal current added to both bitlines, for the nominal channel and over the mismatch draws. Usage: python -m sense.run_mismatch"""
from __future__ import annotations

import json
from multiprocessing import Pool

import numpy as np

import device.constants as C
import paths as RP
from sense import mc, port as P
from sense.cal import DESIGN

SOURCES = {"all": lambda n: True, "regulating amp OTA1": lambda n: n.startswith("a"), "cascode amp OTA2": lambda n: n.startswith("b"), "copy devices M1/M2": lambda n: n[:2] in ("M1", "M2"), "PMOS mirror": lambda n: n.startswith("Mp")}


def _cm(a):
    dz, pos, dv = a
    return mc.cmrr(dz, pos, 4, 20e-6, dv)


def main(n: int = 80) -> None:
    dz = mc.Design(**DESIGN)
    rng = np.random.default_rng(3)
    draws = [mc.draw(dz, rng) for _ in range(n)]
    out = dict(design=DESIGN, n=n, avt_mv_um=C.AVT_MV_UM, sigma_uA={}, cm_gain={})
    with Pool(10) as pool:
        for pos, name in ((P.FAR_POS0, "far"), (P.NEAR_POS0, "near")):
            out["sigma_uA"][name] = {}
            for src, sel in SOURCES.items():
                row = {}
                for m in (1, 4, 7):
                    nom = mc._one((dz, m, pos, None, 0.0))
                    r = pool.map(mc._one, [(dz, m, pos, {k: v for k, v in d.items() if sel(k)}, 0.0) for d in draws])
                    row[str(m)] = float(np.nanstd(np.array(r) - nom) * 1e6)
                out["sigma_uA"][name][src] = row
            cm0 = mc.cmrr(dz, pos, 4, 20e-6)
            cms = np.array(pool.map(_cm, [(dz, pos, d) for d in draws]))
            out["cm_gain"][name] = dict(nominal=float(cm0), mismatch_sigma=float(np.nanstd(cms)), mismatch_max_abs=float(np.nanmax(abs(cms))))
            print(name, {s: [round(v, 2) for v in r.values()] for s, r in out["sigma_uA"][name].items()}, out["cm_gain"][name], flush=True)
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "mismatch_mc.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
