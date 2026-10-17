"""F2: calibration residual measured on the real read transient, vs read pulse length T, integration tail and OTA bias. Usage: python -m sense.run_cal_transient"""
from __future__ import annotations

import itertools
import json

import paths as RP
from sense import cal


def main() -> None:
    out = []
    for vb, T, tail in itertools.product((0.42, 0.46, 0.50), (0.5e-9, 1e-9, 2e-9), (0.3e-9, 1.0e-9)):
        r = cal.run_transient(T, n=40, tail=tail, design=dict(vb=vb), seed=12 + int(1e3 * vb))
        out.append(r)
        print(f"vb {vb} T {T*1e9:g} ns tail {tail*1e9:g} ns: raw {r['raw_rms_uA']:.1f}  gain-only {r['gain_only']['sigma_worst_point_uA']:.2f}  gain+offset sigma_worst {r['gain_and_offset']['sigma_worst_point_uA']:.2f} rms {r['gain_and_offset']['rms_uA']:.2f}", flush=True)
    (RP.SENSE / "calibration_transient.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
