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
# RD_OPTS (the large chip, e.g. "-slew_margin 20 -cap_margin 20"): extra options of every repair_design (design-rule repair with margin below the library max slew / cap)
set ::RD_OPTS [expr {[info exists ::env(RD_OPTS)] ? $::env(RD_OPTS) : ""}]
# GPL_TD=1 (the large chip): timing-driven global placement (net weights from STA pull the critical count-memory -> plane-sequencer logic together)
set ::GPL_TD [expr {[info exists ::env(GPL_TD)] && $::env(GPL_TD) ? "-timing_driven" : ""}]
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
  array set MN {}
  foreach inst [$block getInsts] {
    set mn [[$inst getMaster] getName]
    if {[[$inst getMaster] isBlock]} { lappend MACRO_CELLS $mn }
    if {$mn eq "cim_macro"} { set X $CIM_X; set Y $CIM_Y } elseif {$mn eq "hdc_class_array"} { set X $HDC_X; set Y $HDC_Y } elseif {[info exists ::MAC_${mn}_X]} {
      set X [set ::MAC_${mn}_X]; set Y [set ::MAC_${mn}_Y] } else { continue }
    # several instances of one macro sit side by side, 5 um apart; the counter banks form a block: one column per bank, one row per ping-pong set
    if {![info exists MN($mn)]} { set MN($mn) 0 } else { incr MN($mn) }
    if {[regexp {g_set.*?(\d+).*?g_lane.*?(\d+).*?g_bank.*?(\d+)} [$inst getName] -> cset clane cbank]} {
      set X [expr {$X + $cbank * ([[$inst getMaster] getWidth] / double($dbu) + 5.0)}]
      # lane-private counters: one row per (lane, set), lane-major (a lane's 8 macros in two adjacent rows, next to its own ingest logic), 5 um apart (the SRAMs block Metal1-4 only)
      set Y [expr {$Y + ($clane * 2 + $cset) * ([[$inst getMaster] getHeight] / double($dbu) + 5.0)}]
    } elseif {[regexp {g_set.*?(\d+).*?g_bank.*?(\d+)} [$inst getName] -> cset cbank]} {
      set X [expr {$X + $cbank * ([[$inst getMaster] getWidth] / double($dbu) + 5.0)}]
      set Y [expr {$Y + $cset * ([[$inst getMaster] getHeight] / double($dbu) + 5.0)}]
    } else {
      set X [expr {$X + $MN($mn) * ([[$inst getMaster] getWidth] / double($dbu) + 5.0)}]
    }
    # HDC_ORI (e.g. MX): the large chip hangs the class memory from the top of the digital region, so its pin edge (the LEF top) is mirrored to face the logic below
    if {$mn eq "hdc_class_array" && [info exists ::env(HDC_ORI)]} { set ORI $::env(HDC_ORI) }
    if {![info exists ORI]} { set ORI R0 }
    $inst setOrient $ORI
    unset ORI
    $inst setLocation [expr {int(round($X * $dbu))}] [expr {int(round($Y * $dbu))}]
    $inst setPlacementStatus FIRM
    set bb [$inst getBBox]
    puts "macro [$inst getName] ($mn) placed at ($X, $Y) [$inst getOrient] bbox [expr {[$bb xMin]/double($dbu)}] [expr {[$bb yMin]/double($dbu)}] [expr {[$bb xMax]/double($dbu)}] [expr {[$bb yMax]/double($dbu)}]"
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
  # the event (AER) pins go to the stretch of the bottom edge beside the counter-bank block (fp.tcl: EV_X0 .. EV_X1)
  if {[info exists EV_X0]} {
    set evpins {}
    foreach bt [[ord::get_db_block] getBTerms] { if {[regexp {^(ev|evx)_(aer_i|valid_i|ready_o)} [$bt getName]]} { lappend evpins [$bt getName] } }
    set_io_pin_constraint -region bottom:$EV_X0-$EV_X1 -pin_names $evpins
  }
  # CM_PINS_RIGHT (the large chip): the wide class-image port goes to the right edge of the digital region, beside the class memory, instead of crowding the bottom edge
  set rexcl "right:*"
  if {[info exists ::env(CM_PINS_RIGHT)] && $::env(CM_PINS_RIGHT)} {
    set cmpins {}
    foreach bt [[ord::get_db_block] getBTerms] { if {[regexp {^cm_(data|addr|sel|we)_i} [$bt getName]]} { lappend cmpins [$bt getName] } }
    set_io_pin_constraint -region right:[expr {int($MARGIN) + 1}]-[expr {int($CIM_Y) - 2}] -pin_names $cmpins
    set rexcl "right:[expr {int($CIM_Y) - 2}]-$DIE_H"
  }
  place_pins -hor_layers Metal3 -ver_layers Metal4 -exclude top:* -exclude left:[expr {int($CIM_Y) - 2}]-$DIE_H -exclude $rexcl -exclude bottom:[expr {int($MARGIN + $IO_W) + 1}]-$DIE_W -min_distance 1 -min_distance_in_tracks
  global_placement -routability_driven {*}$::GPL_TD -density $PLACE_DENSITY
  set PV [expr {[info exists ::env(PLACE_VARIANT)] ? $::env(PLACE_VARIANT) : 2}]
  estimate_parasitics -placement
  if {$PV == 1} {
    repair_design -verbose {*}$::RD_OPTS
    global_placement -skip_initial_place -routability_driven {*}$::GPL_TD -density $PLACE_DENSITY
    estimate_parasitics -placement
    repair_design -verbose {*}$::RD_OPTS
  } elseif {$PV == 2} {
    repair_design -verbose {*}$::RD_OPTS
    global_placement -skip_initial_place -routability_driven {*}$::GPL_TD -density $PLACE_DENSITY
    remove_buffers
    buffer_ports
    estimate_parasitics -placement
    repair_design -verbose {*}$::RD_OPTS
  } elseif {$PV == 3} {
    global_placement -skip_initial_place -routability_driven {*}$::GPL_TD -density $PLACE_DENSITY
    estimate_parasitics -placement
    repair_design -verbose {*}$::RD_OPTS
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
  clock_tree_synthesis -root_buf [expr {[info exists ::env(CTS_ROOT)] ? $::env(CTS_ROOT) : "CLKBUFX12"}] -buf_list [expr {[info exists ::env(CTS_BUFS)] ? $::env(CTS_BUFS) : {CLKBUFX8 CLKBUFX12 CLKBUFX16}}] {*}[expr {[info exists ::env(CTS_OPTS)] ? $::env(CTS_OPTS) : "-sink_clustering_enable -sink_clustering_size 6 -sink_clustering_max_diameter 30 -distance_between_buffers 80 -no_insertion_delay"}]
  set_propagated_clock [all_clocks]
  estimate_parasitics -placement
  repair_clock_nets
  set_dont_use {CLKBUFX* CLKINVX* BUFX16 BUFX20 INVX16 INVX20 *X20 *X16}
  detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
  estimate_parasitics -placement
  rpt cts_pre_repair
  repair_design -verbose {*}$::RD_OPTS
  repair_timing -setup -setup_margin 0.1 -verbose
  repair_timing -hold -hold_margin 0.05 -verbose
  repair_timing -setup -setup_margin 0.1 -verbose
  detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
  # CTS_ITERS (the large chip): legalising the repair buffers displaces cells (up to ~200 um near the counter SRAMs) and undoes the repair; repeat repair + legalisation
  for {set it 0} {$it < [expr {[info exists ::env(CTS_ITERS)] ? $::env(CTS_ITERS) : 0}]} {incr it} {
    estimate_parasitics -placement
    rpt cts_iter$it
    repair_design -verbose {*}$::RD_OPTS
    repair_timing -setup -setup_margin 0.1 -verbose
    repair_timing -hold -hold_margin 0.05 -verbose
    repair_timing -setup -setup_margin 0.1 -verbose
    detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
  }
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
  repair_design -verbose {*}$::RD_OPTS
  set GR_SETUP [expr {[info exists ::env(GR_SETUP_MARGIN)] ? $::env(GR_SETUP_MARGIN) : 0.4}]
  set GR_HOLD  [expr {[info exists ::env(GR_HOLD_MARGIN)]  ? $::env(GR_HOLD_MARGIN)  : 0.15}]
  repair_timing -setup -setup_margin $GR_SETUP -verbose
  repair_timing -hold -hold_margin $GR_HOLD -verbose
  repair_timing -setup -setup_margin $GR_SETUP -verbose
  detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
  # GR_FINAL_RD (the large chip): the timing repair above inserts buffers that no design-rule repair sees; repair slew / cap once more (placement parasitics) and re-legalise
  if {[info exists ::env(GR_FINAL_RD)] && $::env(GR_FINAL_RD)} {
    estimate_parasitics -placement
    repair_design -verbose {*}$::RD_OPTS
    detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
  }
  check_placement -verbose
  global_route -guide_file $RUN/route.guide -start_incremental
  global_route -end_incremental -congestion_iterations 30 -allow_congestion
  # GR_EXTRA (the large chip): further setup/hold repair rounds on the routed parasitics, each legalised and incrementally re-routed
  # (placement parasitics: after an incremental route the global-route trees of moved cells can be incomplete; the sign-off below uses the global-route parasitics)
  for {set it 0} {$it < [expr {[info exists ::env(GR_EXTRA)] ? $::env(GR_EXTRA) : 0}]} {incr it} {
    estimate_parasitics -placement
    repair_timing -setup -setup_margin $GR_SETUP -verbose
    repair_timing -hold -hold_margin $GR_HOLD -verbose
    repair_timing -setup -setup_margin $GR_SETUP -verbose
    detailed_placement -use_diamond_legalizer -max_displacement {3000 600}
    check_placement -verbose
    global_route -guide_file $RUN/route.guide -start_incremental
    global_route -end_incremental -congestion_iterations 30 -allow_congestion
  }
  estimate_parasitics -global_routing -spef_file $RUN/groute.spef
  write_db $RUN/groute.odb
  write_verilog $RUN/groute.v
  rpt groute
}

# eco (on request only, STAGES=eco): a further setup/hold repair on the global-route parasitics of an existing groute.odb, legalised and incrementally re-routed; overwrites groute.*
if {"eco" in $STAGES} {
  load_design groute
  set_propagated_clock [all_clocks]
  set_global_routing_layer_adjustment Metal2-Metal9 0.2
  global_route -guide_file $RUN/route.guide -congestion_iterations 60 -allow_congestion
  estimate_parasitics -global_routing
  rpt eco_pre
  set ES [expr {[info exists ::env(ECO_SETUP_MARGIN)] ? $::env(ECO_SETUP_MARGIN) : 0.4}]
  repair_design -verbose {*}$::RD_OPTS
  repair_timing -setup -setup_margin $ES -verbose
  repair_timing -hold -hold_margin 0.05 -verbose
  repair_timing -setup -setup_margin $ES -verbose
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
  set DRT_ITERS [expr {[info exists ::env(DRT_ITERS)] ? $::env(DRT_ITERS) : 20}]
  set DRT_OPTS [expr {[info exists ::env(DRT_OPTS)] ? $::env(DRT_OPTS) : ""}]       ;# e.g. "-or_seed 7 -or_k 2": a different (still deterministic) routing order
  detailed_route -output_drc $RUN/reports/drc_route.rpt -droute_end_iter $DRT_ITERS -verbose 1 {*}$DRT_OPTS
  write_db $RUN/routed.odb
  write_verilog $RUN/routed.v
  write_def $RUN/routed.def
  estimate_parasitics -global_routing -spef_file $RUN/routed.spef
  rpt routed
  report_clock_skew > $RUN/reports/skew_routed.rpt
}
puts "STAGES DONE: $STAGES"
