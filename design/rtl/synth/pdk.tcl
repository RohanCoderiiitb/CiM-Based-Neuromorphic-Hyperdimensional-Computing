# pdk.tcl - locations, relative to the repository root (the PDK is at <repo>/45_nm_PDK and is NOT committed). Source from the Genus / Innovus scripts.
if {![info exists REPO]} { set REPO [file normalize [file join [file dirname [info script]] .. .. ..]] }
set PDK      $REPO/45_nm_PDK/cadence/cadence_45nm
set LIB_FAST $PDK/lib/fast_vdd1v0_basicCells.lib         ;# 1.1 V, 0 C   (best case)
set LIB_SLOW $PDK/lib/slow_vdd1v0_basicCells.lib         ;# 0.9 V, 125 C (worst case)
set TECH_LEF $PDK/lef/gsclib045_tech.lef
set CELL_LEF $PDK/lef/gsclib045_macro.lef
set QRC_TECH $PDK/qrc/gpdk045.tch
set CAPTABLE $PDK/captable/cln28hpl_1p10m+alrdl_5x2yu2yz_typical.capTbl
set SYNTH    $REPO/design/rtl/synth
set TECH_LEF_OR $SYNTH/work/tech_openroad.lef                  ;# OpenROAD: the same tech LEF without three device-level VIARULEs (openroad/sanitize_tech_lef.py)
