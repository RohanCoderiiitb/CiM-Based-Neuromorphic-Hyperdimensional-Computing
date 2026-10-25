read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/45_nm_PDK/cadence/cadence_45nm/lib/fast_vdd1v0_basicCells.lib
read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/layout/full/baseline/analog_blackboxes.lib
read_verilog /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa_digital/full/cim_neurohdc_top_flat_buf_fast.v
link_design cim_neurohdc_top
create_clock -name clk -period 10.0 [get_ports clk_i]
set_input_delay [expr 10.0 / 4.0] -clock clk [all_inputs]
set_output_delay [expr 10.0 / 4.0] -clock clk [all_outputs]
set_false_path -from [get_ports rst_n_i]
report_checks -path_delay max -format full_clock_expanded -digits 3 > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/layout/full/baseline/timing_fast.rpt
report_checks -path_delay max -group_path_count 1 -format end -digits 3 > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/layout/full/baseline/end_fast.rpt
report_worst_slack -max -digits 3 > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/layout/full/baseline/worst_fast.rpt
report_tns -digits 3 > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/layout/full/baseline/tns_fast.rpt
report_clock_skew -setup -digits 3 > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/layout/full/baseline/skew_fast.rpt
report_clock_min_period > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/layout/full/baseline/minperiod_fast.rpt
exit
