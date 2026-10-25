# run_flow.tcl - OpenROAD place-and-route of the accelerator with the analog crossbar as a hard macro, on the PDK's LEF / Liberty.
#   openroad -no_init -exit run_flow.tcl      (env: BUILD, STAGES=floorplan,place,cts,route  default all; WORK = synth/work/$BUILD)
# Netlist: the Yosys netlist (make_pnr_netlist.py). Every stage leaves a database (results/openroad/$BUILD/<stage>.odb) and reports, so a stage can be re-run alone.
# Parasitics: OpenROAD estimates RC from the layers' RESISTANCE / CAPACITANCE in the PDK's tech LEF (set_wire_rc) on the placed (pre_cts, post_cts) and global-routed (routed) wiring.
# This is NOT a Quantus extraction: no coupling capacitance, no via resistance from a field solver (OpenRCX needs a rules file the PDK does not ship). It is labelled so in the report.
set BUILD $::env(BUILD)
set REPO [file normalize [file join [file dirname [info script]] .. .. .. ..]]
source $REPO/design/rtl/synth/pdk.tcl
set WORK $SYNTH/work/$BUILD
set OUTD $SYNTH/results/openroad/$BUILD
file mkdir $OUTD/reports
source $SYNTH/innovus/floorplan_params.tcl
if {![info exists ::env(PLACE_DENSITY)]} { set PLACE_DENSITY 0.55 } else { set PLACE_DENSITY $::env(PLACE_DENSITY) }
set STAGES [expr {[info exists ::env(STAGES)] ? [split $::env(STAGES) ","] : {floorplan place cts route}}]

proc load_design {stage} {
  global PDK TECH_LEF_OR CELL_LEF LIB_FAST LIB_SLOW WORK SYNTH OUTD
  read_lef $TECH_LEF_OR
  read_lef $CELL_LEF
  read_lef $WORK/cim_macro.lef
  read_lef $WORK/hdc_class_array.lef
  read_liberty $LIB_FAST        ;# the flow optimises in the FAST library (the one the netlist was mapped in, and the PDK example's); both corners are analysed afterwards. In the SLOW corner the Yosys XL cells violate max_transition on ~25k nets: reported, not repaired (see the report)
  read_liberty $WORK/cim_macro.lib
  read_liberty $WORK/hdc_class_array.lib
  if {$stage eq "netlist"} {
    read_verilog $WORK/pnr/netlist.v
    link_design cim_neurohdc_top
  } else {
    read_db $OUTD/$stage.odb
  }
  read_sdc $SYNTH/constraints/cim_neurohdc_top.sdc
}
proc rc_setup {} {
  set_wire_rc -signal -layer Metal3
  set_wire_rc -clock  -layer Metal5
  set_routing_layers -signal Metal2-Metal9 -clock Metal2-Metal9
}
proc area_report {tag} {
  global OUTD
  log_begin $OUTD/reports/area_$tag.rpt
  report_design_area
  report_cell_usage
  log_end
}

# ------------------------------------------------------------------ floorplan: explicit die, macros first
if {"floorplan" in $STAGES} {
  load_design netlist
  initialize_floorplan -die_area "0 0 $DIE_W $DIE_H" -core_area "$MARGIN $MARGIN [expr {$DIE_W - $MARGIN}] [expr {$DIE_H - $MARGIN}]" -site CoreSite
  make_tracks
  set block [ord::get_db_block]
  set dbu [$block getDbUnitsPerMicron]
  foreach inst [$block getInsts] {
    set mn [[$inst getMaster] getName]
    if {$mn eq "cim_macro"} { set X $CIM_X; set Y $CIM_Y } elseif {$mn eq "hdc_class_array"} { set X $HDC_X; set Y $HDC_Y } else { continue }
    $inst setOrient R0
    $inst setLocation [expr {int(round($X * $dbu))}] [expr {int(round($Y * $dbu))}]
    $inst setPlacementStatus FIRM
    puts "macro [$inst getName] ($mn) placed at ($X, $Y)"
  }
  # power grid: Metal1 rails, Metal10 stripes (the macros' own supply stripes are Metal10, their OBS blocks the core Metal10 stripes over them), Metal11 straps cross the macros
  add_global_connection -net VDD -pin_pattern {^VDD$} -power
  add_global_connection -net VSS -pin_pattern {^VSS$} -ground
  global_connect
  set_voltage_domain -name CORE -power VDD -ground VSS
  define_pdn_grid -name core_grid -pins {Metal11}
  add_pdn_stripe -grid core_grid -layer Metal1 -followpins -width 0.12
  add_pdn_stripe -grid core_grid -layer Metal10 -width 1.0 -pitch 16.0 -offset 3.0 -nets {VDD VSS}
  add_pdn_stripe -grid core_grid -layer Metal11 -width 2.0 -pitch 40.0 -offset 6.0 -nets {VDD VSS}
  add_pdn_connect -grid core_grid -layers {Metal1 Metal10}
  add_pdn_connect -grid core_grid -layers {Metal10 Metal11}
  define_pdn_grid -macro -name macro_grid -cells {cim_macro hdc_class_array} -grid_over_pg_pins
  add_pdn_connect -grid macro_grid -layers {Metal10 Metal11}
  pdngen
  place_pins -hor_layers Metal3 -ver_layers Metal4 -random
  write_db $OUTD/floorplan.odb
  area_report floorplan
}

# ------------------------------------------------------------------ placement
if {"place" in $STAGES} {
  load_design floorplan
  rc_setup
  global_placement -skip_io -density $PLACE_DENSITY
  place_pins -hor_layers Metal3 -ver_layers Metal4
  global_placement -density $PLACE_DENSITY
  estimate_parasitics -placement
  repair_design
  write_db $OUTD/gpl_repaired.odb
  detailed_placement
  if {[catch {check_placement -verbose} msg]} {
    puts "check_placement failed once ($msg): legalising again with a wider search"
    detailed_placement -max_displacement {3000 600}
    check_placement -verbose
  }
  write_db $OUTD/place.odb
  write_verilog $OUTD/pre_cts.v
  write_def $OUTD/pre_cts.def
  area_report pre_cts
  estimate_parasitics -placement
  report_checks -path_delay max -digits 3 > $OUTD/reports/timing_pre_cts.rpt
  report_clock_skew > $OUTD/reports/clock_skew_pre_cts.rpt
  report_wns > $OUTD/reports/wns_pre_cts.rpt
}

# ------------------------------------------------------------------ clock tree synthesis through the clock gates
if {"cts" in $STAGES} {
  load_design place
  rc_setup
  estimate_parasitics -placement
  clock_tree_synthesis -root_buf CLKBUFX8 -buf_list {CLKBUFX2 CLKBUFX3 CLKBUFX4 CLKBUFX6 CLKBUFX8} -sink_clustering_enable -sink_clustering_size 20 -sink_clustering_max_diameter 60 -balance_levels
  set_propagated_clock [all_clocks]
  estimate_parasitics -placement
  repair_clock_nets
  detailed_placement
  repair_timing -setup -hold -setup_margin 0.0 -hold_margin 0.05
  detailed_placement
  check_placement -verbose
  estimate_parasitics -placement
  write_db $OUTD/cts.odb
  write_verilog $OUTD/post_cts.v
  write_def $OUTD/post_cts.def
  area_report post_cts
  report_checks -path_delay max -digits 3 > $OUTD/reports/timing_post_cts.rpt
  report_clock_skew > $OUTD/reports/clock_skew_post_cts.rpt
  log_begin $OUTD/reports/cts.rpt
  report_cts
  log_end
}

# ------------------------------------------------------------------ global routing only: wire paths fixed by the global router, RC estimated on them (no detailed routing)
if {"groute" in $STAGES} {
  load_design cts
  rc_setup
  set_propagated_clock [all_clocks]
  global_route -guide_file $OUTD/route.guide -congestion_iterations 50 -allow_congestion
  estimate_parasitics -global_routing
  write_db $OUTD/groute.odb
  write_verilog $OUTD/groute.v
  write_def $OUTD/groute.def
  area_report groute
  report_checks -path_delay max -digits 3 > $OUTD/reports/timing_groute.rpt
  report_clock_skew > $OUTD/reports/clock_skew_groute.rpt
  report_wns > $OUTD/reports/wns_groute.rpt
}

# ------------------------------------------------------------------ detailed routing (did not converge in the time available on this design: see the report)
if {"route" in $STAGES} {
  load_design cts
  rc_setup
  set_propagated_clock [all_clocks]
  global_route -guide_file $OUTD/route.guide -congestion_iterations 50 -allow_congestion
  estimate_parasitics -global_routing
  repair_timing -setup -hold -setup_margin 0.0 -hold_margin 0.05
  detailed_route -output_drc $OUTD/reports/drc_route.rpt -verbose 1
  write_db $OUTD/routed.odb
  write_verilog $OUTD/routed.v
  write_def $OUTD/routed.def
  estimate_parasitics -global_routing
  area_report routed
  report_checks -path_delay max -digits 3 > $OUTD/reports/timing_routed.rpt
  report_clock_skew > $OUTD/reports/clock_skew_routed.rpt
  report_wns > $OUTD/reports/wns_routed.rpt
}
puts "STAGES DONE: $STAGES"
