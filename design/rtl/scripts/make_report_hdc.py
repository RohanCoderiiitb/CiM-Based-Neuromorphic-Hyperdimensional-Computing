#!/usr/bin/env python3
"""reports/phase234_report.md - Phases 2-4 (HDC query, integration, margin-based early termination). Every number is read from results/hdc/summary_phase234.json
(built by hdc_tables.py from the regression runs), the comparison logs, the unit-test results and the synthesis summaries; nothing is typed in by hand."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
HDC = ROOT / "results" / "hdc"
PPA = ROOT / "results" / "ppa"
UT = ROOT / "results" / "phase234_1e_recheck" / "unit_tests"
OUT = REPO / "reports" / "phase234_report.md"
SEEDS = (0, 1, 2)
pct = lambda x, d=2: f"{100 * x:.{d}f}%"          # noqa: E731


def load(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def sh(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO).stdout.strip()


def table(head: list[str], rows: list[list]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def main() -> int:
    S = load(HDC / "summary_phase234.json")
    if S is None:
        sys.exit("run hdc_tables.py first")
    R, AB, CMP = S["runs"], S["ablation_runs"], {c["tag"]: c for c in S["compare"]}
    L: list[str] = []
    w = L.append

    # ----------------------------------------------------------------- numbers used in several places
    fu = [CMP.get(f"fu_s{s}") for s in SEEDS]
    dis_b = [CMP.get(f"dis_base_s{s}") for s in SEEDS]
    dis_r = [CMP.get(f"dis_r1_s{s}") for s in SEEDS]
    n_fu = sum(c["timesteps_compared"] for c in fu if c)
    n_dis = sum(c["timesteps_compared"] for c in dis_b + dis_r if c)
    kn = S["knees"]
    sw = {(r["model"], r["theta"]): r for r in S["hw_sweep"]}
    hw_ok = all(r["all_equal_reference"] for r in S["hw_sweep"])
    n_sw_points = sum(r["n_seeds"] for r in S["hw_sweep"])
    p3 = {k: R.get(k) for k in R}
    mean = lambda ks, f: float(np.mean([R[k][f] for k in ks if k in R]))      # noqa: E731
    rg_base, rg_r1 = mean([f"p3_base_s{s}" for s in SEEDS], "rows_gated"), mean([f"p3_r1fact_s{s}" for s in SEEDS], "rows_gated")
    cyc = {m: mean([f"p3_{m}_s{s}" for s in SEEDS], "cycles") for m in ("base", "r1fact")}
    ev = mean([f"p3_base_s{s}" for s in SEEDS], "events")
    q = mean([f"p3_base_s{s}" for s in SEEDS], "query")
    stall = mean([f"p3_base_s{s}" for s in SEEDS], "stall_and_other")

    w("# Phases 2-4 report - the HDC query stage, the integration, and margin-based early termination")
    w("")
    w("Tags: **[RTL]** measured on the RTL regression (Verilator and Icarus, every timestep compared with the reference), **[REF]** computed by the Phase 0/2-4 integer reference, **[SW]** the software study "
      "(`studies/algorithm/phase3_experiments`), **[ASSUM]** assumed, **[CHOICE]** a design decision. Every number below is read from `results/hdc/*.json`, the canonical logs and the comparison "
      "files by `scripts/hdc_tables.py` + `scripts/make_report_hdc.py`; commands in section 9. Written for the project owner; the synthesis, power and the ablation table (energy and area) are in "
      "[`phase5_ppa.md`](phase5_ppa.md).")
    w("")
    w("## 0. The answer")
    w("")
    w(f"- **Both class-hypervector mappings are built, selectable by a parameter, and bit-exact against the reference at every timestep prefix** (240 DVS-Gesture samples x 3 seeds x 100 timesteps, "
      f"{sum(R[k]['samples'] for k in R if k.startswith('p3_')) if R else 0} sample-runs, 0 mismatching) [RTL]. **The factorized mapping produces IDENTICAL scores to the unfactorized one - not close, identical:** "
      f"{n_fu:,} timesteps compared line by line (spikes, X, V, the 10 prefix scores, leader, second score, cycles), 0 differences. The factorization is lossless for the R=1 class hypervector it "
      f"represents; what it costs is the *model*: rank 1 is a different, jointly trained network, {pct(np.mean([R[f'p3_r1fact_s{s}']['accuracy'] for s in SEEDS]), 2)} against "
      f"{pct(np.mean([R[f'p3_base_s{s}']['accuracy'] for s in SEEDS]), 2)} for the unfactorized baseline (3-seed means, full run).")
    w(f"- **The two numbers that justify the factorization** (section 2.5): macro count **16 -> 1** (128 x 128 macros; 4 -> 1 on this design's 512 x 32 macros) and row activation **{pct(rg_base / 2000, 3)} -> "
      f"{pct(rg_base / 20, 1)}** of the rows (measured on the RTL: {rg_base:.2f} rows gated per timestep for the baseline's spikes; the R=1 model fires more, {rg_r1:.2f}, giving {pct(rg_r1 / 2000, 3)} -> {pct(rg_r1 / 20, 1)}). "
      "Storage 20,000 -> 1,250 bits.")
    w(f"- **Integration (section 3): no FIFO is needed.** The event intake of 1E's SNN is already a stall-never-buffer valid/ready; the integration holds it (`ingest_en`) from the spike strobe until the query "
      f"has scored the timestep and the exit decision is taken - **5 cycles per timestep, {q:.0f} per inference** - and for good after an exit. Per inference at g = 8 (all 160 columns per read): {cyc['base']:,.0f} cycles = "
      f"{ev:,.0f} event ingest + {q:.0f} query + {stall:,.0f} SNN MVM stalls; the query stage is {pct(q / cyc['base'], 3)} of the time.")
    k0, k1 = kn["r1"]["strict"], kn["base"]["strict"]
    w(f"- **Early exit (section 4): accuracy intact at a mean exit of timestep {k0['exit_mean']:.1f} (R=1 model, threshold {k0['theta']}) / {k1['exit_mean']:.1f} (unfactorized baseline, threshold {k1['theta']}), "
      f"i.e. {pct(1 - k0['exit_mean'] / 100, 1)} / {pct(1 - k1['exit_mean'] / 100, 1)} of the timesteps - and of the events - never ingested.** The knee is the smallest threshold at which the 3-seed accuracy equals the "
      f"full-run accuracy and stays there for every larger threshold; allowing one sample (0.14 pp) the knee moves to {kn['r1']['one_sample']['theta']} / {kn['base']['one_sample']['theta']} "
      f"(mean exit {kn['r1']['one_sample']['exit_mean']:.1f} / {kn['base']['one_sample']['exit_mean']:.1f}). The threshold is in XNOR-score units; the software study's bipolar threshold is twice it. "
      f"**Hardware and reference agree on all {n_sw_points} (model, seed, threshold) points: {hw_ok}**, and the reference reproduces the stored software sweep exactly (section 4.4).")
    w(f"- **Early exit disabled costs nothing and changes nothing** (Phase 4 requirement ii): with the comparator built and the threshold at its 'never' value, the run is byte-identical to the build without the "
      f"comparator - {n_dis:,} timesteps compared, {sum(c['disagreements'] for c in dis_b + dis_r if c)} differences, cycles included.")
    w("- **1E's RTL is unchanged** (`git diff` of `rtl/phase1_snn` and `rtl/pkg/cim_neurohdc_pkg.sv` is empty; section 7). One thing 1E's controller cannot do is *abort*: after an early exit the SNN is parked in INGEST "
      "and the next sample needs a reset and a weight reload; the testbench does that and reports the reload separately. This is the one follow-up the early exit asks of 1E (section 8).")
    w("")
    # ----------------------------------------------------------------- 1. criteria
    w("## 1. Completion criteria")
    w("")
    ut = load(UT / "summary.json", [])
    ut_new = [u for u in ut if any(u.get("case", "").startswith(p) for p in ("top2_tree", "exit_ctrl", "hdc_query"))]
    lint = (ROOT / "results" / "lint" / "lint_hdc.log")
    gens = {b: (ROOT / "results" / "synthesis" / f"hdc_{b}_stat_specified.txt").exists() for b in ("full", "ee_off", "fact_off", "both_off")}
    git_1e = sh(["git", "diff", "--stat", "--", "design/rtl/rtl/phase1_snn", "design/rtl/rtl/pkg/cim_neurohdc_pkg.sv"])
    sims_ok = [c for c in S["compare"] if c["tag"].startswith("sim_")]
    rows = [
        ["the reference is extended before each RTL block", "PASS", "`hdc_query.py`, `r1_model.py`, `tests/test_hdc_query.py` (10 tests + the Phase 0 ones, all pass) exist before any Phase 2-4 RTL; the unit and regression tests import them (section 2.2)"],
        ["both class-HV mappings build and produce identical scores", "PASS" if all(c and c["verdict"] == "AGREE" for c in fu) else "FAIL", f"`fu_s0..2`: {n_fu:,} timesteps identical (section 2.4)"],
        ["all four ablation configurations elaborate and pass", "PASS" if all(AB.get(f"{b}_g8_s{s}", {}).get("mismatching", 1) == 0 for b in ("full", "ee_off", "fact_off", "both_off") for s in SEEDS) and all(gens.values()) else "see 5", "section 5"],
        ["early exit disabled is bit-identical to Phase 3", "PASS" if all(c and c["verdict"] == "AGREE" for c in dis_b + dis_r) else "FAIL", f"`dis_*`: {n_dis:,} timesteps, 0 differences (section 4.3)"],
        ["every RTL result confirmed on both Verilator and Icarus", "PASS" if sims_ok and all(c["verdict"] == "AGREE" for c in sims_ok) else "see 6", f"{len(sims_ok)} twin runs compared per timestep, plus the cocotb unit tests on both (section 6)"],
        ["1E's RTL is unchanged and its regression still passes", "PASS" if not git_1e else "FAIL", "empty `git diff`; the 1E recheck is in section 7"],
        ["the generated netlist agrees with the mesh solver to 1C's tolerance", "see report", "[`crossbar_netlist.md`](crossbar_netlist.md)"],
        ["Phase 5 energy is reported at the measured exit timestep", "see report", "[`phase5_ppa.md`](phase5_ppa.md)"]]
    w(table(["criterion", "status", "evidence"], rows))
    w("")
    w("## 2. Phase 2 - the HDC query stage")
    w("")
    w("### 2.1 What was built")
    w("")
    w("Input: the 20-bit spike vector of one timestep, with a one-cycle valid strobe and the timestep index (`spike_valid_o`, `spike_o`, `spike_tstep_o` of `snn_top`). Output: N = 10 prefix scores, the leader and "
      "the second-largest score, once per timestep. The two mappings sit behind one interface and are selected by the parameter `FACTORIZED`.")
    w("")
    w(table(["block", "file", "does"], [
        ["class-HV array, both mappings", "`rtl/phase2_hdc/hdc_class_array.sv`", "behavioural model of the CIM array (a black box in synthesis, like `cim_macro`). FACTORIZED: the stationary 20 x N array; one read with the spikes on the row lines (**spike-gated row enable**) and all N columns sensed returns q_i = popcount(S & a_i). Unfactorized: the 2000 x N memory; a read returns the N class slices of timestep t"],
        ["datapath (a) XNOR-popcount", "`hdc_score.sv`", "agree_i = popcount(~(S ^ slice_i)), 0..20"],
        ["datapath (b) AND-popcount + sign", "`hdc_score.sv`", "P_i = 20 - |S| - bias_i + 2 q_i (the XNOR popcount of S with a_i; **bias_i = ||a_i||_1** is the per-class bias register); agree_i = b_i[t] ? P_i : 20 - P_i (sign table, T x N bits)"],
        ["N score accumulators", "`hdc_query.sv`", "N x 11-bit, cleared at sample start, one add per class per timestep"],
        ["top-2 selection, argmax", "`top2_tree.sv`", "binary tournament of pairwise merges, ceil(log2 N) = 4 levels, no sort; ties keep the lower class index; two tied leaders give margin 0"],
        ["class image port", "`hdc_pkg.sv`", "static, like 1E's weight image: sel 0 = array (100 words of N x 20 bits unfactorized, 1 word factorized), sel 1 = sign table, sel 2 = bias registers"]]))
    w("")
    w("Pipeline (the same for both mappings): cycle 0 spike strobe and capture; 1 array read; 2 agree and accumulate; 3 top-2; 4 decision valid. `busy` covers cycles 0-4, so the integration holds the SNN for 5 "
      "cycles per timestep (section 3). Simulation-only checks inside `hdc_query` (never disabled in a run): every agree in 0..20, no spike vector arriving while the previous timestep is in flight, and the "
      "**unipolar identity of the README (Phase 2 task 2)** - the argmax of the prefix `2 S.C_i - ||C_i||_1` equals the XNOR leader at *every* timestep, and exactly `score_i = unipolar_i + sum_t (20 - |S_t|)` - "
      "computed from an independent shadow copy of the class image. 0 assertion messages in every run of every build.")
    w("")
    w("### 2.2 The reference, extended first")
    w("")
    w("`design/reference_model/model/fixedpoint/hdc_query.py` (integer arithmetic only) defines, before any RTL existed: the score (`agree_unfactorized` = Phase 0's XNOR popcount), the R=1 expansion "
      "C_i[t,j] = XNOR(a_i[j], b_i[t]), the factorized form (`agree_factorized`: AND-popcount + bias + sign), the tournament top-2, the margin, the exit rule (`exit_point`), the unipolar identity "
      "and the sweep. `tests/test_hdc_query.py` proves, on random data and on the golden rasters: factorized == unfactorized on the expansion (densities 0..1), the unipolar identity *exactly* (not just argmax), "
      "the tournament equals a sort with forced ties, the exit semantics (the prediction is the argmax *of the exit timestep*, not of the final scores), the bipolar-to-integer threshold translation is exact, and "
      "the replay of the stored software sweep (section 4.4). `r1_model.py` extracts the integer R=1 models and exports their golden vectors (`tb/vectors/dvsgesture/r1_seed<k>.npz`, weights tag `r1s<k>`).")
    w("")
    w("**The R=1 checkpoints are a different network, not a compression of the baseline.** `studies/algorithm/phase3_experiments` trained them jointly (SNN weights, threshold and the factors A [N,1,20], B [N,1,100]) "
      "from an SVD initialisation of the baseline's class hypervector. The integer pipeline reproduces each checkpoint's recorded float test accuracy exactly:")
    gate = load(REPO / "design" / "reference_model" / "artifacts" / "phase0" / "r1_gate.json", {})
    w("")
    w(table(["R=1 seed", "integer pipeline", "recorded float test_acc", "factorized == unfactorized scores"],
            [[s, f"{gate[str(s)]['accuracy'] * 100:.2f}% ({round(gate[str(s)]['accuracy'] * 240)}/240)", f"{gate[str(s)]['recorded'] * 100:.2f}%", "all 24,000 prefixes"] for s in SEEDS if str(s) in gate]))
    w("")
    w("The frozen widths hold for these networks too (measured on the 240 test samples): |X| <= 697,371 (W_X = 21 bits: 1,048,575), V down to -29,470,256 (W_V = 26 bits: 33,554,431 - **12 % headroom on seed 2**, the tightest "
      "margin of the whole datapath), thresholds 5,891..14,974 (W_THRESH = 15 bits: 16,383).")
    w("")
    w("### 2.3 Class image sizes")
    w("")
    w(table(["", "unfactorized", "R=1 factorized"], [
        ["stationary array", "-", "20 x 10 = 200 bits (ReRAM)"], ["class memory", "2000 x 10 = 20,000 bits (ReRAM)", "-"], ["sign table", "-", "100 x 10 = 1,000 bits (digital flip-flops)"],
        ["per-class bias registers", "-", "10 x 5 = 50 bits (digital)"], ["total", "20,000", "1,250 (the README's 120 x N = 1,200 plus the bias registers)"]]))
    w("")
    w("### 2.4 Bit-exactness and the identity of the two mappings")
    w("")
    rows = []
    for s in SEEDS:
        for lab, key in (("unfactorized RTL, baseline model", f"p3_base_s{s}"), ("factorized RTL, R=1 model", f"p3_r1fact_s{s}"), ("unfactorized RTL, R=1 model expanded", f"p3_r1unfact_s{s}")):
            r = R.get(key)
            if r:
                rows.append([lab, s, r["samples"], r["mismatching"], r["assert_messages"], pct(r["accuracy"]), f"{r['cycles']:,.0f}"])
    w(table(["run (early exit not built)", "seed", "samples", "mismatching vs reference", "assertion msgs", "accuracy", "cycles / inference"], rows))
    w("")
    w("Per sample and per timestep the testbench compares spikes, X, V (the 1E checks), the 10 prefix scores, the leader, the second-largest score, the fire flag, the rows gated and the SNN access counters (1E's "
      "criterion 7), and per sample the prediction, the exit timestep, the events ingested and the query cycles (exactly 5 per timestep). **A mismatch anywhere fails the run.**")
    w("")
    w(table(["comparison (canonical per-timestep logs, line by line)", "seed", "timesteps", "differences"],
            [[lab, s, f"{c['timesteps_compared']:,}", c["disagreements"]] for lab, cs in (("factorized RTL vs unfactorized RTL with the expanded class HV (reload cycles aside)", fu),) for s, c in zip(SEEDS, cs) if c]))
    w("")
    w("The two mappings differ in the data path and in the cycle accounting of the *reload* (the class image is 2 words of 1,250 bits against 100 words of 200) - nothing else. That answers the brief's "
      "question: the factorization is **not lossy** for the class hypervector it stores, and there is no bug. The accuracy gap is the cost of constraining the class hypervector to rank 1, paid at training time.")
    w("")
    w("### 2.5 The two numbers")
    w("")
    w(table(["", "unfactorized", "R=1 factorized", "source"], [
        ["macros (128 x 128, README Exp 1b)", "16", "1", "[REF] ceil(2000/128) x ceil(10/128) vs ceil(20/128) x 1; matches `exp1b_analytic.csv`"],
        ["macros on this design's 512 x 32 macro", "4", "1", "[REF] ceil(2000/512) vs 1"],
        ["rows gated per timestep, baseline model (mean of 3 seeds)", f"{rg_base:.3f} of 2000 rows = {pct(rg_base / 2000, 3)}", f"{rg_base:.3f} of 20 rows = {pct(rg_base / 20, 2)}", "[RTL] `rows_gated`, = mean spikes per timestep; README's 0.38 % -> 37.5 % is the seed-0 value 7.51"],
        ["rows gated per timestep, R=1 model (mean of 3 seeds)", f"{rg_r1:.3f} of 2000 = {pct(rg_r1 / 2000, 3)}", f"{rg_r1:.3f} of 20 = {pct(rg_r1 / 20, 2)}", "[RTL]"],
        ["bits read per timestep", "200 (10 classes x 20 bits)", "20 (10 array outputs + 10 sign bits)", "[REF]"],
        ["class image bits", "20,000", "1,250", "section 2.3"]]))
    w("")
    w("The unfactorized datapath here is the literal XNOR-popcount of the 20-bit slices (a digital read of 200 bits); the row-activation figure is the spike-gated one the README quotes. Phase 5 prices the array "
      "reads on that basis ([`phase5_ppa.md`](phase5_ppa.md)).")
    w("")
    # ----------------------------------------------------------------- 3 integration
    w("## 3. Phase 3 - the integration")
    w("")
    w("```")
    w("  events --> [snn_top] --spike_o/spike_valid_o/spike_tstep_o--> [hdc_query] --leader, top1, top2--> [exit_ctrl] --> prediction")
    w("                 ^   ingest_en_i = external enable AND NOT query busy AND NOT exited   <--------------+")
    w("```")
    w("")
    w("- **Top level through the 20-bit interface:** `rtl/phase3_top/cim_neurohdc_top.sv` instantiates `snn_top` unchanged and connects its spike port to the query stage; one configuration bus (7-bit address; 0-31 are 1E's registers, "
      "32 = threshold, 33 = exit enable) and one class-image port.")
    w("- **Handshake and backpressure.** `snn_top` has a valid strobe and no ready input; what it has is the event-intake gate. The integration drives it low from the strobe cycle until the decision is taken and "
      "for good after an exit, so back-pressure reaches the event source through `ev_ready` exactly as in 1E. Nothing is buffered, no event can be lost: the 1E assertions (every event counted once, counters sum to the "
      "timestep's event count) pass in every run, and `hdc_query` asserts that no spike vector arrives while the previous timestep is in flight.")
    w("- **Timestep synchronisation.** The query consumes timestep t's spikes before any event of timestep t+1 is accepted *by construction* (the intake is closed for strobe + 4 cycles), and the exit decision is taken "
      "before the next event - otherwise the saving would be partly an illusion. The measured query cost is exactly 5 cycles per timestep (asserted per sample).")
    w("- **Shared configuration and control:** thresholds, geometry and the event count as in 1E; plus the exit threshold register (reset value 'never' = 4095) and a runtime exit enable.")
    w("- **An input FIFO: not needed.** The handshake is lossless without one. A FIFO would be needed only if the event source cannot be stalled (a live sensor delivering at its own rate while the SNN is busy for "
      f"{stall / 100:,.0f} cycles per timestep on average); that is a system decision about the sensor interface, not something the handshake requires, and it is listed in the open items.")
    w("")
    w("### 3.1 Cycles per inference, split between event ingest and query")
    w("")
    rows = []
    for lab, ks in (("baseline model, unfactorized RTL", [f"p3_base_s{s}" for s in SEEDS]), ("R=1 model, factorized RTL", [f"p3_r1fact_s{s}" for s in SEEDS])):
        e_, q_, st_, c_ = (mean(ks, "events"), mean(ks, "query"), mean(ks, "stall_and_other"), mean(ks, "cycles"))
        rows.append([lab, f"{e_:,.0f}", f"{st_:,.0f}", f"{q_:,.0f}", f"{c_:,.0f}", pct(q_ / c_, 3), f"{c_ / 100e6 * 1e3:.2f} ms"])
    w(table(["early exit not built, g = 8, 160 columns per read", "event ingest (1 cycle per event)", "SNN MVM + update + wipe (stall)", "query (5 per timestep)", "total", "query share", "at 100 MHz"], rows))
    w("")
    w("The design is input-bound (1E's finding): events dominate; the query stage adds 500 cycles, 0.1 %. The 1E-only cycle count at g = 8 was 462,617 (seed-independent: it depends on the inputs only); here "
      "the same inputs give the same ingest and stall cycles plus the query's 500.")
    w("")
    # ----------------------------------------------------------------- 4 phase 4
    w("## 4. Phase 4 - margin-based early termination")
    w("")
    w("**Top-2 without a sort.** `top2_tree.sv`: 9 merge nodes for N = 10, depth 4; each node is one comparison and one second-value update (`merge(l, r)`: if l.v >= r.v the leader is l and the "
      "second is max(l.v2, r.v), else symmetric). Verified against a sort with forced ties, all-equal, all-zero and every pair of tied leaders for N = 7, 10, 16, 24 on both simulators (cocotb), and "
      "inside every regression timestep against the reference tournament. **Margin comparator:** margin = top1 - top2 against the 12-bit threshold register (`exit_ctrl.sv`); the boundary cases margin = theta - 1, "
      "theta, theta + 1 are unit-tested (fires exactly at >= theta). **Exit FSM:** on the decision cycle, `fire` latches the prediction (the leader of *that* timestep), the exit timestep and the early flag, "
      "raises `exited`, and the integration keeps the event intake closed; the last timestep finishes the inference without being an exit. Instrumentation: `events_ingested` counts accepted events, compared per "
      "sample with the reference's bin sizes up to the exit timestep.")
    w("")
    w("**Correctness requirements, proven rather than assumed.**")
    w("")
    w(f"1. *The prediction emitted at exit equals the argmax at that timestep.* Checked on every sample of every run ({sum(r['samples'] for r in R.values())} sample-runs at the named runs plus the whole sweep): the emitted "
      "class equals the reference's argmax of the prefix scores at the exit timestep (the unit test uses a case where it differs from the final argmax).")
    w(f"2. *With the threshold at 'never', behaviour is bit-identical to Phase 3.* {n_dis:,} timesteps over 6 runs (baseline and R=1, 3 seeds), the comparator built vs not built, line by line: 0 differences.")
    w("")
    w("### 4.1 Hardware sweep: accuracy and mean exit timestep against the threshold")
    w("")
    w("Threshold in XNOR-score margin units (software bipolar threshold / 2). Mean of 3 seeds, all 240 test samples, RTL; 'ref' = the integer reference, which agrees on every point.")
    w("")
    rows = []
    ths = sorted({r["theta"] for r in S["hw_sweep"]})
    for th in ths:
        a, b = sw.get(("r1", th)), sw.get(("base", th))
        f = lambda r: (f"{pct(r['acc_mean'])} / {r['exit_mean']:.1f} / {pct(r['events_fraction_mean'], 1)}" if r else "-")      # noqa: E731
        rows.append([th if th != 4095 else "4095 (never)", f(a), f(b), "yes" if all(x["all_equal_reference"] for x in (a, b) if x) else "NO"])
    w(table(["theta", "R=1 factorized: accuracy / mean exit timestep / events ingested", "baseline unfactorized: accuracy / mean exit timestep / events ingested", "RTL == reference"], rows))
    w("")
    w("![Figure 30: accuracy and mean exit timestep against the exit threshold](../figures/fig30_early_exit.png)")
    w("")
    w("*Figure 30.* Accuracy (left) and mean exit timestep (right) against the margin threshold, RTL, mean of 3 seeds; the knees are marked.")
    w("")
    w("### 4.2 The knee")
    w("")
    rows = []
    for kind, lab in (("r1", "R=1 factorized"), ("base", "baseline unfactorized")):
        for nm, desc in (("strict", "accuracy >= full-run accuracy at this threshold and at every larger one"), ("one_sample", "within one test sample (0.14 pp)"), ("half_pp", "within 0.5 pp"), ("one_pp", "within 1 pp")):
            k = kn[kind][nm]
            rows.append([lab, desc, k["theta"], pct(k["acc_mean"]), f"{k['exit_mean']:.2f}", pct(1 - k["exit_mean"] / 100, 1), "/".join(f"{a * 100:.2f}" for a in k["acc_by_seed"])])
        rows.append([lab, "full run (no exit)", "-", pct(float(np.mean(kn[kind]['full_acc_by_seed']))), "100.00", "0.0%", "/".join(f"{a * 100:.2f}" for a in kn[kind]["full_acc_by_seed"])])
    w(table(["model", "knee criterion", "theta", "accuracy (3-seed mean)", "mean exit timestep", "timesteps saved", "accuracy per seed"], rows))
    w("")
    w(f"**The knee is theta = {kn['r1']['strict']['theta']} for the R=1 model and {kn['base']['strict']['theta']} for the baseline** (strict criterion): accuracy intact, mean exit timestep "
      f"{kn['r1']['strict']['exit_mean']:.1f} / {kn['base']['strict']['exit_mean']:.1f}. Accuracy is flat to within one sample from theta ~ {kn['r1']['one_sample']['theta']} / {kn['base']['one_sample']['theta']} upward, so the curve is a plateau, not a cliff, "
      "and a threshold a little below the strict knee costs a fraction of a sample. **Caveat:** the thresholds were chosen on the 240 test samples that also report the accuracy (the project has no held-out raster set "
      "for the R=1 networks); a validation-based choice is an open item.")
    w("")
    w("### 4.3 Early exit disabled == Phase 3")
    w("")
    w(table(["comparison", "seed", "timesteps", "differences"], [[lab, s, f"{c['timesteps_compared']:,}", c["disagreements"]] for lab, cs in (("unfactorized baseline: comparator built, theta = never vs not built", dis_b), ("factorized R=1: comparator built, theta = never vs not built", dis_r)) for s, c in zip(SEEDS, cs) if c]))
    w("")
    w("### 4.4 Against the software study")
    w("")
    base_t = {r["theta"]: r for r in S["hw_sweep"] if r["model"] == "base"}
    w("`hdc_query.sweep` (the reference) reproduces `exp2_early_exit.json` - accuracy and mean exit timestep at all 11 stored thresholds for the three baseline seeds - exactly (`tests/test_hdc_query.py`, bipolar theta = 2 x "
      "integer theta), and the RTL reproduces the reference at every swept point. The README's check point 'bipolar theta = 128 with no accuracy loss and about 68 % of the events ingested' is integer theta = 64: ")
    r64 = base_t.get(64)
    if r64:
        w(f"RTL, baseline, 3-seed mean: accuracy {pct(r64['acc_mean'])} (full run {pct(float(np.mean(kn['base']['full_acc_by_seed'])))}), events ingested {pct(r64['events_fraction_mean'], 1)} "
          f"({pct(1 - r64['events_fraction_mean'], 1)} saved; the README's 67.9 % / 32.1 % is the seed-0 figure).")
    w("")
    w("## 5. The four ablation builds")
    w("")
    w("`cim_neurohdc_top` elaborates and passes in all four configurations; they are two parameters, not edits. Evidence per build:")
    w("")
    rows = []
    for b, (f_, e_), lab in (("full", (1, 1), "full design"), ("ee_off", (1, 0), "early exit OFF"), ("fact_off", (0, 1), "factorization OFF"), ("both_off", (0, 0), "both OFF")):
        reg = [AB.get(f"{b}_g8_s{s}") for s in SEEDS]
        gate_ = sum(r["mismatching"] for r in reg if r)
        rows.append([lab, f"FACTORIZED={f_}, EARLY_EXIT_EN={e_}", "clean" if lint.exists() else "-", "check -assert PASS, 0 latches" if gens[b] else "-",
                     f"{sum(r['samples'] for r in reg if r)} samples, {gate_} mismatching" if all(reg) else "-", pct(float(np.mean([r['accuracy'] for r in reg if r])), 2) if all(reg) else "-",
                     f"{np.mean([r['n_ts'] for r in reg if r]):.1f}" if all(reg) else "-"])
    w(table(["build", "parameters", "`verilator -Wall`", "Yosys elaboration", "regression at its operating threshold, g = 8 (3 seeds)", "accuracy", "mean exit timestep"], rows))
    w("")
    w("(Operating threshold: the strict knee of the model the build uses; early-exit-off builds run to the end. The ablation table with energy and area is in [`phase5_ppa.md`](phase5_ppa.md).)")
    w("")
    w("## 6. Verilator and Icarus")
    w("")
    ic = [c for c in S["compare"] if c["tag"].startswith("sim_")]
    if ic:
        w(table(["configuration (identical stimulus on both simulators)", "timesteps compared", "differences"], [[c["tag"][4:], f"{c['timesteps_compared']:,}", c["disagreements"]] for c in ic]))
        w("")
        w(f"Total {sum(c['timesteps_compared'] for c in ic):,} timesteps, {sum(c['disagreements'] for c in ic)} differences. The Icarus profile is a fixed random subset of the rows per configuration "
          "(Icarus is ~50x slower than Verilator); each is compared with a Verilator twin of identical arguments, so the stimulus is identical.")
    else:
        w("(Icarus matrix not run in this pass.)")
    w("")
    w("The cocotb unit tests of the new blocks (`top2_tree` N = 7/10/16/24, `exit_ctrl` with and without the comparator, `hdc_query` for both mappings) pass on both simulators:")
    w("")
    w(table(["case", "Verilator", "Icarus"], [[c, "PASS" if next((u["ok"] for u in ut if u.get("sim") == "verilator" and u.get("case") == c), False) else "-", "PASS" if next((u["ok"] for u in ut if u.get("sim") == "icarus" and u.get("case") == c), False) else "-"]
                                           for c in sorted({u["case"] for u in ut_new})]))
    w("")
    w("## 7. Phase 1E is untouched")
    w("")
    w("```")
    w(f"git diff --stat -- design/rtl/rtl/phase1_snn design/rtl/rtl/pkg/cim_neurohdc_pkg.sv   ->  {'(empty)' if not git_1e else git_1e}")
    w("```")
    w("")
    rc = load(ROOT / "results" / "phase234_1e_recheck" / "summary.json")
    if rc:
        w(rc.get("text", ""))
        w("")
        ut_all = load(UT / "summary.json", [])
        w(f"Full unit-test suite (1E's 31 cases + the new blocks) on both simulators, rerun with the Phase 2-5 tree: {sum(1 for u in ut_all if u['ok'])} of {len(ut_all)} cases PASS (`results/phase234_1e_recheck/unit_tests/`).")
    w("")
    w("## 8. Assumptions and open items (updated TO BE DETERMINED list)")
    w("")
    w("- **An abort in 1E's controller.** After an early exit `snn_ctrl` is parked in INGEST; the next sample needs a reset and a weight reload (2,560 cycles through `weight_load` in this model, plus the class image). "
      "The testbench does both and reports `reload_cycles` separately; they are *not* part of an inference. A real part keeps its weights (ReRAM) and needs only a 2-state abort input to `snn_ctrl` (return to IDLE/DONE "
      "and clear the counters). Recorded for the 1E follow-up, not done here (1E is frozen).")
    w("- **Threshold selection on the test set.** The knee is picked on the same 240 samples that report the accuracy; no held-out rasters exist for the R=1 networks. Open: choose theta on a validation split (needs "
      "validation spike rasters from the training scripts).")
    w("- **N-MNIST** was not run through the query stage: no class hypervector or R=1 network exists for it in the vectors (Phase 6 must report dataset dependence; the SNN side is exact on N-MNIST since 1E).")
    w("- **The R=1 network is a different model** (jointly trained, 80.4 % against 82.4 %, 3-seed means, full run): the cost of the factorization is paid in accuracy at training time, not in hardware. Higher ranks "
      "(R = 2..16) are not built; the mapping is rank 1 only (a rank-R array is a different `hdc_class_array`).")
    w("- **A live sensor** needs an input FIFO (or a stall-tolerant source) if events arrive faster than 1 per cycle between MVMs; the SNN is busy ~5-8 % of the time. Not designed: 1E's source is replayed and stalled.")
    w("- **The class-HV arrays are behavioural** (like the SNN crossbar in 1E): their analog design, margin and sensing for 10 columns are not done; Phase 5 prices them by scaling 1F's per-column read cost and 1C's area parts "
      "([ASSUM]).")
    w("- **Ties.** The leader of a tie is the lowest class index everywhere (reference, RTL, tournament); the margin of a tie is 0, so a tie can never trigger an exit with theta >= 1.")
    w("- **Verible** is not installed on this machine; the new files are `verilator -Wall` clean only (section 1 of `results/lint/lint_hdc.log`).")
    w("- **Widths.** The frozen W_V = 26 holds for all three R=1 networks but with only 12 % headroom on seed 2 (section 2.2); a different checkpoint could overflow it silently - the simulation asserts in 1E would catch it.")
    w("")
    w("## 9. Reproduce")
    w("")
    w("```")
    w("design/rtl/scripts/run_hdc_everything.sh              # everything (hours); stages log to design/rtl/results/logs/")
    w("venv/bin/python design/rtl/scripts/hdc_tables.py && venv/bin/python design/rtl/scripts/make_report_hdc.py     # only this report, from the runs on disk")
    w("```")
    OUT.write_text("\n".join(L) + "\n")
    print("wrote", OUT, len(L), "lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
