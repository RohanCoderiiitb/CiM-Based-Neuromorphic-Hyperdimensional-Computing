#!/usr/bin/env bash
# Phase 2-4 lint: `verilator --lint-only -Wall` on (a) the integrated top in each of the four ablation builds, (b) every new block as its own top, (c) the SYNTHESIS view (analog arrays
# black-boxed). Verible (lint + format) runs too when it is installed; this machine does not have it, and the log says so.
# Waivers (all deliberate, listed): IMPORTSTAR - the new modules import hdc_pkg::* at $unit scope (Yosys cannot parse `module m import pkg::*;` and the explicit-list form of 1E was
# not applied to the new files); DECLFILENAME / PINCONNECTEMPTY - an unused debug output left open; UNUSEDPARAM - the packages declare constants a single block does not use.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=results/lint; mkdir -p "$OUT"
PK="rtl/pkg/cim_neurohdc_pkg.sv rtl/pkg/hdc_pkg.sv"
ALL="$PK rtl/phase1_snn/*.sv rtl/phase2_hdc/*.sv rtl/phase4_exit/*.sv rtl/phase3_top/*.sv"
W="-Wall -sv -Wno-IMPORTSTAR -Wno-DECLFILENAME -Wno-PINCONNECTEMPTY -Wno-UNUSEDPARAM"
{
  VB=$(ls -d tools/verible-*/bin 2>/dev/null | head -1 || true); [ -z "$VB" ] && command -v verible-verilog-lint >/dev/null && VB=$(dirname "$(command -v verible-verilog-lint)")
  if [ -n "${VB:-}" ]; then
    echo "== verible-verilog-lint (project rules)"; "$VB"/verible-verilog-lint --rules_config .rules.verible_lint rtl/phase2_hdc/*.sv rtl/phase4_exit/*.sv rtl/phase3_top/*.sv rtl/pkg/hdc_pkg.sv tb/sv/hdc_regress_tb.sv tb/sv/top2_wrap.sv && echo clean
  else
    echo "== verible: NOT INSTALLED on this machine - lint/format of the Phase 2-4 files not run (verilator -Wall below is)"
  fi
  for f in 0 1; do for e in 0 1; do
    echo "== verilator --lint-only $W  cim_neurohdc_top  FACTORIZED=$f EARLY_EXIT_EN=$e"
    verilator --lint-only $W $ALL --top-module cim_neurohdc_top -GFACTORIZED=$f -GEARLY_EXIT_EN=$e && echo "clean (0 warnings, 0 errors)"
  done; done
  echo "== verilator --lint-only: every new block as its own top (default parameters; the recursive top2_tree, like 1E's popcount, is linted through its instances above)"
  for m in hdc_score hdc_class_array hdc_query exit_ctrl; do verilator --lint-only $W $ALL --top-module $m && echo "$m: clean"; done
  echo "== verilator --lint-only -DSYNTHESIS (analog arrays black-boxed; UNDRIVEN/UNUSED waived: artefacts of the empty black box)"
  verilator --lint-only $W -Wno-UNDRIVEN -Wno-UNUSEDSIGNAL -DSYNTHESIS $ALL --top-module cim_neurohdc_top && echo clean
} 2>&1 | tee "$OUT/lint_hdc.log"
