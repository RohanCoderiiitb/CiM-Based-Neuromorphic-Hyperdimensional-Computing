        read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/ASIC-Optimization-FFT-Hardware/45_nm_PDK/cadence/cadence_45nm/lib/fast_vdd1v0_basicCells.lib
read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/full/analog_blackboxes.lib

        read_verilog /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/full/cim_neurohdc_top_flat_plain_fast.v
        link_design cim_neurohdc_top
        create_clock -name clk -period 10.0 [get_ports clk_i]
        set_input_delay  [expr 10.0 / 4.0] -clock clk [all_inputs]
        set_output_delay [expr 10.0 / 4.0] -clock clk [all_outputs]
        set_false_path -from [get_ports rst_n_i]
        report_checks -path_delay max -format full_clock_expanded -digits 3 > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/full/timing_flat_plain_fast.rpt
        report_checks -path_delay max -group_path_count 12 -unique_paths_to_endpoint -format end -digits 3 > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/full/endpoints_flat_plain_fast.rpt
        report_clock_min_period > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/full/minperiod_flat_plain_fast.rpt
        exit
