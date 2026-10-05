#!/usr/bin/env python3
"""Run a slice of the 1E regression: build stimulus (Python, golden model), simulate (Verilator or Icarus), compare EVERY timestep's
spikes, X and V against int_model, and compare the access counters against an independent estimate from the count vectors.

Usage example:
  python scripts/run_regression.py --dataset dvsgesture --seed 0 --rows all --g 8 --sim verilator --tag dvs_s0_g8
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
import sim as SIM  # noqa: E402

RESULTS = ROOT / "results" / "regression"
REAL_ROWS: list[int] = []


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def pick_rows(spec: str, n_total: int, labels: np.ndarray, rng) -> list[int]:
    if spec == "all":
        return list(range(n_total))
    if spec == "per_class":      # one sample of every class
        return [int(np.flatnonzero(labels == c)[0]) for c in sorted(set(labels.tolist()))]
    if spec == "real":           # the samples whose raw AER stream Phase 0 exported
        return sorted(REAL_ROWS)
    if spec.startswith("first"):
        return list(range(int(spec[5:])))
    if spec.startswith("rand"):
        return sorted(rng.choice(n_total, int(spec[4:]), replace=False).tolist())
    return [int(v) for v in spec.split(",")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="dvsgesture", choices=["dvsgesture", "nmnist"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rows", default="all")
    ap.add_argument("--g", type=int, default=8)
    ap.add_argument("--cols", type=int, default=160, help="N_PARALLEL_COLS: 160 (all columns per read) or 20 (one weight plane per read)")
    ap.add_argument("--no-skip", action="store_true")
    ap.add_argument("--sim", default="verilator", choices=["verilator", "icarus"])
    ap.add_argument("--gap", type=int, default=0, help="0: back-to-back events, 1: random idle gaps")
    ap.add_argument("--order", default="auto", choices=["auto", "shuffle", "sorted"], help="event order inside a timestep for synthesised streams; auto = real stream when exported else shuffled")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--sim-seed", type=int, default=1)
    ap.add_argument("--chunks", type=int, default=1, help="split the samples over N parallel simulator processes (results identical: gap seeds are per sample)")
    ap.add_argument("--keep-job", action="store_true")
    args = ap.parse_args()

    t_all = time.time()
    tag = args.tag or f"{args.dataset}_s{args.seed}_g{args.g}_c{args.cols}_{args.sim}"
    man, c, s, W = G.load_dataset(args.dataset, args.seed)
    rng = np.random.default_rng([args.sim_seed, args.seed, args.g])
    real, _ = G.real_streams(args.dataset)
    real_by_row = {r: w for r, w, _ in real}
    REAL_ROWS[:] = list(real_by_row)
    rows = pick_rows(args.rows, len(c["labels"]), c["labels"], rng)

    samples, thr, used_real = [], [], []
    for r in rows:
        counts_row = c["counts"][r].astype(np.int64)
        if r in real_by_row and args.order == "auto":
            words, is_real = real_by_row[r], True
        else:
            words, is_real = G.synth_events(args.dataset, counts_row, rng, "sorted" if args.order == "sorted" else "shuffle"), False
        assert G.check_stream_reproduces_counts(args.dataset, words, counts_row), f"stimulus for row {r} does not reproduce the golden counts"
        samples.append((words, counts_row)); used_real.append(is_real)
        thr.append(s["thresh_int"][r])

    exe = SIM.build(args.sim, args.g, args.cols, 0 if args.no_skip else 1)
    gap_seeds = [(args.sim_seed * 1000003 + int(r) * 7919 + args.seed) & 0x7FFFFFFF for r in rows]
    idx_chunks = [list(range(i, len(rows), args.chunks)) for i in range(args.chunks)]
    idx_chunks = [c_ for c_ in idx_chunks if c_]
    job = ROOT / "build" / "jobs" / tag
    runs = []
    for ci, idxs in enumerate(idx_chunks):
        jd = job / f"chunk{ci}"
        G.write_job(jd, args.dataset, args.seed, [samples[i] for i in idxs], [thr[i] for i in idxs], gap_mode=args.gap, sim_seed=args.sim_seed,
                    gap_seeds=[gap_seeds[i] for i in idxs])
        runs.append((jd, jd / "out.txt"))
    with concurrent.futures.ThreadPoolExecutor(len(runs)) as ex:
        rres = list(ex.map(lambda jo: SIM.run(args.sim, exe, jo[0], jo[1]), runs))
    r = dict(returncode=max(x["returncode"] for x in rres), wall_s=max(x["wall_s"] for x in rres), log="\n".join(x["log"][-1500:] for x in rres),
             assert_fails=sum(x["assert_fails"] for x in rres), fatal=any(x["fatal"] for x in rres))
    got = [None] * len(rows)
    for idxs, (jd, ot) in zip(idx_chunks, runs):
        part = G.parse_output(ot) if ot.exists() else []
        for local, i in enumerate(idxs):
            got[i] = part[local] if local < len(part) else None

    class_hv = np.load(G.P0 / "artifacts" / "phase0" / (f"class_hv_nmnist{args.seed}.npy" if args.dataset == "nmnist" else f"class_hv_seed{args.seed}.npy"))
    ng = -(-G.N_ADDR // args.g)
    per_sample, mism, access_bad = [], 0, 0
    detail = []
    for i, rrow in enumerate(rows):
        gi = got[i]
        if gi is None or gi["end"] is None:
            per_sample.append(dict(row=rrow, ok=False, error="no output")); mism += 1; continue
        cmpres = G.compare_sample(samples[i][1], W, thr[i], gi)
        st = gi["stats"]
        est = G.independent_access_estimate(samples[i][1], args.g)
        # stat columns: events, active, rows_skipped, rows_read, allcols, plane, issued, zero_groups, fwd, cycles, cycles_ingest
        exp_cols = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 7: 7}
        access_ok = all(np.array_equal(st[:, k], est[:, e]) for k, e in exp_cols.items()) if not args.no_skip else True
        if args.no_skip:
            access_ok = np.array_equal(st[:, 0], est[:, 0]) and np.array_equal(st[:, 1], est[:, 1])
        issued_expected = st[:, 4] * (G.N_NEURON * 8 // args.cols if args.cols else 1)
        access_ok = bool(access_ok and np.array_equal(st[:, 6], issued_expected))
        pred = int(G.IM.predict(gi["S"], class_hv)[0]) if cmpres["ok"] else -1
        golden_pred = int(s["pred"][rrow])
        raster_hash = hashlib.sha256(np.packbits(gi["S"].astype(np.uint8)).tobytes()).hexdigest()[:16]
        end = gi["end"]
        rec = dict(row=int(rrow), label=int(c["labels"][rrow]), real_stream=bool(used_real[i]), n_events=int(end["events"]), ok=bool(cmpres["ok"] and end["assert_cycles"] == 0),
                   first_mismatch=cmpres["first"], pred=pred, golden_pred=golden_pred, pred_match=bool(pred == golden_pred), raster_hash=raster_hash,
                   cycles=int(end["cycles"]), stall_cycles=int(end["stall_cycles"]), idle_cycles=int(end["idle_cycles"]), assert_cycles=int(end["assert_cycles"]),
                   group_reads_allcols=int(st[:, 4].sum()), group_reads_plane=int(st[:, 5].sum()), group_reads_issued=int(st[:, 6].sum()),
                   rows_skipped=int(st[:, 2].sum()), rows_read=int(st[:, 3].sum()), active_addrs_total=int(st[:, 1].sum()), zero_groups=int(st[:, 7].sum()),
                   fwd_events=int(st[:, 8].sum()), cycles_ingest=int(st[:, 10].sum()), access_estimate_match=bool(access_ok))
        mism += (not rec["ok"]); access_bad += (not access_ok)
        per_sample.append(rec)
        for t in range(len(gi["t"])):
            detail.append(dict(sample=int(rrow), t=int(t), spikes=int("".join(map(str, gi["S"][t][::-1])), 2), X=gi["X"][t].tolist(), V=gi["V"][t].tolist(),
                               stats=dict(zip(G.STAT_NAMES, st[t].tolist())), golden_match=bool(cmpres["ok"])))
    summary = dict(tag=tag, dataset=args.dataset, seed=args.seed, g=args.g, n_parallel_cols=args.cols, plane_skip=not args.no_skip, simulator=args.sim, gap_mode=args.gap,
                   order=args.order, samples=len(rows), mismatching_samples=int(mism), access_estimate_mismatches=int(access_bad),
                   assert_fail_messages=r["assert_fails"], sim_returncode=r["returncode"], sim_fatal=r["fatal"], sim_wall_s=round(r["wall_s"], 2),
                   total_wall_s=round(time.time() - t_all, 2), git_commit=git_commit(), tools=SIM.tool_versions(),
                   parameters=dict(ROWS_PER_GROUP=args.g, N_PARALLEL_COLS=args.cols, PLANE_SKIP_EN=int(not args.no_skip), W_COUNT=11, W_X=21, W_V=26, W_THRESH=15),
                   golden_vectors_sha256=man.get("sha256"))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{tag}.json").write_text(json.dumps(dict(summary=summary, samples=per_sample), indent=1))
    with gzip.open(RESULTS / f"{tag}.timesteps.jsonl.gz", "wt") as fh:
        for d in detail:
            fh.write(json.dumps(d) + "\n")
    status = "PASS" if (mism == 0 and r["returncode"] == 0 and not r["fatal"] and r["assert_fails"] == 0 and access_bad == 0) else "FAIL"
    print(f"[{status}] {tag}: {len(rows)} samples, {mism} mismatching, {access_bad} access-estimate mismatches, {r['assert_fails']} assertion messages, sim {r['wall_s']:.1f}s")
    if status == "FAIL":
        bad = [p for p in per_sample if not p.get("ok", False)][:3]
        for b in bad:
            print("   first failing:", {k: b.get(k) for k in ("row", "first_mismatch", "assert_cycles", "error")})
        print(r["log"][-1500:])
    if not args.keep_job:
        import shutil
        shutil.rmtree(job, ignore_errors=True)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
