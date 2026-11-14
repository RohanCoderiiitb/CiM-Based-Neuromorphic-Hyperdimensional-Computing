#!/usr/bin/env python3
"""Power of the final routed layout when ingest and scan OVERLAP (ping-pong counters): gate-level simulation of routed.v -> VCD window -> SAIF -> OpenSTA with the layout SPEF, fast library.

The earlier methodology (power.py / nm_power.py) measured an `ing` window and a `mvm` window and added P_ing x ingest cycles + P_scan x remaining cycles; that no longer applies because the scan of timestep t
runs while the events of t+1 are taken in. Instead, many windows (any dataset, any position in a sample) are simulated; each gives E_w = P_w x T_w together with what happened in the window, counted from the
VCD at every rising clock edge: events accepted (lane 0 + extra lanes), crossbar passes issued (rd_valid), cycles. Then
        E_w  =  c0 * cycles  +  e_ev * events  +  e_rd * reads
is fitted by least squares over all windows (c0: the activity-independent power - clock tree, leakage, idle logic; e_ev: energy per accepted event; e_rd: digital energy per crossbar read) and applied to the
counts of every sample (cycles, events, reads from the RTL regression). The fit residuals are printed: they are the check that the three-term model describes the chip.
  python opt/power2.py --tag g4 --build ee_off --spec dvs:46:60000:6000 nm:7:300:3000 ...        (dataset:row:start_cycle:length)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gatesim as GS  # noqa: E402
import power as PW  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402
import nm_power as NP  # noqa: E402

SYNTH = PW.SYNTH


def count_window(vcd: Path, t_lo: int, t_hi: int) -> dict:
    """cycles, accepted events, crossbar passes issued in the VCD, sampled just before every rising clock edge (ps times)."""
    want = {"clk_i": "clk", "ev_ready_o": "ev0", "ev_valid_i": "v0", "rd_valid_o": "rd", "evx_ready_o": "evx"}
    ids, scope = {}, []
    with open(vcd) as f:
        for line in f:
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                p = line.split()
                nm = p[4].lstrip("\\")
                if scope and scope[-1] == "dut" and nm in want:
                    ids.setdefault(p[3], []).append(want[nm])
            elif line.startswith("$enddefinitions"):
                break
        vals = {k: 0 for k in want.values()}
        cyc = ev = rd = 0
        t = 0
        snap = dict(vals)
        clk_prev = 0
        for line in f:
            c = line[0]
            if c == "#":
                t = int(line[1:])
                snap = dict(vals)
                continue
            if c in "01xzXZ":
                i, v = line[1:].strip(), c
                new = 1 if v == "1" else 0
            elif c == "b":
                v, i = line[1:].split()
                new = v.count("1")
            else:
                continue
            for nm in ids.get(i, []):
                if nm == "clk":
                    if new == 1 and clk_prev == 0 and t_lo <= t < t_hi:
                        cyc += 1
                        ev += snap["ev0"] * snap["v0"] + snap["evx"]
                        rd += snap["rd"]
                    clk_prev = new
                vals[nm] = new
    return dict(cycles=cyc, events=ev, reads=rd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--build", default="ee_off")
    ap.add_argument("--cols", type=int, default=40)
    ap.add_argument("--stage", default="routed", help="layout stage whose netlist (<stage>.v) and SPEF (<stage>_fast.spef) are used: routed, or groute (provisional)")
    ap.add_argument("--spec", nargs="+", required=True, help="dataset:row:start:length (dataset dvs|nm)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    run = SYNTH / "work" / "opt" / a.tag
    const = json.loads((run / "syn" / "const_ports.json").read_text())
    mdls = {}
    rows = []
    for k, sp in enumerate(a.spec):
        ds, row, start, length = sp.split(":")
        row, start, length = int(row), int(start), int(length)
        if ds not in mdls:
            mdls[ds] = NP.nm_model() if ds == "nm" else H.load_model("r1", 0, "dvsgesture")
        name = f"w{k}_{ds}{row}"
        d = GS.run(a.build, run / f"gs_{name}", run / (a.stage + ".v"), const, row, start, length, theta=4095, cols=a.cols, mdl=mdls[ds], vcd_name=f"{name}.vcd")
        pw = PW.sta_power(run, a.stage, name, Path(d["vcd"]), "fast")
        # the window in VCD time: the TB dumps [start, start+length) cycles from the sample start; count over the whole file
        cnt = count_window(Path(d["vcd"]), 0, 1 << 62)
        Path(d["vcd"]).unlink(missing_ok=True)
        r = dict(spec=sp, dataset=ds, row=row, start=start, length=length, power_w=pw["total_w"], leakage_w=pw["leakage_w"], ann=pw["annotation"], golden=d["matches_golden"], **cnt)
        rows.append(r)
        print(json.dumps(r), flush=True)
    A = np.array([[r["cycles"], r["events"], r["reads"]] for r in rows], float)
    E = np.array([r["power_w"] * r["cycles"] * 10e-9 for r in rows], float)                 # J (10 ns cycles)
    coef, res, rk, sv = np.linalg.lstsq(A, E, rcond=None)
    pred = A @ coef
    fit = dict(c0_J_per_cycle=coef[0], e_event_J=coef[1], e_read_J=coef[2], residual_rel=[float((p - e) / e) for p, e in zip(pred, E)], rank=int(rk))
    print("FIT", json.dumps(fit, indent=1))
    Path(a.out or run / f"power2_{a.stage}.json").write_text(json.dumps(dict(windows=rows, fit=fit), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
