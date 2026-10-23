#!/usr/bin/env python3
"""Phase 2-4 regression slice: stimulus from the golden vectors (Python), simulation (Verilator or Icarus), then EVERY timestep compared with the references:
the SNN part as in 1E (spikes, X, V), and the new part - the N prefix scores, the leader, the second-largest score, the exit decision, the emitted prediction and the number
of events actually ingested. Nothing is compared only at the end.

  python scripts/run_hdc_regression.py --model r1 --seed 0 --factorized 1 --early-exit 1 --theta 64 --rows all --sim verilator --tag f1e1_t64
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tb.common import golden as G  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402
import sim_hdc as SIM  # noqa: E402

HQ = H.HQ
RESULTS = ROOT / "results" / "hdc"
REAL_ROWS: list[int] = []


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def pick_rows(spec: str, n_total: int, labels: np.ndarray, rng) -> list[int]:
    if spec == "all":
        return list(range(n_total))
    if spec == "real":
        return sorted(REAL_ROWS)
    if spec.startswith("first"):
        return list(range(int(spec[5:])))
    if spec.startswith("rand"):
        return sorted(rng.choice(n_total, int(spec[4:]), replace=False).tolist())
    return [int(v) for v in spec.split(",")]


def compare_sample(mdl, row, counts_row, thr, got, theta, exit_en, n_events, g=8, cols=160) -> dict:
    """Bit-exact comparison of one DUT sample with the references, timestep by timestep. Returns a record; 'first' is the first mismatch."""
    ref = H.reference_sample(mdl, row, theta, exit_en)
    tr = G.reference_trace(counts_row, mdl["W"], thr)
    n_exp = ref["t_exit"] + 1
    rec = dict(ok=True, first=None, n_ts=len(got["t"]), t_exit=ref["t_exit"], ref_pred=ref["pred"], ref_fired=ref["fired"])

    def bad(*what):
        if rec["ok"]:
            rec["ok"], rec["first"] = False, what

    if len(got["t"]) != n_exp or not np.array_equal(got["t"], np.arange(n_exp)):
        bad("timesteps", len(got["t"]), n_exp)
        return rec
    for name, a, b in (("spikes", tr.S[:n_exp], got["S"]), ("X", tr.X[:n_exp], got["X"]), ("V", tr.V[:n_exp], got["V"]), ("scores", ref["prefix"][:n_exp], got["scores"])):
        d = np.argwhere(a != b)
        if len(d):
            bad(name, int(d[0][0]), int(d[0][1]), int(a[tuple(d[0])]), int(b[tuple(d[0])]))
    t2 = np.array([[v[0], v[1], v[2]] for v in ref["top2"][:n_exp]])        # (index, top1, top2)
    for name, a, b in (("top1_idx", t2[:, 0], got["top1_idx"]), ("top1", t2[:, 1], got["top1"]), ("top2", t2[:, 2], got["top2"])):
        d = np.argwhere(a != b)
        if len(d):
            bad(name, int(d[0][0]), int(a[d[0][0]]), int(b[d[0][0]]))
    fire_ref = np.zeros(n_exp, np.int64)
    if ref["fired"] and exit_en:
        fire_ref[-1] = 1
    if not np.array_equal(fire_ref, got["fire"]):
        bad("fire", int(np.argwhere(fire_ref != got["fire"])[0][0]))
    if not np.array_equal(got["rows_gated"], got["S"].sum(axis=1)):
        bad("rows_gated", 0)
    e = got["end"]
    if e["pred"] != ref["pred"]:
        bad("pred", e["pred"], ref["pred"])
    if e["early"] != int(ref["fired"] and exit_en):
        bad("early", e["early"], int(ref["fired"]))
    if e["pred_tstep"] != ref["t_exit"]:
        bad("pred_tstep", e["pred_tstep"], ref["t_exit"])
    ev_ref = int(np.sum(G.EV.bin_sizes(n_events, G.T)[:n_exp]))
    if e["events_ingested"] != ev_ref:
        bad("events_ingested", e["events_ingested"], ev_ref)
    # 1E's criterion 7 for the timesteps that ran: the SNN access counters equal an independent estimate from the count vectors alone
    est = G.independent_access_estimate(counts_row, g)[:n_exp]
    st = got["stats"]
    for k, col in ((0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (7, 7)):
        if not np.array_equal(st[:, k], est[:, col]) and not (k == 5 and cols != 160):
            bad("access_estimate", k, int(np.argwhere(st[:, k] != est[:, col])[0][0]))
    if not np.array_equal(st[:, 6], st[:, 4] * (160 // cols)):
        bad("reads_issued", 6)
    if e["assert_cycles"] or e["hdc_assert_cycles"]:
        bad("assertions", e["assert_cycles"], e["hdc_assert_cycles"])
    if e["cycles_query"] != 5 * n_exp:
        bad("query_cycles", e["cycles_query"], 5 * n_exp)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="r1", choices=["base", "r1"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--factorized", type=int, default=1)
    ap.add_argument("--early-exit", type=int, default=1, help="EARLY_EXIT_EN: 1 builds the comparator + exit FSM, 0 does not (Phase 3)")
    ap.add_argument("--theta", type=int, default=HQ.THETA_NEVER, help="margin threshold (XNOR-score units) written to the threshold register")
    ap.add_argument("--exit-en", type=int, default=1, help="runtime enable written to CFG_EXIT_EN")
    ap.add_argument("--rows", default="all")
    ap.add_argument("--g", type=int, default=8)
    ap.add_argument("--cols", type=int, default=160, help="N_PARALLEL_COLS: 160 or 20")
    ap.add_argument("--sim", default="verilator", choices=["verilator", "icarus"])
    ap.add_argument("--gap", type=int, default=0)
    ap.add_argument("--order", default="auto", choices=["auto", "shuffle", "sorted"])
    ap.add_argument("--tag", default=None)
    ap.add_argument("--sim-seed", type=int, default=1)
    ap.add_argument("--chunks", type=int, default=1)
    ap.add_argument("--keep-job", action="store_true")
    args = ap.parse_args()

    t_all = time.time()
    tag = args.tag or f"{args.model}{args.seed}_f{args.factorized}_e{args.early_exit}_t{args.theta}_{args.sim}"
    mdl = H.load_model(args.model, args.seed)
    if args.factorized and mdl["a_bits"] is None:
        sys.exit("the factorized build needs the factorized (r1) model")
    rng = np.random.default_rng([args.sim_seed, args.seed, args.g])
    real, _ = G.real_streams("dvsgesture")
    real_by_row = {r: w for r, w, _ in real}
    REAL_ROWS[:] = list(real_by_row)
    rows = pick_rows(args.rows, len(mdl["labels"]), mdl["labels"], rng)
    samples, thr = [], []
    for r in rows:
        counts_row = mdl["counts"][r].astype(np.int64)
        if r in real_by_row and args.order == "auto":
            words = real_by_row[r]
        else:
            words = G.synth_events("dvsgesture", counts_row, rng, "sorted" if args.order == "sorted" else "shuffle")
        assert G.check_stream_reproduces_counts("dvsgesture", words, counts_row), f"stimulus for row {r} does not reproduce the golden counts"
        samples.append((words, counts_row))
        thr.append(mdl["thresh_int"][r])
    exe = SIM.build(args.sim, args.factorized, args.early_exit, args.g, args.cols)
    gap_seeds = [(args.sim_seed * 1000003 + int(r) * 7919 + args.seed) & 0x7FFFFFFF for r in rows]
    idx_chunks = [c for c in ([list(range(i, len(rows), args.chunks)) for i in range(args.chunks)]) if c]
    job = ROOT / "build" / "jobs_hdc" / tag
    runs = []
    for ci, idxs in enumerate(idx_chunks):
        jd = job / f"chunk{ci}"
        H.write_job(jd, mdl, bool(args.factorized), [samples[i] for i in idxs], [thr[i] for i in idxs], [args.theta] * len(idxs), [args.exit_en] * len(idxs), gap_mode=args.gap,
                    sim_seed=args.sim_seed, gap_seeds=[gap_seeds[i] for i in idxs])
        runs.append((jd, jd / "out.txt"))
    with concurrent.futures.ThreadPoolExecutor(len(runs)) as ex:
        rres = list(ex.map(lambda jo: SIM.run(args.sim, exe, jo[0], jo[1]), runs))
    r = dict(returncode=max(x["returncode"] for x in rres), wall_s=max(x["wall_s"] for x in rres), log="\n".join(x["log"][-1500:] for x in rres),
             assert_fails=sum(x["assert_fails"] for x in rres), fatal=any(x["fatal"] for x in rres))
    got = [None] * len(rows)
    for idxs, (jd, ot) in zip(idx_chunks, runs):
        part = H.parse_output(ot) if ot.exists() else []
        for local, i in enumerate(idxs):
            got[i] = part[local] if local < len(part) else None

    # canonical raw log: every TS / END line with the GLOBAL golden row as the sample id, sorted by (row, timestep) - byte-comparable between simulators and between builds
    canon = []
    for idxs, (jd, ot) in zip(idx_chunks, runs):
        if not ot.exists():
            continue
        for line in open(ot):
            f = line.split()
            if f and f[0] in ("TS", "END") and int(f[1]) < len(idxs):
                row = rows[idxs[int(f[1])]]
                key = (row, 0 if f[0] == "TS" else 1, int(f[2]) if f[0] == "TS" else 0)
                canon.append((key, " ".join([f[0], str(row)] + f[2:])))
    canon.sort(key=lambda kv: kv[0])
    RESULTS.mkdir(parents=True, exist_ok=True)
    with gzip.open(RESULTS / f"{tag}.out.txt.gz", "wt") as fh:
        fh.writelines(line + "\n" for _, line in canon)

    per_sample, mism = [], 0
    detail = []
    for i, rrow in enumerate(rows):
        gi = got[i]
        if gi is None or gi["end"] is None:
            per_sample.append(dict(row=int(rrow), ok=False, error="no output")); mism += 1; continue
        cmp_ = compare_sample(mdl, rrow, samples[i][1], thr[i], gi, args.theta, bool(args.exit_en) and bool(args.early_exit), len(samples[i][0]), args.g, args.cols)
        e = gi["end"]
        n = len(gi["t"])
        rec = dict(row=int(rrow), label=int(mdl["labels"][rrow]), ok=bool(cmp_["ok"]), first_mismatch=cmp_["first"], pred=e["pred"], correct=bool(e["pred"] == mdl["labels"][rrow]),
                   early=e["early"], exit_tstep=e["pred_tstep"], n_timesteps=n, n_events=len(samples[i][0]), events_ingested=e["events_ingested"], cycles_inf=e["cycles_inf"],
                   cycles_query=e["cycles_query"], stall_cycles=e["stall_cycles"], idle_cycles=e["idle_cycles"], reload_cycles=e["reload_cycles"],
                   mvm_and_other_cycles=e["cycles_inf"] - e["events_ingested"] - e["cycles_query"] - e["idle_cycles"],
                   group_reads_allcols=int(gi["stats"][:, 4].sum()), group_reads_issued=int(gi["stats"][:, 6].sum()), zero_groups=int(gi["stats"][:, 7].sum()), rows_gated_total=int(gi["rows_gated"].sum()),
                   raster_hash=hashlib.sha256(np.packbits(gi["S"].astype(np.uint8)).tobytes()).hexdigest()[:16])
        mism += (not rec["ok"])
        per_sample.append(rec)
        for t in range(n):
            detail.append(dict(sample=int(rrow), t=int(t), spikes=int("".join(map(str, gi["S"][t][::-1])), 2), scores=gi["scores"][t].tolist(), top1=int(gi["top1_idx"][t]), margin=int(gi["top1"][t] - gi["top2"][t]),
                               fire=int(gi["fire"][t])))
    acc = float(np.mean([p["correct"] for p in per_sample if "correct" in p])) if per_sample else 0.0
    ok_s = [p for p in per_sample if p.get("ok")]
    summary = dict(tag=tag, model=args.model, seed=args.seed, factorized=args.factorized, early_exit_en=args.early_exit, theta=args.theta, exit_en=args.exit_en, g=args.g, n_parallel_cols=args.cols, simulator=args.sim,
                   gap_mode=args.gap, samples=len(rows), mismatching_samples=int(mism), accuracy=acc, mean_exit_tstep=float(np.mean([p["n_timesteps"] for p in ok_s])) if ok_s else None,
                   mean_cycles_inf=float(np.mean([p["cycles_inf"] for p in ok_s])) if ok_s else None, mean_events_ingested=float(np.mean([p["events_ingested"] for p in ok_s])) if ok_s else None,
                   assert_fail_messages=r["assert_fails"], sim_returncode=r["returncode"], sim_fatal=r["fatal"], sim_wall_s=round(r["wall_s"], 2), total_wall_s=round(time.time() - t_all, 2),
                   git_commit=git_commit(), tools=SIM.tool_versions() if hasattr(SIM, "tool_versions") else {})
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{tag}.json").write_text(json.dumps(dict(summary=summary, samples=per_sample), indent=1))
    with gzip.open(RESULTS / f"{tag}.timesteps.jsonl.gz", "wt") as fh:
        for d in detail:
            fh.write(json.dumps(d) + "\n")
    status = "PASS" if (mism == 0 and r["returncode"] == 0 and not r["fatal"] and r["assert_fails"] == 0) else "FAIL"
    print(f"[{status}] {tag}: {len(rows)} samples, {mism} mismatching, acc {acc * 100:.2f}%, mean exit timestep {summary['mean_exit_tstep']}, {r['assert_fails']} assertion messages, sim {r['wall_s']:.1f}s")
    if status == "FAIL":
        for b in [p for p in per_sample if not p.get("ok", False)][:3]:
            print("   first failing:", {k: b.get(k) for k in ("row", "first_mismatch", "error")})
        print(r["log"][-1500:])
    if not args.keep_job:
        import shutil
        shutil.rmtree(job, ignore_errors=True)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
