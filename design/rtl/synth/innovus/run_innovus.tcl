# run_innovus.tcl - D1(b)-(d): floorplan with the analog crossbar as a hard macro, place, clock tree (738+ gated branches), route, extract, post-route timing at both corners.
#   cd <repo>/design/rtl/synth && python make_floorplan_params.py --build full && BUILD=full WORK=$PWD/work/full innovus -batch -files innovus/run_innovus.tcl
# Inputs : results/genus/<BUILD>/netlist.v (run_genus.tcl), work/<BUILD>/*.lef|*.lib (prepare_rtl.py), innovus/floorplan_params.tcl, innovus/mmmc.tcl, the PDK.
# Outputs: results/innovus/<BUILD>/{pre_cts,post_cts,routed}.{v,def,spef(post_cts,routed)}, routed.sdc, reports/*.rpt  -> feed them to  ../layout_analysis.py --stage pre_cts|post_cts|routed
# The CLOCK numbers that matter are written BEFORE and AFTER CTS (reports/clock_*_pre_cts.rpt / *_post_cts.rpt): skew, latency, buffer counts, per skew group.
# Modelled on the PDK's innovus_new_script.tcl. NOT run in the repository's environment (no licence); commands are Innovus 21-style - adjust the few that your version names differently.
set BUILD $::env(BUILD)
set env(WORK) $::env(WORK)
source [file join [file dirname [info script]] .. pdk.tcl]
source $SYNTH/innovus/floorplan_params.tcl
set OUTD $SYNTH/results/innovus/$BUILD
file mkdir $OUTD/reports

# ------------------------------------------------------------------ design import
set init_design_netlisttype verilog
set init_verilog $SYNTH/results/genus/$BUILD/netlist.v
set init_design_set_top 1
set init_top_cell cim_neurohdc_top
set init_lef_file [list $TECH_LEF $CELL_LEF $::env(WORK)/cim_macro.lef $::env(WORK)/hdc_class_array.lef]
set init_pwr_net {VDD}
set init_gnd_net {VSS}
set init_mmmc_file $SYNTH/innovus/mmmc.tcl
init_design

# ------------------------------------------------------------------ floorplan: explicit die, macros first
setDrawView fplan
floorPlan -site CoreSite -d $DIE_W $DIE_H $MARGIN $MARGIN $MARGIN $MARGIN
set cim [dbGet -p2 top.insts.cell.name cim_macro]
set hdc [dbGet -p2 top.insts.cell.name hdc_class_array]
placeInstance [dbGet $cim.name] $CIM_X $CIM_Y R0 -fixed
placeInstance [dbGet $hdc.name] $HDC_X $HDC_Y R0 -fixed
addHaloToBlock 10 10 10 10 [dbGet $cim.name]
addHaloToBlock 5 5 5 5 [dbGet $hdc.name]
# the macros are a full blockage for logic; routing over them is allowed only above Metal8 (see the LEF OBS)
createPlaceBlockage -box [dbGet $cim.box_llx] [dbGet $cim.box_lly] [dbGet $cim.box_urx] [dbGet $cim.box_ury] -type hard

# I/O pins of the digital top: spread on the right and top edges, away from the macro pins
editPin -side RIGHT -layer Metal5 -spreadType SIDE -pin [dbGet top.terms.name]

# ------------------------------------------------------------------ power
globalNetConnect VDD -type pgpin -pin VDD -override -verbose -netlistOverride
globalNetConnect VSS -type pgpin -pin VSS -override -verbose -netlistOverride
setAddRingMode -stacked_via_top_layer Metal11 -stacked_via_bottom_layer Metal1
addRing -nets {VDD VSS} -type core_rings -layer {top Metal11 bottom Metal11 left Metal10 right Metal10} -width 2.0 -spacing 1.0 -offset 2.0
addStripe -nets {VDD VSS} -layer Metal10 -direction vertical -width 1.0 -spacing 1.0 -set_to_set_distance 16 -start_from left
sroute -connect {blockPin corePin floatingStripe} -allowJogging 1 -allowLayerChange 1 -blockPin useLef -targetViaLayerRange {Metal1 Metal11}

# ------------------------------------------------------------------ placement
setPlaceMode -place_global_timing_effort high -place_global_cong_effort high
placeDesign
setDrawView place
optDesign -preCTS
timeDesign -preCTS -outDir $OUTD/reports/timing_pre_cts
reportCongestion -hotspot > $OUTD/reports/congestion_pre_cts.rpt
summaryReport -noHtml -outfile $OUTD/reports/summary_pre_cts.rpt
# ---- pre-CTS clock numbers (ideal-ish: no tree yet; the ICG fanout nets are the "clock"): the BEFORE column of the CTS delta
report_clocks > $OUTD/reports/clocks_pre_cts.rpt
report_clock_timing -type skew > $OUTD/reports/clock_skew_pre_cts.rpt
saveNetlist $OUTD/pre_cts.v
defOut -floorplan -netlist -routing $OUTD/pre_cts.def
setExtractRCMode -engine preRoute
extractRC
rcOut -spef $OUTD/pre_cts.spef

# ------------------------------------------------------------------ clock tree synthesis
# Clock-gate aware: CCOpt balances the sinks behind the 700+ TLATNCAX2 gates against the ungated ones. The library's CLKBUF / CLKINV cells are the tree cells.
set_ccopt_property buffer_cells   {CLKBUFX2 CLKBUFX3 CLKBUFX4 CLKBUFX6 CLKBUFX8 CLKBUFX12 CLKBUFX16 CLKBUFX20}
set_ccopt_property inverter_cells {CLKINVX1 CLKINVX2 CLKINVX3 CLKINVX4 CLKINVX6 CLKINVX8 CLKINVX12 CLKINVX16 CLKINVX20}
create_ccopt_clock_tree_spec -file $OUTD/ccopt.spec
source $OUTD/ccopt.spec
ccopt_design -cts
report_ccopt_clock_trees -file $OUTD/reports/ccopt_clock_trees_post_cts.rpt
report_ccopt_skew_groups -file $OUTD/reports/ccopt_skew_groups_post_cts.rpt
report_clock_timing -type skew > $OUTD/reports/clock_skew_post_cts.rpt
optDesign -postCTS -setup -hold
timeDesign -postCTS -outDir $OUTD/reports/timing_post_cts
timeDesign -postCTS -hold -outDir $OUTD/reports/timing_post_cts
summaryReport -noHtml -outfile $OUTD/reports/summary_post_cts.rpt
saveNetlist $OUTD/post_cts.v
defOut -floorplan -netlist -routing $OUTD/post_cts.def
extractRC
rcOut -spef $OUTD/post_cts.spef

# ------------------------------------------------------------------ routing and post-route extraction
setNanoRouteMode -routeWithTimingDriven true -routeWithSiDriven true
routeDesign -globalDetail
# signoff-quality extraction with Quantus when available (engine postRoute, coupled); falls back to Innovus' own post-route engine
setExtractRCMode -engine postRoute -effortLevel signoff -coupled true
extractRC
optDesign -postRoute -setup -hold
extractRC
timeDesign -postRoute -outDir $OUTD/reports/timing_routed
timeDesign -postRoute -hold -outDir $OUTD/reports/timing_routed
report_timing -view AV_SLOW -max_paths 5 > $OUTD/reports/timing_routed_slow.rpt
report_timing -view AV_FAST -max_paths 5 > $OUTD/reports/timing_routed_fast.rpt
report_clock_timing -type skew > $OUTD/reports/clock_skew_routed.rpt
report_power -outfile $OUTD/reports/power_innovus_routed_noactivity.rpt
summaryReport -noHtml -outfile $OUTD/reports/summary_routed.rpt
reportCongestion -hotspot > $OUTD/reports/congestion_routed.rpt

# physical cleanup and checks (fillers last, as in the PDK example)
set fillercells [list FILL64 FILL32 FILL16 FILL8 FILL4 FILL2 FILL1]
setFillerMode -corePrefix FILL -core $fillercells
addFiller -cell $fillercells -prefix FILL -markFixed
verify_drc -report $OUTD/reports/drc.rpt
verifyConnectivity -report $OUTD/reports/connectivity.rpt
verify_PG_short -report $OUTD/reports/pg_short.rpt

# ------------------------------------------------------------------ hand-off to layout_analysis.py (netlist WITHOUT physical-only cells, DEF, SPEF, SDC)
saveNetlist $OUTD/routed.v -excludeLeafCell
defOut -floorplan -netlist -routing $OUTD/routed.def
rcOut -spef $OUTD/routed.spef
write_sdc $OUTD/routed.sdc
write_sdf $OUTD/routed.sdf
exit
