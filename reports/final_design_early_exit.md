# Final design: post-route PPA and accuracy

Open-source tools only (Yosys, OpenROAD, OpenSTA, ngspice, NeuroSim), 45 nm, 100 MHz, 1.1 V. This report supersedes the area and energy claims of `operating_point.md` (its 0.355 mm^2 die was wrong: it used a 5 kohm macro modelled too small; see the note at its top).

## The design

Single-lane digital block (HEAD RTL, factorisation and early exit on), crossbar at LRS = 3.5 kohm with a 1 ns sense window and 40 columns sensed per pass (4 passes per read), early-exit threshold theta = 28, layout at digital utilisation 0.50.

## Result against NeuroHDC-small

One chip (same die, same 100 MHz clock); the early-exit threshold is a runtime register, theta = 28 for DVS-Gesture and theta = 64 for N-MNIST.

| | DVS-Gesture, ours (theta = 28) | DVS-Gesture, NeuroHDC-small | N-MNIST, ours (theta = 64) | N-MNIST, NeuroHDC-small |
|---|---|---|---|---|
| accuracy | 78.2 % (78.75 / 80.00 / 75.83) | 87.5 % published; 82.36 % our bit-exact reimplementation | 90.15 % (89.90 % in RTL, 1,000 samples) | 97.28 % published; 94.91 % our bit-exact reimplementation |
| energy per inference | **2.72 uJ** | 3.01 uJ | 0.53 uJ | 0.315 uJ |
| die area | **0.352 mm^2** | 0.399 mm^2 | **0.352 mm^2** | 0.399 mm^2 |
| latency | 1.98 ms | 1.8 ms | 0.44 ms | 80.77 us |
| average power | 1.37 mW | 1.67 mW (derived) | 1.20 mW | 3.90 mW (derived) |

Paper values from its Table III (energy and area as scaled to 45 nm); the paper's average power is derived as energy / latency (3.01 uJ / 1.8 ms; 0.315 uJ / 80.77 us). How measured: area from the detail-routed layout (`f2`); digital power from SAIF gate-level simulation of the routed netlist (OpenSTA, fast library) times RTL cycle counts; crossbar energy from the ngspice-based model (83.3 pJ per read at 3.5 kohm, 1 ns window) times the measured non-zero reads. DVS: 3 seeds x 240 samples. N-MNIST: 1,000 RTL samples, power from four N-MNIST windows (`design/rtl/synth/opt/nm_power.py`).

## Layout (f2)

Die 498 x 706 um = 0.352 mm^2 (macro 229,000 um^2 modelled, digital cells 41,636 um^2). Detail-routed, both corners: slow setup WNS +0.10 ns, hold +0.15 ns; fast setup +3.48 ns, hold +0.13 ns; zero setup and hold violations. 36 residual Metal2 spacing markers beside macro obstructions, the class reported in `optimised_ppa.md` (no timing effect). Utilisation 0.45 failed slow setup (-1.95 ns); 0.60 did not place.

## Power method

Gate-level simulation of the routed netlist (10 timesteps, row 46, timestep 10), activity written as **SAIF** (per-cell pin blocks; OpenSTA 3.1.0 only annotates pins), OpenSTA with the layout's SPEF, fast library: ingest 0.479 mW, scan 2.43 mW, 55,512 of 56,407 pins annotated (98.4 %). Energy = P_ingest x ingest cycles + P_scan x remaining cycles, per sample, then averaged (digital 1.84 uJ); crossbar = 83.3 pJ per read x the measured non-zero reads per sample (about 10.7k, 0.89 uJ). Glitch power is excluded (zero-delay simulation), as in earlier passes.

## Caveats

- Energy per seed is 2.37 / 3.29 / 2.51 uJ; the mean (2.72 uJ, 9.5 % under) beats 3.01 uJ, seed 1 (the longest runs, 80.0 % accuracy) does not.
- The crossbar energy is the sweep model at 3.5 kohm with the sense window capped at 1 ns (`studies/crossbar/results/macro_512x32/operating_point_sweep_report_tcap1.json`: 1.395 uJ at 16,748 reads, macro 0.229 mm^2 for 160 channels, 0.193 mm^2 with 40 shared channels, which is not designed), not a simulation of the exact macro. The layout uses the 0.229 mm^2 figure.
- Area missed the 15 % goal (0.339 mm^2): 12 % under the paper.
- Latency is about 10 % longer than the paper's; the power advantage comes from the longer run.
- At full accuracy (theta = 50, 80.42 %) the energy does **not** beat the paper (about 4.2 uJ: 2.85 digital + 1.40 crossbar).
- Reproduce N-MNIST: `design/rtl/scripts/run_hdc_regression.py --dataset nmnist --model base --factorized 0 --early-exit 1 --theta 64 --rows all --g 4 --cols 40 --chunks 8 --tag nm_t64_s0`.
- Reproduce: `design/rtl/synth/opt/power.py --tag f2 --build full --stage routed` (SAIF), `design/rtl/scripts/run_hdc_regression.py --theta 28 --seed {0,1,2}` (tags `fin_t28_s*`).
