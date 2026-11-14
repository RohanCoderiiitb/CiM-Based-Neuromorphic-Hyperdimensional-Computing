# Design walkthrough: how the final chip works and why each choice was made

Companion to [`final_design.md`](final_design.md) (the numbers). This file explains the machine behind them and points to the report that justifies each choice. Where a point rests on a report I did not re-derive here, it says so. Section numbers refer to those reports.

## 1. What the chip does

NeuroHDC-style gesture recognition on DVS-Gesture event streams. The chip receives address-event (AER) events and returns a class label, usually before the stream ends.

```
events --> addr_gen --> count_mem --> [plane_seq --> crossbar macro --> shift_accum] --> IF neurons --> spike_reg
              |            |                          (analog MVM, 4 passes)                (20 neurons)      (20 bits / timestep)
              |        event_ctr ends the timestep;  snn_ctrl sequences everything
                                                                                                    |
                                      class hypervector query (XNOR scores) --> top-2 margin --> exit_ctrl --> label
```

Source: `design/rtl/rtl/` (`phase1_snn/` = the spiking part, `phase2_hdc/` = the classifier, `phase4_exit/` = early exit, `phase3_top/cim_neurohdc_top.sv` ties them together).

1. **Events to counts (`addr_gen`, `count_mem`).** Each event (x, y, polarity) becomes one of 512 input addresses (paper eq. 19: `p*256 + cell_y*16 + cell_x`, a 16 x 16 grid per polarity). A reciprocal multiply replaces the divide, so one RTL covers 128 x 128 and 34 x 34 sensors. Each address has an 11-bit event counter. A timestep holds N_e or N_e + 1 events (a counter rule found in Phase 0 that the first plan got wrong); `event_ctr` closes the timestep and `snn_ctrl` starts the scan. **Why it matters:** the timestep's input is a count vector, not a binary frame.
2. **Counts to currents: the compute-in-memory MVM (`plane_seq`, crossbar macro).** The 20 neurons' integer weights (8-bit, per-channel quantised, `q = round(Ws/s)`, clamp +-127) live in a ReRAM 2T2R crossbar: 512 rows, 160 columns = 20 neurons x 8 weight bit-planes (`N_WCOLS` in the package), built as five 512 x 32 macros. Each read senses 40 columns (2 bit-planes per neuron), so a full read takes 4 passes (`shift_accum` shifts by plane and pass). The 512 counters are read out group by group (g = 4 consecutive counters); the counts are applied bit-plane by bit-plane: one crossbar read per set count bit-plane of a group drives the 4 rows with bit b of the group's counters, and the resulting column current is proportional to the number of active rows with a stored 1. Comparators with a per-group threshold ladder turn it into a digital count. The sequencer (`plane_seq`) **skips every (bit-plane, group) read that has no active row** (item 1, `optimised_ppa.md`: 16,748 non-zero reads per inference instead of 61,622).
3. **Shift and add (`shift_accum`).** The per-plane counts are combined by shifting (plane and pass) and adding into a 21-bit `X` per neuron. The scan reads each counter once and clears it as it reads, so the scan is also the timestep wipe (`count_mem`).
4. **Integrate and fire (`if_neuron_array`, `spike_reg`).** `V += X` (26-bit), spike if `V >= thresh_int`, hard reset. Output: 20 spike bits per timestep. Phase 0 proves this integer model is bit-exact against the trained float model (0 of 480,000 spikes differ).
5. **Hypervector query (`hdc_query`, `hdc_class_array`, `hdc_score`, `top2_tree`).** The 20 spike bits enable rows of the class array (spike-gated row enable). In the factorized (rank-1) mapping this is a stationary 20 x N array (N = 10 classes) plus a T x N sign table and N bias registers; AND-popcount, the bias and the sign give exactly the XNOR-popcount score. N 11-bit score accumulators add the score every timestep and a top-2 tournament (`top2_tree`) gives the leader and the second-largest score; the decision is valid 5 cycles after the spike strobe (`hdc_query.sv` header). Factorising replaces 16 class macros by 1 and 20,000 bits of storage by 1,250, with scores identical to the unfactorised mapping (72,000 timesteps compared); the cost is in the *model*: 80.42% against 82.36% accuracy (`phase234_report.md` section 0).
6. **Early exit (`exit_ctrl`).** When the top-1 / top-2 margin passes a threshold theta the chip stops accepting events, so the remaining timesteps (and their events, reads and cycles) cost nothing. After an exit the controller takes `abort_i` (back to IDLE with the weights kept, counters flushed, query and exit state cleared; `digital_energy.md` section 6), so no weight reload is needed between samples.

## 2. Design choices and where each is justified

| Choice | Value | Why | Read |
|---|---|---|---|
| Cell and operating point | 2T2R differential, LRS = 3.5 kohm, 1 ns sense window | The decoupling capacitor scales with the array current and the window, so a lower resistance (more current) needs a bigger macro: with the window capped at 1 ns the macro is 0.318 mm^2 at 2 kohm, 0.248 at 3 kohm, **0.229 at 3.5 kohm**; the crossbar energy is 1.015 / 1.407 / **1.395 uJ**. The 5 kohm point does not meet the noise requirement in 1 ns (it needs 4 ns, macro 0.330 mm^2). 3.5 kohm is the point that brings the die under 0.399 mm^2; 2 kohm would save about 0.38 uJ of crossbar energy but its die would be about 0.44 mm^2 | `operating_point_sweep_report_tcap1.json` (regenerate: `python -m scaleup.op_sweep_report --tcap 1`, from `studies/crossbar`); `operating_point.md` section 1 describes the method (its table is the old, uncapped decap rule) |
| Rows per group g | 4 | g = 8 closes the electrical margin only for device spread sigma <= 0.07 and fails at 0.10; g = 4 closes through 0.15. Price: about 1.4x the non-zero reads | `phase1b_report.md` section 0, `phase1c_report.md` section 0, `phase1f_report.md` sections 0 and 8 |
| Columns per pass | 40 (4 passes of 40 cols) | The supply cannot deliver the full 160-column pulse: 10 mV droop at 1 ns needs 10 nF (1.2-2 mm^2). 40 columns at g = 4 needs about 1 nF (0.12-0.2 mm^2), at the cost of 4 passes per read | `phase1f_report.md` section 5 |
| Sense front-end | regulated current conveyor with 1:4 copy into a charge integrator, per-column two-parameter calibration | Only topology that holds the virtual ground at <= 125 uA per bitline. Calibration is mandatory: uncalibrated mismatch error is 24-44 uA against a 12.2 uA limit | `phase1f_report.md` sections 2-3 |
| Pulse / window | 1 ns at g = 4 | Set by front-end noise and calibration residual, not settling. Energy is linear in it | `phase1f_report.md` section 4 |
| Decoupling | C ~ 1 nF x (array current / 64 uA) x (T + 0.3 ns) / 1.3 ns | 1 nF at the 1F design point (8.7 mA peak, 1 ns pulse + 0.3 ns tail, 7 mV droop, `phase1f_report.md` section 5). The first version of the area model scaled it with the front-end bias as well and gave no window dependence; that produced the wrong 0.355 mm^2 die. The rule is now in `op_sweep_report.py` | `phase1f_report.md` section 5; `studies/crossbar/scaleup/op_sweep_report.py` |
| Threshold correction | deleted (rank 0: one static scale per column) | The row-line gain varies with the group and the number of active rows; correcting that cost energy (crossbar 3.11 -> 1.95 uJ when deleted, `optimised_ppa.md` item 7). At 3.5 kohm the residual after the per-column scale is 0.60% of full scale against a budget of 4.1% (`operating_point_sweep_report_tcap1.json`). Assumes the array row line is strapped on Metal9 across the cell (an assumption in `optimised_ppa.md` section 5.1); the rank-1 fallback costs about 0.6 uJ more | `optimised_ppa.md` item 7, section 5.1 |
| Count memory | 512 counters of 11 bits in one single-port SRAM macro (modelled as 1 kB, 512 x 16 b, CACTI 7, 45 nm), double-pumped (read on the rising, write on the falling edge), one event per cycle | It was 5,632 flip-flops behind a 512-way multiplexer. The CACTI figures are assumptions. A two-lane variant (2 events per cycle, 4 banks) was built and measured **worse** on routed power: 7.2 pJ per event against 4.86 | `optimised_ppa.md` item 3 (the two-lane attempt is not in any report) |
| Shift-accumulate | tree + one shift, 40 columns per pass | Flip-flops 10,668 -> 1,941, cell area 205,722 -> 41,636 um^2 | `optimised_ppa.md` item 4 |
| Clocking | clock gating at `gate-min 1`, operand isolation, CTS without insertion delay | Gating cut the digital block from 11.6 to 3.1 uJ together with the rest of items 1-6 | `digital_energy.md`, `optimised_ppa.md` items 2, 5, 6 |
| Timing closure | slow-corner synthesis, two-corner repair, one global+detail route session | Fixed -31.8 ns slow setup of the first flow | `optimised_ppa.md` section 1 |
| Early exit threshold | 28 | Lowering theta ends the inference earlier: energy about 4.2 uJ at theta 50 (2.85 uJ digital measured on the earlier layout + 1.40 uJ crossbar model), 2.72 uJ at theta 28 (measured cycles and reads). Accuracy 82.36% (unfactorised baseline) -> 80.42% (rank-1, theta 50, the knee where accuracy equals the full run) -> 78.2% (theta 28) | `phase234_report.md` section 4; the theta sweep for the final layout is in `final_design.md` |
| Floorplan | digital utilisation 0.50 on a 498 um wide die | 0.45 failed slow setup, 0.60 did not place | `final_design.md` |

## 3. Where the final numbers come from

Energy per inference = digital + crossbar:

- **Digital.** Gate-level simulation of the routed netlist, activity as per-cell SAIF, OpenSTA with the layout SPEF (fast library, 1.1 V): ingest 0.479 mW, scan 2.43 mW. Energy = 0.479 mW x ingest cycles + 2.43 mW x remaining cycles, per sample, averaged (mean 1.84 uJ at theta 28). Glitches are excluded (zero-delay simulation).
- **Crossbar.** The 3.5 kohm model with the window capped at 1 ns (array, word line, sense bias, comparators: 1.395 uJ per 16,748 reads = 83.3 pJ per read) times the measured non-zero reads per sample (about 10.7k at theta 28): 0.89 uJ. The model includes the per-plane readout and the front-end wake-up of `optimised_ppa.md` items 8-9.
- **Latency and power.** 198k cycles at 100 MHz = 1.98 ms; 2.72 uJ / 1.98 ms = 1.37 mW.
- **Area.** Die = crossbar macro (modelled 0.229 mm^2 for 160 channels: cell array + periphery + front-end + decoupling, with 20% overhead; 0.193 mm^2 if the 40-shared-channel front-end, which is not designed, were used) + the digital region (41,636 um^2 of cells at 0.50 utilisation) + margins. The macro is a model, the digital block is routed.

## 4. How accurate the accuracy claims are

| Reference point | DVS-Gesture accuracy |
|---|---|
| NeuroHDC paper, published | 87.5% (`phase5_ppa.md`) |
| Our bit-exact reimplementation of the paper's algorithm (factorisation off, no early exit) | 82.36% (3-seed mean) |
| Our full design, rank-1 factorised, theta 50 | 80.42% |
| Final design, theta 28 | 78.2% (78.75 / 80.00 / 75.83) |

The hardware matches the integer reference bit-for-bit in every timestep; the differences above come from the model (factorisation) and the exit threshold, not from the circuit. The 5-point gap between 87.5% and 82.36% is a reproduction gap that none of the reports explains. N-MNIST (94.91% in the Phase 0 model): the SNN part is bit-exact in RTL on 1,000 samples (`phase1e_report.md`), but no class hypervector or rank-1 network exists for it, so the full chip was not run on N-MNIST (`phase234_report.md` section 8).

## 5. What is not written up elsewhere

- **The decoupling rule** (now in `op_sweep_report.py` with a `--tcap` option; results in `operating_point_sweep_report_tcap1.json` and `_tcap4.json`). `operating_point.md` still shows the old, uncapped table.
- **The two-lane ingest trial** (queue, four banks, stage-registered input): routed at 0.376 mm^2 (498 x 754 um, utilisation 0.43) with timing closed in both corners, but worse on routed power per event, so dropped. The RTL is in `~/.cache/cim_neurohdc/a1_backup`.
- **SAIF power flow.** `design/rtl/synth/opt/power.py` converts the VCD window to per-cell SAIF because OpenSTA 3.1.0 annotates pins only.
- **Not modelled or verified:** the comparator latch and threshold generator (not simulated at transistor level), the calibration procedure, the 3.5 kohm crossbar macro as a circuit (modelled, not laid out), and the decoupling placement.

## 6. Suggested reading order

1. `phase0_report.md` (the reference model), then `phase234_report.md` (query and early exit).
2. `phase1b_report.md`, `phase1c_report.md`, `phase1f_report.md` (the analog array and front-end; the 1F section 0 is the most important).
3. `phase1e_report.md`, `digital_energy.md`, `optimised_ppa.md` (the digital block and the flow).
4. `operating_point.md` section 1 (the resistance sweep), then `final_design.md`.
5. Skip unless needed: `phase1a`, `phase1b_provisional`, `phase1d_i`, `phase1d_ii` (device and write path), `crossbar_netlist.md`, `final_ppa.md`, `phase5_ppa.md` (earlier PPA passes).
