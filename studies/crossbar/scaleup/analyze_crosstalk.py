"""C2(b) analysis: coupled error and its data dependence versus sampling time (reads results/transient/crosstalk_macro_raw.json).
For each group G and coupling fraction: at each sampling time t_s over the N neighbour/data patterns
  err        = victim I_diff(t_s) - I_diff(final)                      (settling + coupling, vs the DC value)
  spread     = max_pattern |err - mean_pattern(err)|                   (what remains if the ladder is calibrated at t_s: data-dependent, uncorrectable)
  coupling   = err(cc) - err(cc = 0) on the same pattern; its spread  (the coupling-induced, neighbour-data-dependent part alone)
Also the earliest sampling time at which the data-dependent spread falls below 0.05 / 0.1 / 0.2 uA.
Usage: python -m scaleup.analyze_crosstalk"""
from __future__ import annotations

import paths as RP

import json

import numpy as np

import device.constants as C


def analyse() -> dict:
    raw = json.loads((RP.TRANSIENT / "crosstalk_macro_raw.json").read_text())
    ts = np.array(raw["t_s"]); runs = raw["runs"]
    out = {"t_s_ps": (ts * 1e12).tolist(), "groups": {}}
    for G in sorted({r["G"] for r in runs}):
        err = {}
        for cc in sorted({r["cc"] for r in runs}):
            rr = sorted([r for r in runs if r["G"] == G and r["cc"] == cc], key=lambda r: r["pat"])
            err[cc] = np.array([r["err_a"] for r in rr])               # (patterns, times)
        res = {}
        for cc, e in err.items():
            spread = np.abs(e - e.mean(0, keepdims=True)).max(0)
            absmax = np.abs(e).max(0)
            entry = dict(abs_max_a=absmax.tolist(), spread_a=spread.tolist())
            if cc > 0:
                ce = e - err[0.0]
                entry["coupling_abs_max_a"] = np.abs(ce).max(0).tolist()
                entry["coupling_spread_a"] = np.abs(ce - ce.mean(0, keepdims=True)).max(0).tolist()
            for eps in (0.05e-6, 0.1e-6, 0.2e-6):
                idx = np.flatnonzero(spread <= eps)
                entry[f"t_spread_below_{eps*1e6:.2f}uA_ps"] = float(ts[idx[0]] * 1e12) if len(idx) else None
            res[str(cc)] = entry
        out["groups"][str(G)] = res
    return out


def main() -> None:
    o = analyse()
    (RP.TRANSIENT / "crosstalk_macro_summary.json").write_text(json.dumps(o, indent=1))
    ts = o["t_s_ps"]
    for G, res in o["groups"].items():
        for cc, e in res.items():
            print(f"G={G} cc={cc}: |err| max over patterns at t_s [{', '.join(str(int(t)) for t in ts)}] ps (uA): " + " ".join(f"{v*1e6:.2f}" for v in e["abs_max_a"]))
            print(f"      data-dependent spread (uA): " + " ".join(f"{v*1e6:.3f}" for v in e["spread_a"]) + (f"  | coupling-only spread: " + " ".join(f"{v*1e6:.3f}" for v in e["coupling_spread_a"]) if "coupling_spread_a" in e else ""))


if __name__ == "__main__":
    main()
