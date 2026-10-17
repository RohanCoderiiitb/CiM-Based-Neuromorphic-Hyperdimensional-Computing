#!/usr/bin/env python3
"""Criterion 6: compare a Verilator run and an Icarus run PER TIMESTEP (spikes, X[20], V[20], every instrumentation counter, cycle counts).
Samples are matched by dataset row; the Icarus run may cover a subset of the Verilator run's rows.
usage: compare_sims.py VERILATOR_TAG ICARUS_TAG [...]  (tag pairs given as vtag:itag)  -> results/regression/sim_compare.json"""
import gzip, json, pathlib, sys
R = pathlib.Path(__file__).resolve().parent.parent / "results" / "regression"


def load(tag):
    meta = json.load(open(R / f"{tag}.json"))
    rows = {s["row"]: s["row"] for s in meta["samples"]}  # the "sample" field of the timestep log is the dataset row
    ts = {}
    with gzip.open(R / f"{tag}.timesteps.jsonl.gz", "rt") as f:
        for line in f:
            d = json.loads(line)
            ts[(rows[d["sample"]], d["t"])] = d
    return meta, ts


def compare(vtag, itag):
    vm, vt = load(vtag); im, it = load(itag)
    vrows = {s["row"]: s for s in vm["samples"]}
    out = dict(verilator=vtag, icarus=itag, rows_compared=len(im["samples"]), timesteps_compared=0, disagreements=[], fields=["spikes", "X", "V", "stats", "golden_match"])
    for (row, t), di in sorted(it.items()):
        dv = vt.get((row, t))
        if dv is None:
            out["disagreements"].append(dict(row=row, t=t, field="missing in verilator run")); continue
        out["timesteps_compared"] += 1
        for k in out["fields"]:
            if dv.get(k) != di.get(k):
                out["disagreements"].append(dict(row=row, t=t, field=k, verilator=str(dv.get(k))[:160], icarus=str(di.get(k))[:160]))
    for s in im["samples"]:  # per-sample totals and raster hash
        v = vrows.get(s["row"])
        for k in ("raster_hash", "cycles", "stall_cycles", "pred", "n_events", "group_reads_issued", "active_addrs_total", "rows_skipped"):
            if v is None or v.get(k) != s.get(k):
                out["disagreements"].append(dict(row=s["row"], t=None, field=k, verilator=None if v is None else v.get(k), icarus=s.get(k)))
    out["verdict"] = "AGREE" if not out["disagreements"] else "DISAGREE"
    return out


if __name__ == "__main__":
    res = [compare(*p.split(":")) for p in sys.argv[1:]]
    json.dump(res, open(R / "sim_compare.json", "w"), indent=1)
    for r in res:
        print(f"{r['verdict']}: {r['icarus']} vs {r['verilator']}: {r['rows_compared']} samples, {r['timesteps_compared']} timesteps, {len(r['disagreements'])} disagreements")
        for d in r["disagreements"][:5]:
            print("   ", d)
    sys.exit(0 if all(r["verdict"] == "AGREE" for r in res) else 1)
