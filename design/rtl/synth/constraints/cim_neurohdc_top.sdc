# cim_neurohdc_top.sdc - constraints of every number in the reports: 100 MHz, input/output delay = period/4, reset false-pathed, BUFX2 drivers / 20 fF loads on the ports
# (the same as scripts/synth_ppa.py's OpenSTA runs and abc.constr), so that pre-route and post-route differ only by the layout.
# The analog macros are library cells (synth/macro/*.lib): their outputs launch 0.3 ns after the clock edge (Liberty arc), Phase 5's constraint.
# UNC: clock uncertainty. 0 reproduces the pre-route numbers; for a signoff run set e.g. 0.15 (setup) / 0.05 (hold) and report both.
if {![info exists UNC_SETUP]} { set UNC_SETUP 0.0 }
if {![info exists UNC_HOLD]}  { set UNC_HOLD  0.0 }
set PERIOD 10.0
create_clock -name clk -period $PERIOD [get_ports clk_i]
set_clock_uncertainty -setup $UNC_SETUP [get_clocks clk]
set_clock_uncertainty -hold  $UNC_HOLD  [get_clocks clk]
# data inputs = all inputs but the clock (Genus / Innovus: remove_from_collection; OpenSTA / OpenROAD: all_inputs -no_clocks)
if {[catch {set DATA_IN [remove_from_collection [all_inputs] [get_ports clk_i]]}]} { set DATA_IN [all_inputs -no_clocks] }
set_input_delay  [expr $PERIOD / 4.0] -clock clk $DATA_IN
set_output_delay [expr $PERIOD / 4.0] -clock clk [all_outputs]
set_false_path -from [get_ports rst_n_i]
set_driving_cell -lib_cell BUFX2 $DATA_IN
set_load 0.02 [all_outputs]
