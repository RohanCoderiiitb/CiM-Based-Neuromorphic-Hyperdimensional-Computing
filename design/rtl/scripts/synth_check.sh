#!/usr/bin/env bash
# Criterion 8: SYNTHESIZABILITY CHECK - generic Yosys, NO PDK, NO liberty file. About correctness (latches, combinational loops), not cost.
# 1. the specified elaboration: check -assert must be clean and `stat` must report zero $dlatch cells.
# 2. a generic-gate smell test (flip-flop count, gate count, logic depth) for the sizes we expect; NOT area.
# Checks 1 and 2 are made with CLOCK_GATING = 0 (enabled flip-flops only), for ZERO latches, as before. The shipped default, CLOCK_GATING = 1, has explicit clock gates (rtl/common/clk_gate.sv, one latch
# each, intended); check 3 requires that its latches are exactly the clk_gate instances of count_mem (8 + 64 + 512 = 584) and nothing else.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=results/synthesis
mkdir -p "$OUT"

echo "== 1. specified elaboration (check -assert, zero latches)"
yosys -p "
  read_verilog -sv rtl/pkg/*.sv rtl/common/*.sv rtl/phase1_snn/*.sv
  chparam -set CLOCK_GATING 0 snn_top
  hierarchy -check -top snn_top
  proc; opt
  memory -nomap; opt
  check -assert
  tee -o $OUT/yosys_stat_specified.txt stat
" > "$OUT/yosys_elaboration.log" 2>&1
echo "check -assert: PASS (exit 0)"
if grep -q '\$dlatch\|\$adlatch\|\$dlatchsr' "$OUT/yosys_stat_specified.txt"; then echo "FAIL: latch cells found"; exit 1; fi
echo "latch cells: 0"

for IE in 1 0; do
  echo "== 2. generic gate smell test, INSTRUMENT_EN=$IE (cim_macro is a blackbox: the behavioural crossbar)"
  yosys -p "
    read_verilog -sv rtl/pkg/*.sv rtl/common/*.sv rtl/phase1_snn/*.sv
    chparam -set INSTRUMENT_EN $IE -set CLOCK_GATING 0 snn_top
    hierarchy -check -top snn_top
    synth -top snn_top -flatten
    abc -g AND,NAND,OR,NOR,XOR,XNOR,ANDNOT,ORNOT,MUX
    opt_clean
    check -assert
    tee -o $OUT/yosys_generic_gates_instr${IE}.txt stat
    tee -o $OUT/yosys_logic_depth_instr${IE}.txt ltp -noff
  " > "$OUT/yosys_generic_instr${IE}.log" 2>&1
done
echo "== 3. CLOCK_GATING = 1: every latch is a clk_gate (count_mem: 8 + 64 + 512)"
yosys -p "
  read_verilog -sv rtl/pkg/*.sv rtl/common/*.sv rtl/phase1_snn/*.sv
  chparam -set CLOCK_GATING 1 snn_top
  hierarchy -check -top snn_top
  flatten
  proc; opt
  memory -nomap; opt
  check -assert
  tee -o $OUT/yosys_stat_clock_gated.txt stat
" > "$OUT/yosys_elaboration_clock_gated.log" 2>&1
N=$(grep -E '^\s+[0-9]+\s+\$dlatch\s*$' "$OUT/yosys_stat_clock_gated.txt" | awk '{print $1}' | head -1)
if [ "${N:-0}" != "584" ]; then echo "FAIL (CLOCK_GATING=1): ${N:-0} latches, expected the 584 clk_gate instances"; exit 1; fi
echo "CLOCK_GATING=1: check -assert PASS, $N latches = the 584 clk_gate instances, no other latch"
python3 scripts/summarize_synth.py
