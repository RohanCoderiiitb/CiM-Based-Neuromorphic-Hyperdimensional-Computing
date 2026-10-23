#!/usr/bin/env bash
# Synthesizability check of the four ablation builds of cim_neurohdc_top (generic Yosys, no liberty): `check -assert` clean, zero latches, flip-flop / gate counts and the longest
# topological path. The analog arrays (cim_macro, hdc_class_array) are black boxes under SYNTHESIS. Real area / timing / power: scripts/synth_ppa.py, synth_power.py.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=results/synthesis; mkdir -p "$OUT"
READ="read_verilog -sv rtl/pkg/*.sv rtl/phase1_snn/*.sv rtl/phase2_hdc/*.sv rtl/phase4_exit/*.sv rtl/phase3_top/*.sv"
for B in "full 1 1" "ee_off 1 0" "fact_off 0 1" "both_off 0 0"; do
  set -- $B
  P="chparam -set FACTORIZED $2 -set EARLY_EXIT_EN $3 -set INSTRUMENT_EN 0 -set CHECK_UNIPOLAR 0 cim_neurohdc_top"
  yosys -p "$READ
    $P
    hierarchy -check -top cim_neurohdc_top
    proc; opt
    memory -nomap; opt
    check -assert
    tee -o $OUT/hdc_$1_stat_specified.txt stat" > "$OUT/hdc_$1_elaboration.log" 2>&1
  if grep -q '\$dlatch\|\$adlatch\|\$dlatchsr' "$OUT/hdc_$1_stat_specified.txt"; then echo "FAIL $1: latch cells"; exit 1; fi
  yosys -p "$READ
    $P
    hierarchy -check -top cim_neurohdc_top
    synth -top cim_neurohdc_top -flatten
    abc -g AND,NAND,OR,NOR,XOR,XNOR,ANDNOT,ORNOT,MUX
    opt_clean
    check -assert
    tee -o $OUT/hdc_$1_gates.txt stat
    tee -o $OUT/hdc_$1_depth.txt ltp -noff" > "$OUT/hdc_$1_generic.log" 2>&1
  echo "$1: check -assert PASS, latches 0, $(grep -E 'Number of cells|cells$' "$OUT/hdc_$1_gates.txt" | head -1 | xargs), longest path $(grep -E 'Longest topological path' "$OUT/hdc_$1_depth.txt" | head -1)"
done
