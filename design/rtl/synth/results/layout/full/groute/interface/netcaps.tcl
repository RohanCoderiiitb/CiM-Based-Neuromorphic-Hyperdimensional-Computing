read_lef /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/work/tech_openroad.lef
read_lef /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/45_nm_PDK/cadence/cadence_45nm/lef/gsclib045_macro.lef
read_lef /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/work/full/cim_macro.lef
read_lef /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/work/full/hdc_class_array.lef
read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/45_nm_PDK/cadence/cadence_45nm/lib/fast_vdd1v0_basicCells.lib
read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/work/full/cim_macro.lib
read_liberty /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/work/full/hdc_class_array.lib
read_db /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/openroad/full/groute.odb
read_sdc /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/constraints/cim_neurohdc_top.sdc
set_propagated_clock [all_clocks]
set_wire_rc -signal -layer Metal3
set_wire_rc -clock -layer Metal5
estimate_parasitics -global_routing
set block [ord::get_db_block]
set fh [open /Users/rohankamath/Desktop/IIIT-Bangalore/Projects/Research-Projects/CiM-Based-Neuromorphic-Hyperdimensional-Computing/design/rtl/synth/results/layout/full/groute/interface/macro_net_caps.txt w]
foreach inst [$block getInsts] {
  set mn [[$inst getMaster] getName]
  if {$mn ne "cim_macro"} continue
  foreach it [$inst getITerms] {
    set net [$it getNet]
    if {$net eq "NULL"} continue
    if {[$net getSigType] ne "SIGNAL"} continue
    set nn [$net getName]
    sta::redirect_string_begin
    report_net -digits 6 $nn
    set s [sta::redirect_string_end]
    if {[regexp {Wire capacitance: ([0-9.eE+-]+)} $s -> r]} { puts $fh "[[$it getMTerm] getName] $nn $r" }
  }
}
close $fh
exit
