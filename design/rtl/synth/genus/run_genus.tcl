# run_genus.tcl - D1(a): synthesis against the PDK's standard-cell library with Genus (the owner's licence). One build per run:
#     cd <repo>/design/rtl/synth && python prepare_rtl.py --build full && BUILD=full genus -batch -files genus/run_genus.tcl
# Inputs : work/<BUILD>/filelist.f (prepare_rtl.py: package defaults of the build, structural ICG, macros as library cells), the PDK libraries, the macro Liberty files, constraints/*.sdc
# Outputs: results/genus/<BUILD>/{netlist.v, netlist.sdc, area.rpt, power.rpt, timing.rpt, gates.rpt, clock_gating.rpt, qor.rpt}
# Written from the PDK's own genus_new.tcl; NOT run in the repository's environment (no licence there) - adapt option names to your Genus version if it complains.
set BUILD $::env(BUILD)
source [file join [file dirname [info script]] .. pdk.tcl]
set WORK $SYNTH/work/$BUILD
set OUTD $SYNTH/results/genus/$BUILD
file mkdir $OUTD

# --- libraries: synthesis in the FAST library like the PDK example and the pre-route numbers; both corners are signed off in Innovus
set_db init_lib_search_path [list $PDK/lib]
set_db library [list $LIB_FAST $WORK/cim_macro.lib $WORK/hdc_class_array.lib]
# physical hints for the macros (area, pins) - Genus uses the LEF only with -physical; harmless otherwise
set_db lef_library [list $TECH_LEF $CELL_LEF $WORK/cim_macro.lef $WORK/hdc_class_array.lef]

# --- RTL
set files [split [string trim [read [open $WORK/filelist.f]]] "\n"]
set_db hdl_language sv
read_hdl -sv $files
elaborate cim_neurohdc_top

# --- clock gating: the explicit clk_gate_tree cells are TLATNCAX2 instances already (clk_gate_icg.v) and must be kept; Genus may still gate the remaining enabled registers (the Yosys
#     flow did: 40 extra ICGs). Keep the same policy: groups of >= 4 flip-flops.
set_db [get_db designs] .lp_insert_clock_gating true
set_db lp_clock_gating_min_flops 4
set_db lp_clock_gating_cell [get_db [get_db base_cells TLATNCAX2] .name]
set_dont_touch [get_db insts -if {.base_cell.name == TLATNCAX2}]

# --- constraints
read_sdc $SYNTH/constraints/cim_neurohdc_top.sdc

# --- synthesis: generic -> map -> optimise (timing driven; 100 MHz is easy, the result is area / power limited)
syn_generic
syn_map
syn_opt

# --- reports
report_area           > $OUTD/area.rpt
report_gates          > $OUTD/gates.rpt
report_timing -max_paths 5 > $OUTD/timing.rpt
report_power          > $OUTD/power.rpt
report_clock_gating   > $OUTD/clock_gating.rpt
report_qor            > $OUTD/qor.rpt
check_design          > $OUTD/check_design.rpt

# --- hand-off to Innovus
write_hdl -exclude_ilm > $OUTD/netlist.v
write_sdc > $OUTD/netlist.sdc
write_design -innovus -base_name $OUTD/innovus_handoff
exit
