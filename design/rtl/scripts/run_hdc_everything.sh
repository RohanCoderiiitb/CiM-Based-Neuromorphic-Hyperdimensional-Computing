#!/usr/bin/env bash
# ONE COMMAND for Phases 2-5 (called by run_everything.sh): reference tests, lint of the four ablation builds, Yosys elaboration check, cocotb unit tests of the new blocks on both
# simulators, the Verilator regression matrix (+ its extra runs), the Icarus subset matrix with its Verilator twins, the comparisons, synthesis (area / timing), gate-level power,
# the Phase 5 combination, and the three reports.
#     design/rtl/scripts/run_hdc_everything.sh                     (~6-8 h on 10 cores; the Icarus matrix and the gate-level power runs are most of it)
#     design/rtl/scripts/run_hdc_everything.sh --skip-icarus       (~3 h; the Verilator-vs-Icarus agreement is then NOT re-established)
set -uo pipefail
cd "$(dirname "$0")/../../.."
SKIP_ICARUS=0; [ "${1:-}" = "--skip-icarus" ] && SKIP_ICARUS=1
PY=venv/bin/python; R=design/rtl; L=$R/results/logs; mkdir -p $L $R/results/hdc $R/results/ppa reports
T0=$(date +%s)
stage() { name=$1; shift; echo "=== [$(( $(date +%s)-T0 ))s] $name"; "$@" > "$L/stage_${name}.log" 2>&1; rc=$?; tail -n 3 "$L/stage_${name}.log"; [ $rc -eq 0 ] || { echo "STAGE FAILED: $name (see $L/stage_${name}.log)"; exit $rc; }; }

[ -x $R/tools/sta ] || echo "NOTE: $R/tools/sta (OpenSTA) is missing - the synthesis / power stages will fail; see reports/phase5_ppa.md section 'Reproduce' for how it was built"
stage ref_tests       $PY -m pytest design/reference_model/tests -q
stage lint_hdc        $R/scripts/lint_hdc.sh
stage synth_check_hdc $R/scripts/synth_check_hdc.sh
stage unit_tests_hdc  $PY $R/tb/cocotb/run_unit_tests.py --sims verilator icarus --only top2_tree exit_ctrl hdc_query
stage matrix_main     $PY $R/scripts/run_hdc_matrix.py --sim verilator --set main
stage matrix_extra    $PY $R/scripts/run_hdc_matrix.py --sim verilator --set extra
if [ $SKIP_ICARUS -eq 0 ]; then
  stage matrix_icarus   $PY $R/scripts/run_hdc_matrix.py --sim icarus --set main
  stage matrix_icarus_x $PY $R/scripts/run_hdc_matrix.py --sim icarus --set extra
  stage matrix_twin     $PY $R/scripts/run_hdc_matrix.py --sim verilator --set twin
fi
stage compare         $PY $R/scripts/hdc_compare_all.py
stage synth_ppa       $PY $R/scripts/synth_ppa.py
stage synth_power     $PY $R/scripts/synth_power.py
stage phase5          $PY $R/scripts/phase5_ppa.py
stage reports         $PY $R/scripts/make_report_hdc.py
echo "=== done in $(( $(date +%s)-T0 ))s: reports/phase234_report.md, reports/phase5_ppa.md"
