# flow.tcl - optimised OpenROAD flow (reports/optimised_ppa.md item 2): TWO corners (slow = setup, fast = hold), repair_design before and after CTS, repair_timing -setup/-hold,
# global route, detailed route. env: RUN (run dir with fp.tcl, netlist_pnr.v, macro/ with the LEF+LIB of the macros), STAGES (space separated), PLACE_DENSITY, REPO.
set RUN  $::env(RUN)
set REPO $::env(REPO)
set SYNTH $REPO/design/rtl/synth
set PDK $REPO/45_nm_PDK/cadence/cadence_45nm
source $RUN/fp.tcl
set MAC $RUN/macro
set PLACE_DENSITY [expr {[info exists ::env(PLACE_DENSITY)] ? $::env(PLACE_DENSITY) : 0.6}]
set STAGES [expr {[info exists ::env(STAGES)] ? $::env(STAGES) : "floorplan place cts groute route"}]
set TOPL [expr {[info exists ::env(TOP_ROUTE_LAYER)] ? $::env(TOP_ROUTE_LAYER) : "Metal9"}]
file mkdir $RUN/reports

proc load_design {stage {corners "slow fast"}} {
  global RUN SYNTH PDK MAC
  define_corners {*}$corners
  set ::CORNERS $corners
  read_lef $SYNTH/work/tech_openroad.lef
  read_lef $PDK/lef/gsclib045_macro.lef
  foreach l [glob $MAC/*.lef] { read_lef $l }
  foreach c $corners {
    read_liberty -corner $c $PDK/lib/${c}_vdd1v0_basicCells.lib
    foreach l [glob $MAC/*.lib] { read_liberty -corner $c $l }
  }
  if {$stage eq "netlist"} {
    read_verilog $RUN/netlist_pnr.v
    link_design cim_neurohdc_top
  } else {
    read_db $RUN/$stage.odb
  }
  read_sdc $SYNTH/constraints/cim_neurohdc_top.sdc
  set_dont_use {*XL}
  # the repair steps may not use clock buffers/inverters or the 16x/20x buffers as data buffers (CTS has its own list)
  set_dont_use {CLKBUFX2 CLKBUFX3 CLKBUFX4 CLKBUFX6 CLKBUFX8 CLKBUFX12 CLKBUFX16 CLKBUFX20 CLKINVX1 CLKINVX2 CLKINVX3 CLKINVX4 CLKINVX6 CLKINVX8 CLKINVX12 CLKINVX16 CLKINVX20 BUFX16 BUFX20}
  set_wire_rc -signal -layer Metal3
  set_wire_rc -clock  -layer Metal5
  if {$stage ne "netlist"} { set_routing_layers -signal Metal2-Metal9 -clock Metal2-Metal9 }
}
proc rpt {tag} {
  global RUN
  set f [open $RUN/reports/summary_$tag.txt w]
  puts $f "== $tag"
  puts $f "design area: [rsz::design_area] um^2"
  foreach c $::CORNERS {
    set sc [sta::find_scene $c]
    puts $f "SCENE $c setup_wns_ns [format %.3f [expr {[sta::worst_slack_scene $sc max] * 1e9}]] hold_wns_ns [format %.3f [expr {[sta::worst_slack_scene $sc min] * 1e9}]] setup_tns_ns [format %.3f [expr {[sta::total_negative_slack_scene_cmd $sc max] * 1e9}]] hold_tns_ns [format %.3f [expr {[sta::total_negative_slack_scene_cmd $sc min] * 1e9}]]"
  }
  close $f
  report_design_area > $RUN/reports/area_$tag.rpt
  log_begin $RUN/reports/cells_$tag.rpt
  report_cell_usage
  log_end
  report_worst_slack -max -digits 3 > $RUN/reports/ws_$tag.rpt
  report_worst_slack -min -digits 3 > $RUN/reports/hs_$tag.rpt
  report_tns -digits 3 > $RUN/reports/tns_$tag.rpt
  report_check_types -max_slew -max_capacitance -max_fanout -violators > $RUN/reports/viol_$tag.rpt
}

if {"floorplan" in $STAGES} {
  load_design netlist
  initialize_floorplan -die_area "0 0 $DIE_W $DIE_H" -core_area "$MARGIN $MARGIN [expr {$DIE_W - $MARGIN}] [expr {$DIE_H - $MARGIN}]" -site CoreSite
  make_tracks
  set block [ord::get_db_block]
  set dbu [$block getDbUnitsPerMicron]
  # the standard cells live in the compact block under the macro's pin edge: the rest of the strip under the macro is a hard placement blockage (routing may cross it)
  if {$CORE_W + 2 * $MARGIN < $DIE_W - 1} {
    set bx0 [expr {int(($MARGIN + $CORE_W) * $dbu)}]
    odb::dbBlockage_create $block $bx0 [expr {int($MARGIN * $dbu)}] [expr {int(($DIE_W - $MARGIN) * $dbu)}] [expr {int(($CIM_Y - 0.5) * $dbu)}]
  }
  set MACRO_CELLS {}
  foreach inst [$block getInsts] {
    set mn [[$inst getMaster] getName]
    if {[[$inst getMaster] isBlock]} { lappend MACRO_CELLS $mn }
    if {$mn eq "cim_macro"} { set X $CIM_X; set Y $CIM_Y } elseif {$mn eq "hdc_class_array"} { set X $HDC_X; set Y $HDC_Y } elseif {[info exists ::MAC_${mn}_X]} {
      set X [set ::MAC_${mn}_X]; set Y [set ::MAC_${mn}_Y] } else { continue }
    $inst setOrient R0
    $inst setLocation [expr {int(round($X * $dbu))}] [expr {int(round($Y * $dbu))}]
    $inst setPlacementStatus FIRM
    puts "macro [$inst getName] ($mn) placed at ($X, $Y)"
  }
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
  define_pdn_grid -macro -name macro_grid -cells [lsort -unique $MACRO_CELLS] -grid_over_pg_pins
  add_pdn_connect -grid macro_grid -layers {Metal10 Metal11}
  pdngen
  write_db $RUN/floorplan.odb
}

if {"place" in $STAGES} {
  load_design floorplan slow
  buffer_ports
  global_placement -skip_io -density $PLACE_DENSITY
  place_pins -hor_layers Metal3 -ver_layers Metal4 -exclude top:* -exclude left:[expr {int($CIM_Y) - 2}]-$DIE_H -exclude right:* -exclude bottom:[expr {int($MARGIN + $IO_W) + 1}]-$DIE_W -min_distance 1 -min_distance_in_tracks
  global_placement -routability_driven -density $PLACE_DENSITY
  set PV [expr {[info exists ::env(PLACE_VARIANT)] ? $::env(PLACE_VARIANT) : 2}]
  estimate_parasitics -placement
  if {$PV == 1} {
    repair_design -verbose
    global_placement -skip_initial_place -routability_driven -density $PLACE_DENSITY
    estimate_parasitics -placement
    repair_design -verbose
  } elseif {$PV == 2} {
    repair_design -verbose
    global_placement -skip_initial_place -routability_driven -density $PLACE_DENSITY
    remove_buffers
    buffer_ports
    estimate_parasitics -placement
    repair_design -verbose
  } elseif {$PV == 3} {
    global_placement -skip_initial_place -routability_driven -density $PLACE_DENSITY
    estimate_parasitics -placement
    repair_design -verbose
  }
  if {[catch {detailed_placement -use_diamond_legalizer -max_displacement {3000 600}} msg]} {
    puts "legaliser (diamond) failed: $msg - retrying with the default legaliser"
    detailed_placement -max_displacement {3000 600}
  }
  check_placement -verbose
  estimate_parasitics -placement
  write_db $RUN/place.odb
  rpt place
}

if {"cts" in $STAGES} {
  load_design place
  estimate_parasitics -placement
  clock_tree_synthesis -root_buf CLKBUFX12 -buf_list {CLKBUFX8 CLKBUFX12 CLKBUFX16} {*}[expr {[info exists ::env(CTS_OPTS)] ? $::env(CTS_OPTS) : "-sink_clustering_enable -sink_clustering_size 6 -sink_clustering_max_diameter 30 -distance_between_buffers 80 -no_insertion_delay"}]
  set_propagated_clock [all_clocks]
  estimate_parasitics -placement
  repair_clock_nets
  set_dont_use {CLKBUFX* CLKINVX* BUFX16 BUFX20 INVX16 INVX20 *X20 *X16}
  detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
  estimate_parasitics -placement
  rpt cts_pre_repair
  repair_design -verbose
  repair_timing -setup -setup_margin 0.1 -verbose
  repair_timing -hold -hold_margin 0.05 -verbose
  repair_timing -setup -setup_margin 0.1 -verbose
  detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
  check_placement -verbose
  estimate_parasitics -placement
  write_db $RUN/cts.odb
  rpt cts
  report_clock_skew > $RUN/reports/skew_cts.rpt
}

if {"groute" in $STAGES} {
  load_design cts
  set_propagated_clock [all_clocks]
  estimate_parasitics -placement
  set_global_routing_layer_adjustment Metal2-Metal9 0.2
  global_route -guide_file $RUN/route.guide -congestion_iterations 60 -allow_congestion -congestion_report_file $RUN/reports/congestion.rpt
  estimate_parasitics -global_routing
  repair_design -verbose
  repair_timing -setup -setup_margin 0.4 -verbose
  repair_timing -hold -hold_margin 0.15 -verbose
  repair_timing -setup -setup_margin 0.4 -verbose
  detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
  check_placement -verbose
  global_route -guide_file $RUN/route.guide -start_incremental
  global_route -end_incremental -congestion_iterations 30 -allow_congestion
  estimate_parasitics -global_routing -spef_file $RUN/groute.spef
  write_db $RUN/groute.odb
  write_verilog $RUN/groute.v
  rpt groute
}

if {"route" in $STAGES} {
  if {"groute" ni $STAGES} {
    load_design groute
    set_propagated_clock [all_clocks]
  }
  detailed_route -output_drc $RUN/reports/drc_route.rpt -droute_end_iter 20 -verbose 1
  write_db $RUN/routed.odb
  write_verilog $RUN/routed.v
  write_def $RUN/routed.def
  estimate_parasitics -global_routing -spef_file $RUN/routed.spef
  rpt routed
  report_clock_skew > $RUN/reports/skew_routed.rpt
}
puts "STAGES DONE: $STAGES"
