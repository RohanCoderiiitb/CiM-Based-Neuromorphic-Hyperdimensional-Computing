#!/usr/bin/env bash
# Final regression of the optimised design, SNN level (Levels 4 and 5, g sweep, column-mode sweep, N-MNIST) on Verilator, then the SAME configurations on Icarus (subsets where marked) and the
# per-timestep Verilator-vs-Icarus comparison. g = 4 / 40 columns is the design point; the other g and column modes are the sweeps the earlier regression ran.
#   design/rtl/scripts/run_final_snn_regressions.sh [--no-icarus]
set -uo pipefail
cd "$(dirname "$0")/../../.."
PY=venv/bin/python; LOG=design/rtl/results/logs/final; mkdir -p $LOG
RV="$PY design/rtl/scripts/run_regression.py --sim verilator"
RI="$PY design/rtl/scripts/run_regression.py --sim icarus --chunks 10"
PAIRS=""
run() { sim=$1; tag=$2; shift 2; if [ "$sim" = v ]; then $RV --tag "$tag" "$@" > "$LOG/$tag.log" 2>&1; else $RI --tag "icarus_$tag" "$@" > "$LOG/icarus_$tag.log" 2>&1; fi; tail -1 "$LOG/${sim/i/icarus_}$tag.log" 2>/dev/null; }
CFGS=(
 "f_dvs_s0_g4_c40|--dataset dvsgesture --seed 0 --rows all --g 4"
 "f_dvs_s1_g4_c40|--dataset dvsgesture --seed 1 --rows all --g 4"
 "f_dvs_s2_g4_c40|--dataset dvsgesture --seed 2 --rows all --g 4"
 "f_dvs_s0_g8_c160|--dataset dvsgesture --seed 0 --rows all --g 8 --cols 160"
 "f_dvs_s0_g16_c40|--dataset dvsgesture --seed 0 --rows all --g 16"
 "f_dvs_s0_g32_c40|--dataset dvsgesture --seed 0 --rows all --g 32"
 "f_dvs_s0_g64_c40|--dataset dvsgesture --seed 0 --rows all --g 64"
 "f_dvs_s0_g4_c20|--dataset dvsgesture --seed 0 --rows all --g 4 --cols 20"
 "f_dvs_s0_g64_c20|--dataset dvsgesture --seed 0 --rows all --g 64 --cols 20"
 "f_dvs_s0_g4_c160|--dataset dvsgesture --seed 0 --rows all --g 4 --cols 160"
 "f_l4_real_gaps_s0|--dataset dvsgesture --seed 0 --rows real --g 4 --gap 1"
 "f_l4_real_gaps_s1|--dataset dvsgesture --seed 1 --rows real --g 4 --gap 1"
 "f_l4_real_gaps_s2|--dataset dvsgesture --seed 2 --rows real --g 4 --gap 1"
 "f_l4_shuffled_gaps|--dataset dvsgesture --seed 0 --rows rand48 --g 4 --gap 1 --order shuffle"
 "f_l4_sorted_gaps|--dataset dvsgesture --seed 0 --rows rand48 --g 4 --gap 1 --order sorted"
 "f_l4_sorted_nogap_s1|--dataset dvsgesture --seed 1 --rows rand48 --g 4 --gap 0 --order sorted"
 "f_nmnist_g4|--dataset nmnist --seed 0 --rows all --g 4"
 "f_nmnist_g4_gaps|--dataset nmnist --seed 0 --rows all --g 4 --gap 1"
 "f_nmnist_g64|--dataset nmnist --seed 0 --rows all --g 64"
)
# warm-up builds, serially (parallel runs sharing a build directory race on the link step)
for g in 4 8 16 32 64; do for c in 40 160 20; do $RV --tag warm --dataset dvsgesture --seed 0 --rows first1 --g $g --cols $c > /dev/null 2>&1; done; done
n=0
for cfg in "${CFGS[@]}"; do
  tag=${cfg%%|*}; args=${cfg#*|}
  ( $RV --tag "$tag" $args > "$LOG/$tag.log" 2>&1; tail -1 "$LOG/$tag.log" ) &
  n=$((n+1)); if [ $((n % 4)) -eq 0 ]; then wait; fi
done
wait
if [ "${1:-}" != "--no-icarus" ]; then
  for cfg in "${CFGS[@]}"; do
    tag=${cfg%%|*}; args=${cfg#*|}
    case "$args" in *"--rows all"*) iargs=${args/--rows all/--rows rand48};; *) iargs=$args;; esac
    $RV --tag "sub_$tag" $iargs > "$LOG/sub_$tag.log" 2>&1
    $RI --tag "icarus_$tag" $iargs > "$LOG/icarus_$tag.log" 2>&1; tail -1 "$LOG/icarus_$tag.log"
    PAIRS="$PAIRS sub_$tag:icarus_$tag"
  done
  $PY design/rtl/scripts/compare_sims.py $PAIRS > "$LOG/compare_sims.log" 2>&1; tail -3 "$LOG/compare_sims.log"
fi
