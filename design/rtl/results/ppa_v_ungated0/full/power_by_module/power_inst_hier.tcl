read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/ASIC-Optimization-FFT-Hardware/45_nm_PDK/cadence/cadence_45nm/lib/fast_vdd1v0_basicCells.lib
read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa_v_ungated0/full/power_by_module/analog_blackboxes.lib
read_verilog /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa_v_ungated0/full/power_by_module/cim_neurohdc_top_hier_buf_fast.v
link_design cim_neurohdc_top
create_clock -name clk -period 10.0 [get_ports clk_i]
read_vcd -scope hdc_gate_tb/dut /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa_v_ungated0/full/power_by_module/activity.vcd
report_power > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa_v_ungated0/full/power_by_module/power_total_hier.rpt
set leaf [get_cells -hierarchical -filter "is_hierarchical == 0" *]
report_power -instances $leaf > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa_v_ungated0/full/power_by_module/power_inst_hier.rpt
set fh [open /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa_v_ungated0/full/power_by_module/refs_hier.txt w]
foreach c $leaf { puts $fh "[get_full_name $c] [get_property $c ref_name]" }
close $fh
exit
