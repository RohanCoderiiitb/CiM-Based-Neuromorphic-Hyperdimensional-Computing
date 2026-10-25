# mmmc.tcl - multi-mode multi-corner setup of the owner's Innovus run (sourced by init_design via $init_mmmc_file). Two library corners of the PDK (slow = worst case 0.9 V / 125 C,
# fast = best case 1.1 V / 0 C), one RC corner from the PDK's QRC technology file (typical), one constraint mode (constraints/cim_neurohdc_top.sdc).
# Setup is checked at both corners, hold at both: the design closes with margin at 100 MHz, the hold check is where CTS through 700+ clock gates will show first.
set REPO [file normalize [file join [file dirname [info script]] .. .. .. ..]]
source $REPO/design/rtl/synth/pdk.tcl
set MACRO_LIBS [list $env(WORK)/cim_macro.lib $env(WORK)/hdc_class_array.lib]
create_library_set -name LIB_SLOW -timing [concat [list $LIB_SLOW] $MACRO_LIBS]
create_library_set -name LIB_FAST -timing [concat [list $LIB_FAST] $MACRO_LIBS]
# Quantus: -qrc_tech. If Quantus is not available in your Innovus session, replace by:  -cap_table $CAPTABLE
create_rc_corner -name RC_TYP -qrc_tech $QRC_TECH -T 25
create_delay_corner -name DC_SLOW -library_set LIB_SLOW -rc_corner RC_TYP
create_delay_corner -name DC_FAST -library_set LIB_FAST -rc_corner RC_TYP
create_constraint_mode -name CM -sdc_files [list $SYNTH/constraints/cim_neurohdc_top.sdc]
create_analysis_view -name AV_SLOW -delay_corner DC_SLOW -constraint_mode CM
create_analysis_view -name AV_FAST -delay_corner DC_FAST -constraint_mode CM
set_analysis_view -setup [list AV_SLOW AV_FAST] -hold [list AV_FAST AV_SLOW]
