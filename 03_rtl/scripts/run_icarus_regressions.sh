#!/usr/bin/env bash
# Criterion 6: the SAME configurations as run_all_regressions.sh (same arguments => same rows, same per-sample gap seeds) on Icarus, then a
# per-timestep comparison against the Verilator run of each configuration (scripts/compare_sims.py). CHUNKS parallel simulator processes per run.
# Resumable: a configuration whose results/regression/icarus_<tag>.json already exists is not re-run (delete the file to force it).
#   PROFILE=full       (default) every configuration on every sample: ~8-9 h on 10 cores (Icarus ~11k cycles/s/process)
#   PROFILE=overnight  the design point and the stress runs in full, the remaining sweeps on a fixed random subset of rows (48 DVS, 200 N-MNIST
#                      samples); same rows as the Verilator run of that row, compared per timestep. ~4-5 h. The report lists samples per configuration.
set -uo pipefail
cd "$(dirname "$0")/../.."
PY=venv/bin/python
CHUNKS=${CHUNKS:-10}
PROFILE=${PROFILE:-full}
LOG=03_rtl/results/logs
R="$PY 03_rtl/scripts/run_regression.py --sim icarus --chunks $CHUNKS"
PAIRS=""
if [ "$PROFILE" = overnight ]; then SUB_DVS=rand48; SUB_NM=rand200; else SUB_DVS=all; SUB_NM=all; fi
# Synthesised streams draw their event order from one RNG consumed row after row, so a SUBSET run sends different events for a row than the
# full Verilator run did (identical counts, different order: only the order-dependent forwarding counter differs). A subset is therefore compared
# with a Verilator "twin" run of identical arguments (tag sub_<tag>), not with the full run.
# run TAG ROWS args...
run() {
  tag=$1; rows=$2; shift 2; vtag=$tag
  if [ ! -s 03_rtl/results/regression/icarus_$tag.json ]; then $R --tag "icarus_$tag" --rows "$rows" "$@" > "$LOG/icarus_$tag.log" 2>&1; fi
  tail -1 "$LOG/icarus_$tag.log"
  if [ "$rows" != all ] && [ "$rows" != real ] && [[ "$tag" == dvs_seed0_g* ]]; then
    vtag=sub_$tag
    [ -s 03_rtl/results/regression/$vtag.json ] || $PY 03_rtl/scripts/run_regression.py --sim verilator --tag "$vtag" --rows "$rows" "$@" > "$LOG/$vtag.log" 2>&1
    tail -1 "$LOG/$vtag.log"
  fi
  PAIRS="$PAIRS $vtag:icarus_$tag"
}
run dvs_seed0_g8_c160  all --dataset dvsgesture --seed 0 --g 8
run dvs_seed1_g8_c160  all --dataset dvsgesture --seed 1 --g 8
run dvs_seed2_g8_c160  all --dataset dvsgesture --seed 2 --g 8
for s in 0 1 2; do run dvs_seed${s}_level4_real_gaps real --dataset dvsgesture --seed $s --g 8 --gap 1; done
run dvs_seed0_level4_shuffled_gaps rand48 --dataset dvsgesture --seed 0 --g 8 --gap 1 --order shuffle
run dvs_seed0_level4_sorted_gaps   rand48 --dataset dvsgesture --seed 0 --g 8 --gap 1 --order sorted
run dvs_seed1_level4_sorted_nogap  rand48 --dataset dvsgesture --seed 1 --g 8 --gap 0 --order sorted
run nmnist_seed0_g8      all        --dataset nmnist --seed 0 --g 8
run nmnist_seed0_g8_gaps $SUB_NM    --dataset nmnist --seed 0 --g 8 --gap 1
run nmnist_seed0_g64     $SUB_NM    --dataset nmnist --seed 0 --g 64
for g in 4 16 32 64; do run dvs_seed0_g${g}_c160 $SUB_DVS --dataset dvsgesture --seed 0 --g $g; done
run dvs_seed0_g8_c20     $SUB_DVS --dataset dvsgesture --seed 0 --g 8 --cols 20
run dvs_seed0_g64_c20    $SUB_DVS --dataset dvsgesture --seed 0 --g 64 --cols 20
run dvs_seed0_g8_noskip  $SUB_DVS --dataset dvsgesture --seed 0 --g 8 --no-skip
$PY 03_rtl/scripts/compare_sims.py $PAIRS | tee "$LOG/sim_compare.log"
