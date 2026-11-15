#!/usr/bin/env python3
"""Energy per inference of the theta-free design (packed-row crossbar reads, ping-pong counters, 3-lane ingest), from measured pieces:
  digital   E = c0 * cycles + e_ev * events + e_rd * passes     c0, e_ev, e_rd: least-squares fit to SAIF windows (OpenSTA, routed-stage parasitics, fast library) -> opt/power2.py
  SRAM      the count-memory macros ARE inside the STA total (their CACTI energies are in the macro liberty and OpenSTA lists them as instances; only the group label says "Macro 0 %"), so they are not added again;
            --sram-uw only reports their share (instance report of the same window)
  crossbar  pJ per packed read from studies/crossbar/results/macro_512x32/packed_reads.json (scaleup.packed_reads: 3.5 kohm, 1 ns window cap, the packed read population of each
            dataset at the package's S_ROWS: signal current and comparator decisions per read) x reads
  counts    per sample from the RTL regression logs (cycles, events accepted, packed reads, analog passes)
  python opt/energy_v2.py --fit work/opt/h5/power2_groute.json --tags dvs=v8_dvs,v8_dvs_s1,v8_dvs_s2 nm=v8_nm"""
import argparse, collections, gzip, json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
import re as _re
_S = int(_re.search(r"localparam int S_ROWS\s*=\s*(\d+)", (ROOT / "rtl" / "pkg" / "cim_neurohdc_pkg.sv").read_text()).group(1))
_XB = json.loads((ROOT.parents[1] / "studies" / "crossbar" / "results" / "macro_512x32" / "packed_reads.json").read_text())["rows"][str(_S)]["pJ_per_read"]
ap = argparse.ArgumentParser()
ap.add_argument("--fit", required=True)
ap.add_argument("--sram-uw", nargs=2, type=float, required=True, help="count-SRAM power in the DVS and N-MNIST windows (uW)")
ap.add_argument("--tags", nargs="+", required=True)
ap.add_argument("--out", default=str(ROOT / "results/ppa/v2_energy.json"))
ap.add_argument("--stage", default="global-route (provisional)")
ap.add_argument("--n-spk", type=int, default=20, help="neurons of the chip (40: the large chip): offsets of the TS log fields")
ap.add_argument("--xb-pj", nargs="*", default=[], help="ds=pJ per read overrides (the large chip: studies/crossbar/results/macro_512x32/packed_reads_large.json)")
a = ap.parse_args()
_XB = dict(_XB, **{k: float(v) for k, v in (x.split("=") for x in a.xb_pj)})
_O = 4 + 2 * a.n_spk          # first stats field of a TS line (TS s t spikes X[n] V[n] stats...)
fit = json.loads(Path(a.fit).read_text())["fit"]
c0, e_ev, e_rd = fit["c0_J_per_cycle"], fit["e_event_J"], fit["e_read_J"]


def counts(tag):
    reads, passes, cyc, ev = collections.defaultdict(int), collections.defaultdict(int), {}, {}
    for l in gzip.open(ROOT / f"results/hdc/{tag}.out.txt.gz", "rt"):
        f = l.split()
        if f[0] == "TS":
            reads[int(f[1])] += int(f[_O + 4]); passes[int(f[1])] += int(f[_O + 6])
        elif f[0] == "END":
            cyc[int(f[1])] = int(f[2]); ev[int(f[1])] = int(f[5])
    S = sorted(cyc)
    acc = json.loads((ROOT / f"results/hdc/{tag}.json").read_text())["summary"]["accuracy"]
    return dict(cycles=np.mean([cyc[s] for s in S]), events=np.mean([ev[s] for s in S]), reads=np.mean([reads[s] for s in S]), passes=np.mean([passes[s] for s in S]), accuracy=acc, n=len(S))


out = {}
for grp in a.tags:
    ds, tags = grp.split("=")
    sram_uw = a.sram_uw[0 if ds == "dvs" else 1]
    per = []
    for tag in tags.split(","):
        c = counts(tag)
        dig = (c0 * c["cycles"] + e_ev * c["events"] + e_rd * c["passes"]) * 1e6
        sram = sram_uw * 1e-6 * c["cycles"] * 10e-9 * 1e6
        xb = _XB[ds] * 1e-12 * c["reads"] * 1e6
        tot = dig + xb                      # sram is inside dig (see header); kept as a reported share
        lat = c["cycles"] * 10e-9
        per.append(dict(tag=tag, **{k: float(v) for k, v in c.items()}, digital_uJ=dig, digital_of_which_sram_uJ=sram, digital_split_uJ=dict(baseline=c0 * c["cycles"] * 1e6, ingest=e_ev * c["events"] * 1e6, scan=e_rd * c["passes"] * 1e6),
                        sram_share_uJ=sram, crossbar_uJ=xb, energy_uJ=tot, latency_us=lat * 1e6, avg_power_mW=tot * 1e-6 / lat * 1e3))
    m = {k: float(np.mean([p[k] for p in per])) for k in ("accuracy", "cycles", "events", "reads", "digital_uJ", "sram_share_uJ", "crossbar_uJ", "energy_uJ", "latency_us", "avg_power_mW")}
    out[ds] = dict(mean=m, per_tag=per)
    print(ds, {k: round(v, 4) for k, v in m.items()})
out["method"] = dict(stage=a.stage, fit=fit, sram_uw=a.sram_uw, crossbar_pJ_per_read=_XB, s_rows=_S)
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_text(json.dumps(out, indent=1))
