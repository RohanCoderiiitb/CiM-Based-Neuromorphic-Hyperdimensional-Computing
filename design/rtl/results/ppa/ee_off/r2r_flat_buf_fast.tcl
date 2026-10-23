        read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/ASIC-Optimization-FFT-Hardware/45_nm_PDK/cadence/cadence_45nm/lib/fast_vdd1v0_basicCells.lib
read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/ee_off/analog_blackboxes.lib

        read_verilog /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/ee_off/cim_neurohdc_top_flat_buf_fast.v
        link_design cim_neurohdc_top
        create_clock -name clk -period 10.0 [get_ports clk_i]
        report_checks -path_delay max -from [all_registers -clock_pins] -to [all_registers -data_pins] -format full -digits 3 > /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/results/ppa/ee_off/r2r_flat_buf_fast.rpt
        exit
