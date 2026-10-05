#!/usr/bin/env bash
# Criterion 5: Verible lint + format check and `verilator --lint-only -Wall` (including its LATCH warnings) must all be clean.
set -euo pipefail
cd "$(dirname "$0")/.."
VB=$(ls -d tools/verible-*/bin 2>/dev/null | head -1 || true)
[ -z "$VB" ] && VB=$(dirname "$(command -v verible-verilog-lint)")
OUT=results/lint; mkdir -p "$OUT"
FILES="rtl/pkg/*.sv rtl/phase1_snn/*.sv tb/sv/*.sv"
{
  echo "== verible-verilog-lint (project rules: .rules.verible_lint)"
  "$VB"/verible-verilog-lint --rules_config .rules.verible_lint $FILES && echo "clean"
  echo "== verible-verilog-format --verify (column limit 180)"
  for f in $FILES; do "$VB"/verible-verilog-format --verify --column_limit 180 "$f" >/dev/null || { echo "NOT FORMATTED: $f"; exit 1; }; done; echo "clean"
  echo "== verilator --lint-only -Wall snn_top (design)"
  verilator --lint-only -Wall -sv rtl/pkg/cim_neurohdc_pkg.sv rtl/phase1_snn/*.sv --top-module snn_top && echo "clean (0 warnings, 0 errors)"
  echo "== verilator --lint-only -Wall per block (every module except the recursive parameterised popcount, which is linted through its instances, as its own top; UNUSEDPARAM waived: the shared package declares constants a single block does not use)"
  for m in addr_gen count_mem event_ctr plane_seq cim_macro weight_load shift_accum if_neuron_array spike_reg snn_ctrl; do
    verilator --lint-only -Wall -sv rtl/pkg/cim_neurohdc_pkg.sv rtl/phase1_snn/*.sv -Wno-UNUSEDPARAM --top-module $m && echo "$m: clean"
  done
  echo "== verilator --lint-only -Wall -DSYNTHESIS (crossbar blackboxed; UNDRIVEN/UNUSED waived: they are artefacts of the empty blackbox)"
  verilator --lint-only -Wall -Wno-UNDRIVEN -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -DSYNTHESIS -sv rtl/pkg/cim_neurohdc_pkg.sv rtl/phase1_snn/*.sv --top-module snn_top && echo "clean"
} 2>&1 | tee "$OUT/lint.log"
