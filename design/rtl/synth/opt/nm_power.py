#!/usr/bin/env python3
"""N-MNIST power of the final routed layout (f2) from switching activity (SAIF): gate-level simulation of routed.v on an N-MNIST sample (N-MNIST weights, geometry, event stream), two windows as power.py
(`ing` inside the ingest phase, `mvm` the whole non-ingest part) of one timestep, SAIF -> OpenSTA with the layout SPEF, fast library.
Window boundaries come from the RTL run of the same sample (results/hdc/<tag>.out.txt.gz, unfactorized build: same cycles per timestep as the factorized one).
The laid-out chip stores a rank-1 class image; no rank-1 N-MNIST network exists, so the class image used here is the rank-1 sign approximation of the trained class hypervector (affects only the
5-cycle query step's activity; the SNN part, which is the activity that matters, is exact N-MNIST and checked against the golden spikes).
  python opt/nm_power.py --tag f2 --row 46 --ts 30"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gatesim as GS  # noqa: E402
import power as PW  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402

ROOT, SYNTH = PW.ROOT, PW.SYNTH


def nm_model() -> dict:
    m = H.load_model("base", 0, "nmnist")
    B = 2 * m["class_hv"].astype(float) - 1
    a = np.zeros((10, 20), np.uint8)
    b = np.zeros((10, 100), np.uint8)
    for i in range(10):
        u, s, vt = np.linalg.svd(B[i])
        a[i], b[i] = (vt[0] > 0), (u[:, 0] > 0)
    hv = H.HQ.expand_r1(a, b)
    prefix = np.stack([H.HQ.prefix_scores(H.HQ.agree_unfactorized(m["spikes"][i], hv)) for i in range(len(m["spikes"]))])
    m.update(a_bits=a, b_bits=b, class_hv=hv, prefix=prefix, pred=prefix[:, -1].argmax(axis=1))
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="f2")
    ap.add_argument("--row", type=int, required=True)
    ap.add_argument("--ts", type=int, default=-1, help="-1: the timestep with the longest ingest phase (N-MNIST timesteps ingest only tens of events)")
    ap.add_argument("--rtl", default="nm_t64_s0")
    ap.add_argument("--theta", type=int, default=64)
    a = ap.parse_args()
    run = SYNTH / "work" / "opt" / a.tag
    rows = [l.split() for l in gzip.open(ROOT / "results" / "hdc" / f"{a.rtl}.out.txt.gz", "rt")]
    tsr = [r for r in rows if r[0] == "TS" and int(r[1]) == a.row]
    if a.ts < 0:
        a.ts = max(range(len(tsr)), key=lambda k: int(tsr[k][54]))
    start = sum(int(r[53]) for r in tsr[:a.ts])
    cyc, ing = int(tsr[a.ts][53]), int(tsr[a.ts][54])
    win = dict(row=a.row, timestep=a.ts, ts_start=start, ts_cycles=cyc, ts_ingest_cycles=ing, ing=dict(start=start + 2, length=ing - 4), mvm=dict(start=start + ing + 2, length=cyc - ing - 4))
    const = json.loads((run / "syn" / "const_ports.json").read_text())
    mdl = nm_model()
    res = dict(tag=a.tag, dataset="nmnist", windows=win, power={})
    for w in ("ing", "mvm"):
        d = GS.run("full", run / f"nm_gs_{w}", run / "routed.v", const, a.row, win[w]["start"], win[w]["length"], theta=a.theta, mdl=mdl, vcd_name=f"nm_{w}.vcd")
        saifname = f"nm_{w}"
        pw = PW.sta_power(run, "routed", saifname, Path(d["vcd"]), "fast")
        pw["gate_level_matches_golden"] = d["matches_golden"]
        res["power"][w] = pw
        Path(d["vcd"]).unlink(missing_ok=True)
        print(w, win[w], round(pw["total_w"] * 1e3, 4), "mW; golden", d["matches_golden"], "ann", pw["annotation"], flush=True)
    (run / "power_nmnist.json").write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
