#!/usr/bin/env bash
# The Verilator regression suite (Levels 4 and 5, g-sweep, column-mode sweep, N-MNIST). One log per run in results/logs, one JSON per run in
# results/regression. Icarus runs are in scripts/run_icarus_regressions.sh.
set -uo pipefail
cd "$(dirname "$0")/../.."
PY=venv/bin/python
R="$PY 03_rtl/scripts/run_regression.py --sim verilator"
LOG=03_rtl/results/logs
run() { tag=$1; shift; $R --tag "$tag" "$@" > "$LOG/$tag.log" 2>&1; tail -1 "$LOG/$tag.log"; }

# Build the default (g=8) model once, serially: parallel runs sharing one cached build directory race on the link step.
$R --tag warmup_g8 --dataset dvsgesture --seed 0 --rows first1 --g 8 > "$LOG/warmup_g8.log" 2>&1 || { echo "warm-up build failed, see $LOG/warmup_g8.log"; exit 1; }
rm -f 03_rtl/results/regression/warmup_g8.*
# Level 5: all 240 DVS-Gesture samples x all three seed weight images (design point g = 8, all 160 columns per read, plane skipping on)
for s in 0 1 2; do run dvs_seed${s}_g8_c160 --dataset dvsgesture --seed $s --rows all --g 8 & done; wait
# Level 5 + criterion 3: the same 240 samples at every other g (seed 0), raster must be bit-identical
for g in 4 16 32 64; do run dvs_seed0_g${g}_c160 --dataset dvsgesture --seed 0 --rows all --g $g & done; wait
# column-sensing assumption B (one weight bit-plane per read) and plane skipping disabled
run dvs_seed0_g8_c20 --dataset dvsgesture --seed 0 --rows all --g 8 --cols 20 &
run dvs_seed0_g8_noskip --dataset dvsgesture --seed 0 --rows all --g 8 --no-skip &
run dvs_seed0_g64_c20 --dataset dvsgesture --seed 0 --rows all --g 64 --cols 20 &
wait
# Level 4: real AER streams (20, every class) and synthesised streams, randomised idle gaps (stall path), same-address adjacency stress
for s in 0 1 2; do run dvs_seed${s}_level4_real_gaps --dataset dvsgesture --seed $s --rows real --g 8 --gap 1 & done; wait
run dvs_seed0_level4_shuffled_gaps --dataset dvsgesture --seed 0 --rows rand48 --g 8 --gap 1 --order shuffle &
run dvs_seed0_level4_sorted_gaps --dataset dvsgesture --seed 0 --rows rand48 --g 8 --gap 1 --order sorted &
run dvs_seed1_level4_sorted_nogap --dataset dvsgesture --seed 1 --rows rand48 --g 8 --gap 0 --order sorted &
wait
# N-MNIST: 1,000 samples, shared threshold, divide-by-34 address path (reciprocal multiply), back-to-back and with random gaps
run nmnist_seed0_g8 --dataset nmnist --seed 0 --rows all --g 8 &
run nmnist_seed0_g8_gaps --dataset nmnist --seed 0 --rows all --g 8 --gap 1 &
run nmnist_seed0_g64 --dataset nmnist --seed 0 --rows all --g 64 &
wait
