#!/usr/bin/env bash
# ONE COMMAND that reproduces every number in reports/phase1e_report.md (repository root) from a clean checkout (criterion 9):
#     design/rtl/scripts/run_everything.sh            (from the repository root; ~4-6 h on 10 cores, almost all of it the Icarus regression)
#     design/rtl/scripts/run_everything.sh --skip-icarus-regression    (~25 min; criterion 6 is then NOT re-established, the report says so)
# Stages: preflight, lint, Phase 0 Level-1 guard, cocotb unit tests (Verilator + Icarus), Verilator regression, Icarus regression + per-timestep
# comparison, Yosys check, report. Stops at the first failing stage; every stage logs to results/logs/.
set -uo pipefail
cd "$(dirname "$0")/../.."
SKIP_ICARUS=0; [ "${1:-}" = "--skip-icarus-regression" ] && SKIP_ICARUS=1
PY=venv/bin/python; L=design/rtl/results/logs; mkdir -p $L design/rtl/results/regression reports
T0=$(date +%s)
stage() { name=$1; shift; echo "=== [$(( $(date +%s)-T0 ))s] $name"; "$@" > "$L/stage_${name}.log" 2>&1; rc=$?; tail -n 3 "$L/stage_${name}.log"; [ $rc -eq 0 ] || { echo "STAGE FAILED: $name (see $L/stage_${name}.log)"; exit $rc; }; }

# 0. preflight: tools, python env, golden vectors present
for t in verilator iverilog vvp yosys; do command -v $t >/dev/null || { echo "missing tool: $t"; exit 2; }; done
[ -x $PY ] || { echo "create the venv first: python3 -m venv venv && venv/bin/pip install -r design/rtl/requirements.txt"; exit 2; }
VEC=design/reference_model/tb/vectors
head -c 2 $VEC/dvsgesture/events.npz | grep -q PK || { echo "golden vectors missing or not a numpy archive: $VEC/dvsgesture/events.npz"; exit 2; }
ls design/rtl/tools/verible-*/bin/verible-verilog-lint >/dev/null 2>&1 || command -v verible-verilog-lint >/dev/null || { echo "missing verible (put it on PATH or in design/rtl/tools/verible-*/)"; exit 2; }

stage lint            design/rtl/scripts/lint.sh
stage level1_guard    $PY design/rtl/scripts/level1_guard.py
stage unit_tests      $PY design/rtl/tb/cocotb/run_unit_tests.py --sims verilator icarus
stage verilator_regr  bash design/rtl/scripts/run_all_regressions.sh
grep -q "FAIL" $L/stage_verilator_regr.log && { echo "Verilator regression has FAIL lines"; exit 1; }
[ "$(grep -c '^\[PASS\]' $L/stage_verilator_regr.log)" -ge 19 ] || { echo "Verilator regression did not produce all 19 PASS lines"; exit 1; }
if [ $SKIP_ICARUS -eq 0 ]; then
  stage icarus_regr   bash design/rtl/scripts/run_icarus_regressions.sh
  grep -q "DISAGREE\|FAIL" $L/stage_icarus_regr.log && { echo "Icarus regression/comparison failed"; exit 1; }
fi
stage synthesis       design/rtl/scripts/synth_check.sh
stage report          $PY design/rtl/scripts/make_report.py
echo "=== done in $(( $(date +%s)-T0 ))s: reports/phase1e_report.md"
