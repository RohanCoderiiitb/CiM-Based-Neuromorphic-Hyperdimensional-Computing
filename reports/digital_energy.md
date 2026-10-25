# Digital energy pass - clock gating, operand isolation, abort

Tags: **[SIM]** simulated (Yosys + OpenSTA, 45 nm library, gate-level Icarus activity), **[RTL]** measured on the RTL regression, **[1F]** carried forward from [`phase1f_report.md`](phase1f_report.md) unchanged, **[MODEL]** analytic in code, **[ASSUM]** assumed. Numbers are read from `design/rtl/results/ppa_digital/*` and `results/hdc/*` by `design/rtl/scripts/make_report_digital.py`. Companions: [`phase5_ppa.md`](phase5_ppa.md), [`phase234_report.md`](phase234_report.md). (The brief said `results/reports/`; that directory does not exist, the repository's reports live in `reports/`, so the report is here.)

## 0. The answer

- **Digital power 0.147 mW against Phase 5's 3.31 mW (23x lower)**, same gate-level activity method, same sample (row 46), same 8,000-cycle window, 100 % of 270,502 pins annotated, gate level equal to the golden model over the window. The flip-flop clock energy that was 89 % of the digital energy is now 0.089 mW (sequential 0.059 + clock/ICG network 0.030) against Phase 5's 2.93 mW; Phase 5's *ideal-gating bound* for the sequential term was 0.009 mW. So gating removed ~97 % of the sequential energy but is still ~10x above the ideal bound; the remainder is what a real implementation pays (ICG cells, enable paths, the 1,600 partial-count flops of the fold that must be clocked on every non-empty read).
- **Energy per inference at the measured exit timestep (g = 4 recommended point, mean of 3 seeds x 240 samples): 4.37 uJ** against Phase 5's 19.23 uJ and NeuroHDC-small's 3.01 uJ (same exclusions as Phase 5, section 1). Digital 1.26 uJ (was 16.12), crossbar reads 3.11 uJ (unchanged, [1F] x [RTL]), class-HV arrays 0.0005 uJ. That is **1.45x NeuroHDC-small**. The digital number is phase-resolved (section 4); the Phase-5-method window average gives 0.72 uJ digital / 3.83 uJ total - I headline the phase-resolved one because the window average under-weights the read phase (section 4).
- **Bit-exactness:** every functional result is unchanged - the verification table is section 7 (what ran, what was reduced, what is outstanding).
- **The clock gating was not missing from the RTL - the enables were already there** (section 2): synthesis mapped them to enable-flops that are still clocked every cycle. Real gating needed (i) a synthesis step and (ii) two RTL restructurings (in-place counters, hierarchical gate trees) because naive per-counter ICGs cost 161 uW of idle clock-gate power and the read-modify-write read mux 297 uW.

## 1. What is and is not in these numbers

Identical to Phase 5 except the digital power: crossbar read energy per non-zero read from 1F (186 pJ at g = 4), class-HV arrays from the Phase 5 models, cycles / reads / exit timesteps from the RTL regression (**provenance: the ablation logs `ab_*` and `c20_check_s0` are Phase 5's own, reused; only `ab_full_g4_s0` was re-run on the modified RTL and matched. Reuse is justified by the regression result in section 7: 166 re-run configurations, 1.84 million timesteps, line-by-line identical to the Phase 2-5 logs, cycle and read counters included**), the cycle model validated on the 20-column RTL run. **Exclusions, unchanged:** clock tree and clock network (ideal clocks - this matters more than before, see section 5), wire capacitance, supply regulator, decoupling leakage, calibration, write path / weight load, host IO, analog array leakage at rest, idle bias of empty reads. NeuroHDC-small's 3.01 uJ is a whole accelerator including its clock tree and SRAM macros; ours is pre-layout.

## 2. E0 and E1(a): the c20 difference, and why gating was not already happening

**E0 (c20_check_s0, 'one difference', Verilator vs Icarus, 54,231 timesteps) - benign, criterion 5 closed.** The 'difference' was a line-count entry of an Icarus run that had been *killed* before finishing rows 196/229/238; a stale `compare_summary.json` from the earlier partial run survived and was read as a result. The complete re-run (Icarus, 8 chunks) produced 1,205 timesteps / 24 END records which agree with Verilator on every field except END field 13 (`reload_cycles`), which depends on how samples are partitioned over simulator processes (the first sample of a process pays the weight load, the others the reload) - a property of the harness chunking, not of the design. `hdc_compare_all.py` now masks that field for cross-simulator comparisons and says so. The corrected total is 54,342 timesteps.

**E1(a): the enables were in the RTL.** `count_mem` (`if (s2_valid_q) cnt_q[a] <= ...`), `shift_accum` (`else if (m_valid_i)`) and the sign table all had enable conditions. Yosys + `dfflibmap` mapped 6,982 of Phase 5's 10,584 flops to `EDFFHQX1` (enable flop, 8.55 um^2: an internal mux in front of an always-clocked flop) and 3,602 to `DFFHQX1` with the enable folded into logic - no gate was ever inserted. Real clock gating needs the library's ICG (`TLATNCAX2`, 5.47 um^2) and Yosys' `clockgate` pass, which only converts fine-grained `$_DFFE_` cells and only if sync-reset flops are kept as data logic (`opt -nosdff`). So it was a synthesis mapping problem first. The second finding made it an RTL problem too: an ICG draws ~3.1 fJ per cycle (0.31 uW) *even when disabled* (its own clock pin toggles), so 512 flat per-counter ICGs cost 161 uW idle - which is why the final design gates hierarchically (a parent gate stops the clock to its children). Details in section 3.

## 3. E1: what was done, and the power by step

Changes ([RTL], all behind parameters `CLOCK_GATING`, `OPERAND_ISOLATION`, `INSTRUMENT_EN`; defaults on, off reproduces the old structure): `clk_gate` / `clk_gate_tree` modules (latch + AND, mapped to `TLATNCAX2` by `synth/icg_map.v`, gate-level model `tb/gl/icg_models.v`); `count_mem` increments each counter in place on its own gated clock (same two-stage pipeline flags, so `busy_o`, `fwd_o` and every cycle count are identical); `hdc_query`'s 100-row sign table and bias on a two-level tree; `shift_accum` operand isolation and empty-group gating (section 6). The waterfall below is on the *hierarchy-preserving* netlist (leaf-cell sum, same window), the only netlist that allows a per-module view; flat headline numbers are in section 0.

| step | digital power (mW), hierarchical netlist | vs previous step |
|---|---|---|
| Phase 5 design, ungated, instrumentation stripped (hier netlist) | 2.855 | - |
| per-counter ICGs inferred by Yosys `clockgate`, read-modify-write counters | 0.708 | -75% |
| + in-place counter increment (no 512:1 x 11 read mux, no forwarding) | 0.437 | -38% |
| + explicit hierarchical clock-gate trees (8x8x8 count memory, 2-level sign table) | 0.249 | -43% |
| + operand isolation of the fold network | 0.206 | -17% |
| + empty-group gating of the partial counts (final design) | 0.165 | -20% |

(The flat-netlist Phase-5-method headline is 0.147 mW: the hierarchical netlist is ~12 % higher because cross-module optimisation is blocked. Phase 5's own flat figure was 3.31 mW; the ungated hierarchical stripped build above is the like-for-like start of the waterfall.)

| module | ungated (uW) | final (uW) | factor |
|---|---|---|---|
| u_snn.u_count_mem | 1584.5 | 45.8 | 35x |
| u_snn.u_shift_accum | 616.4 | 57.9 | 11x |
| u_query | 336.0 | 3.0 | 113x |
| u_snn.u_neurons | 149.0 | 1.5 | 96x |
| u_snn | 89.1 | 9.4 | 9x |
| u_snn.u_event_ctr | 26.0 | 18.5 | 1x |
| u_snn.u_ctrl | 19.6 | 8.9 | 2x |
| u_snn.u_addr_gen | 8.8 | 8.8 | 1x |
| u_snn.u_spike_reg | 8.0 | 0.9 | 9x |
| u_snn.u_plane_seq | 5.8 | 2.5 | 2x |
| u_exit | 4.1 | 0.6 | 7x |
| u_snn.u_weight_load | 3.8 | 1.7 | 2x |
| (top glue) | 3.6 | 0.6 | 6x |
| u_query.u_top2 | 0.1 | 0.1 | 1x |

Module attribution is by instance-name prefix; the ICG cells of the gate trees are listed with their parent module's glue (`u_snn`), not with the counters they gate. The leaf-cell sum is exact.

**Against Phase 5 and the ideal bound (flat netlist, same window):** total 3.31 -> 0.147 mW; sequential 2.93 -> 0.059 mW; combinational 0.375 -> 0.058 mW; clock/ICG network 0 -> 0.030 mW. Phase 5's ideal-gating sequential bound was 0.009 mW (alpha = 0.0031 transitions per flop-cycle); the gated design's measured alpha is 0.0024 (flops that ever change: 2,842 of 9,930). (9,882 flops sit behind the 738 ICGs; 48 stay on the free-running clock. The per-ICG edge counts in `icg_activity` are not used here: they do not follow the nested count-memory trees reliably.)

**What real gating costs.**

| item | value |
|---|---|
| ICG cells in the netlist | 738 (40 inferred by Yosys on the remaining enabled registers + 698 explicit `clk_gate` instances: 584 count memory, 113 sign table, 1 bias) |
| ICG area | 4,037 um^2 = 2.0% of the digital area |
| digital area, flat buffered mapping | 205,722 um^2 against Phase 5's 234,969 (-12.4%: the 512:1 x 11 read mux and 6,982 enable-flops (8.55 -> 5.47 um^2 per flop) outweigh the ICGs) |
| flip-flops | 10,668 (Phase 5: 10,584) |
| timing, reg->reg slack at 10 ns, fast / slow corner | 8.01 / 1.76 ns (Phase 5: 7.99 / 1.77 ns) - **closes at 100 MHz in both corners, all four builds** (worst slow-corner slack 1.69 ns) |
| enable path | the gate enables come from registered signals (`s2_valid_q`/`s2_addr_q` for the count memory, the sign-table write strobe) through a 3-level (count memory) or 2-level (sign table) decode; the latch is transparent while the clock is low, so the enable has a half cycle; OpenSTA, with ideal clocks, meets it with the slacks above |
| NOT modelled | clock-tree synthesis and skew through the gates (each gated clock is a separate branch that CTS must balance - the real risk of this design, and it adds clock-tree power that the ideal-clock numbers exclude); ICG enable setup after place-and-route |

**Instrumentation (E1c).** The ~300 `ts_*` / `sq_*` per-timestep counters are behind `INSTRUMENT_EN`; the regression keeps them on, the power netlists build them off:

| netlist (hier, same window) | instrumentation ON (mW) | OFF (mW) | saved |
|---|---|---|---|
| ungated | 3.091 | 2.855 | 8% |
| gated (final structure) | 0.247 | 0.165 | 33% |

In the gated design the counters are a third of the digital power - they would have been the largest single module had they stayed in. Phase 5's 3.31 mW already stripped part of them; the 'ungated, OFF' row is the stripped baseline. (The ungated/OFF run starts every library flop at 0: an ABC cone of the form ~((q & k) | ~(a | q)) is 0 for any known q but X for q = X in a 4-state zero-delay simulation, so a reset that is correct in silicon never clears the X there; measurement baseline only, the gated builds reset from X and match the golden model.)

## 4. E4: energy per inference, re-measured

**Method.** Phase 5's was digital energy = window-average power x cycles. That was exact when every cycle cost the same (the clock tree dominated). It is not exact now: the power netlist is the g = 8 / 160-column design, whose 8,000-cycle window is mostly event ingest, while at the recommended g = 4 point the read phase is ~51 % of the cycles. I therefore also measured two short windows of the same netlist and sample - an ingest-only window (cycles 12,000-14,400) and a read-phase window (14,580-15,140, one crossbar walk) - and price the accepted-event cycles at the first and all other cycles at the second. The window average understates; the phase-resolved number is the one to use. Both are shown.

| build (g = 4) | accuracy | mean exit t | cycles | window power (mW) | P ingest / P read (mW) | crossbar reads (uJ) | digital, phase-resolved (uJ) | digital, window avg (uJ) | **total, phase-resolved (uJ)** | total, window avg (uJ) | Phase 5 total (uJ) | digital area (mm^2) | total area (mm^2) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| full design | 80.42% | 57.6 | 486,963 | 0.147 | 0.105 / 0.407 | 3.11 | 1.26 | 0.72 | **4.37** | 3.83 | 19.23 | 0.206 | 0.642 |
| early exit OFF | 80.42% | 100.0 | 838,141 | 0.145 | 0.105 / 0.400 | 5.29 | 2.15 | 1.22 | **7.44** | 6.51 | 33.03 | 0.199 | 0.636 |
| factorization OFF | 82.36% | 60.7 | 511,181 | 0.141 | 0.100 / 0.396 | 3.26 | 1.28 | 0.72 | **4.55** | 3.99 | 18.71 | 0.193 | 0.737 |
| both OFF | 82.36% | 100.0 | 838,141 | 0.141 | 0.100 / 0.401 | 5.29 | 2.14 | 1.18 | **7.44** | 6.49 | 30.53 | 0.198 | 0.742 |

NeuroHDC-small: 0.399 mm^2, 3.01 uJ. At g = 8 (reported alongside, not recommended): full design 3.99 uJ (Phase 5 18.85); early exit OFF 6.80 uJ (Phase 5 32.39); factorization OFF 4.15 uJ (Phase 5 18.31); both OFF 6.80 uJ (Phase 5 29.89).

### The three explicit answers

**(a) Does factorization flip from a cost to a win on both axes?** Factorization ON vs OFF, both with early exit (full design vs factorization-OFF, g = 4). **Energy: yes, it flips - a cost of +0.523 uJ in Phase 5 became -0.182 uJ now.** Where Phase 5's cost came from: the factorized datapath's extra flip-flops (sign table, bias; digital power 3.31 against 3.02 mW) were clocked every cycle, so they cost energy on every one of the inference's cycles even though the factorized design runs 24,218 fewer cycles (it exits at timestep 57.6 against 60.7). Gated, those flops sit idle: window power 0.147 against 0.141 mW, and the fewer cycles, the smaller class-HV array read (0.0005 against 0.0087 uJ) and the lower crossbar energy now win. **Area: it was already a win in Phase 5 and still is** (-95.1 x 10^-3 mm^2 now, -98.6 Phase 5 - modelled class-HV arrays, [ASSUM]); it did not flip, it never was a cost. The remaining cost of factorization is not a hardware axis: accuracy -1.94 pp, because rank 1 is a different, jointly trained network (not a compression of the baseline). Note the energy gap of 0.18 uJ also contains the crossbar difference between the two models (-0.15 uJ), i.e. it is a model-plus-hardware comparison, as in Phase 5.

**(b) Is the a = 0 read skip still worth it?** The skip removes 179,497 of 486,963 cycles per inference (37%), which is a *throughput* gain either way. As energy: in Phase 5 it was worth 0.26 uJ of digital energy under the window-average model (every cycle costs the same). With gating an empty read costs far less than the average cycle (the group is empty, so the partial counts are held and the fold network is isolated): the saving is **bounded above by 0.73 uJ (16.7% of the 4.37 uJ total)** - taking every removed cycle at the full read-phase average power - and below by 0. The analog side draws nothing for an empty read in the Phase 5 model, so it saves nothing there. **Decision: the measured numbers do not settle it.** The bound is wide (0 to 0.73 uJ) because I only have power windows of a mixed read walk, not of a stretch of empty reads; with gating an empty read is far cheaper than the walk average, so the true saving is likely a fraction of the upper bound. Recommendation: do **not** spend RTL effort on it for energy; treat it as a throughput/latency feature (-37% cycles) and decide after 1G has moved the crossbar term, when its share of the total is larger. A one-window power run on an empty-read stretch would pin the number (about 10 minutes); not done.

**(c) The largest remaining term** is **crossbar reads (1F x RTL): 3.11 uJ = 71% of 4.37 uJ** (crossbar reads (1F x RTL) 3.11, digital, read phase 1.01, digital, event ingest 0.25, class-HV arrays 0.00). The crossbar read energy (186 pJ per non-zero group read, 1F) is now the project-level bottleneck, as the original argument predicted: the next pass is the analog read-energy pass (1G). Headroom not taken: voltage scaling of the digital supply (energy ~ V^2; the library is characterised at 1.1 V only), and the count memory as an SRAM macro instead of 5,632 flops (Phase 5 follow-up).

## 5. E2: operand isolation

Operand isolation of the fold network (inputs held at zero except on the cycle its result is consumed) took the design from 0.249 to 0.206 mW (-17%), well above the 'few percent' drop line, so it was kept. Measuring it showed the premise was slightly off: much of the energy was in the 1,600 partial-count flops and the fold adder tree behind them, which are clocked on *empty* reads too. Gating those flops on 'the group has no active row' (`grp_nz` / `t_nz_q`; an empty group contributes exactly zero, so the result is bit-identical) gave a further 0.165 mW (-20%). Both are in the final design; `shift_accum` went from 616 uW ungated to 58 uW and is still the largest module.

## 6. E3: abort

`abort_i` (one-cycle strobe) returns the controller from RUN to IDLE with the weights kept (`loaded_q` untouched), flushes the count memory, restarts the sequencer, clears the accumulator, the query stage and the exit controller, and cancels the cycle's event accept, so the next `start_i` begins a clean inference **without a reset and without the 2,560-cycle weight reload**. Verified by (i) the unit tests (`plane_seq` and `count_mem` abort / flush tests), (ii) `abortmode_*`: the regression re-run so that every sample after the first starts via `abort_i` after the early exit instead of reset + reload - predictions, scores and exit timesteps identical to the reset flow (the regression compares against the golden model), and (iii) `abortstress_*`: before every sample a decoy run is aborted at a random cycle of each run state (ingest, drain, MVM, update, emit, wipe; CHECK is a single cycle and covered statistically; MVM_WAIT is unreachable) - the sample after it must be bit-identical. **This found a real bug:** the class array's registered valid survived `clr`, so the first score after an abort could be stale (793 assertion messages in the stress run); fixed by masking the array valid for one cycle after `clr` in `hdc_query`. The early-exit flow therefore composes: an exit at timestep t leaves the accelerator ready for the next sample after one cycle instead of ~2,560 (2,133 reload cycles per sample on average in the Phase 5 model, now unnecessary).

## 7. Verification (acceptance)

| check | result | where |
|---|---|---|
| cocotb unit tests (Verilator and Icarus, incl. new clk_gate_tree, abort, isolation, g-sweep) | PASS (94 suites on the two simulators, 0 failures) | `results/unit_tests/` |
| lint (Verilator -Wall, INSTRUMENT_EN 0/1, synthesis view) | clean, 0 warnings (Verible not installed) | `scripts/lint_hdc.sh` equivalents |
| generic Yosys synthesizability, 4 builds | `check -assert` PASS, 0 latches with CLOCK_GATING = 0; with = 1 every latch is a clk_gate (698) | `synth_check_hdc.sh`, `synth_check.sh` |
| bit-identical to the Phase 2-5 logs (every timestep line of every configuration) | 166/166 configurations identical, 1,839,397 timesteps | `results/hdc/before_after.json` |
| Verilator regression, 162 configurations of the main matrix (4 builds incl. both models, theta sweep to 256, early exit off/never, real AER streams with gaps, sorted/shuffled order), 240 samples each | all PASS, 0 mismatching samples, 0 assertion messages | `results/hdc/*.json` |
| abort: `abortmode_full_g4_s0` (abort_i after every exit instead of reset + reload) and `abortstress_full_g4_s0` (decoy run aborted in every run state before every sample), 240 samples each | both PASS, 0 mismatching, 0 assertion messages | `results/hdc/abort*.json` |
| gate level vs golden model, final netlists, 4 builds | bit-exact over the power windows (5 timesteps; 3 and 3 in the phase windows), 0 unannotated pins. **Whole-inference gate-level equivalence was started and stopped (reduced scope): not claimed** | `ppa_digital/*/power*/power_summary.json` |
| Verilator vs Icarus on the modified RTL | **not re-run (reduced scope).** The unit tests pass on both simulators; the E0 cross-simulator comparison (1,205 timesteps) predates the gating changes | - |
| not re-run (reduced scope) | seeds 1-2 of the ablation / abort runs, the Icarus subset and the twin set, the 1E re-check (`recheck_1e.sh`) | - |


## 8. Reproduce

```
# final-configuration builds (4): area + timing both corners, then gate-level power (flat), windows, per-module power
venv/bin/python design/rtl/scripts/synth_ppa.py --builds full ee_off fact_off both_off --hier --gate 4 --rtl-gating 1 --isolate 1 --instr 0 --out ppa_digital
venv/bin/python design/rtl/scripts/synth_power.py  --builds full ee_off fact_off both_off --gate 4 --rtl-gating 1 --isolate 1 --instr 0 --out ppa_digital
venv/bin/python design/rtl/scripts/synth_power.py  --builds full ee_off fact_off both_off --tag _ing --start 12000 --len 2400 ... ; --tag _mvm --start 14580 --len 560 ...
venv/bin/python design/rtl/scripts/power_by_module.py --builds full --out ppa_digital --gate 4 --rtl-gating 1 --isolate 1 --instr 0   # (+ the ungated / instrumented variants)
venv/bin/python design/rtl/scripts/run_hdc_matrix.py --sim verilator --set main|extra|twin ; compare_before_after.py --before <old results/hdc> ; hdc_compare_all.py
venv/bin/python design/rtl/scripts/digital_energy.py && venv/bin/python design/rtl/scripts/make_report_digital.py
```

## 9. Updated TO BE DETERMINED list

- **Clock tree / skew through the gates is not modelled** (ideal clocks). Gated clocks are separate branches that CTS must balance; the clock-tree power excluded here may be a sizeable part of the remaining digital energy. Needs place-and-route.
- **Digital power is window-sampled** (one sample, row 46; three windows). The phase-resolved estimate removes the gross mix error; the read-phase window is a g = 8 walk, so its share of non-empty reads is higher than at g = 4 - the phase-resolved energy is, if anything, conservative.
- **a = 0 read skip**: bounded, not built (section 4b). **Voltage scaling** of the digital supply: untested headroom. **Count memory as an SRAM macro** instead of 5,632 flops: Phase 5 follow-up, not done.
- **Analog read energy (1G)** is now the largest term (section 4c): unchanged 1F numbers; 186 pJ per non-zero read at g = 4.
- Still open from Phase 5: class-HV array energy/area are scaled models; the 1F energy model's own open items; no NeuroSim cross-check; two corners of one lab library; thresholds chosen on the 240 test samples; no P&R.
