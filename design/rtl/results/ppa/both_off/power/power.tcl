read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/ASIC-Optimization-FFT-Hardware/45_nm_PDK/cadence/cadence_45nm/lib/fast_vdd1v0_basicCells.lib
read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/both_off/power/analog_blackboxes.lib
read_verilog /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/both_off/power/cim_neurohdc_top_flat_buf_fast.v
link_design cim_neurohdc_top
create_clock -name clk -period 10.0 [get_ports clk_i]
read_vcd -scope hdc_gate_tb/dut /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/both_off/power/activity.vcd
report_activity_annotation > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/both_off/power/annotation.rpt
report_power > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/both_off/power/power.rpt
exit
