# design/rtl/synth - post-layout PPA of the accelerator

Everything for `reports/final_ppa.md`: the digital flow with the real PDK (Genus + Innovus + Quantus, the owner's licences), the analog crossbar as a hard macro (LEF/Liberty generated here,
area from NeuroSim), the digital/analog interface, and the scripts that turn the owner's layout files into the numbers. The digital block has been placed, clock-tree-synthesised and global-routed with **OpenROAD** (built from source, outside the repository) for the full design;
detailed routing did not converge, and the Genus / Innovus / Quantus flow (no licence here) is prepared but not run. Cells no tool produced are marked PENDING and never estimated.

## What is here, and whether it has been run

| file | purpose | status |
|---|---|---|
| `analog_macros.py` | area of the analog macro at 20 F^2 (1C), NeuroSim 40 F, NeuroSim 128 F; LEF + timing-only Liberty of `cim_macro`, `hdc_class_array` | **run**; `macro/*.lef,*.lib`, `results/analog_area.json` |
| `neurosim/` | `ns_driver.cpp` + `run_neurosim.py`: NeuroSim V1.4 on one 512 x 32 2T2R macro (cloned outside the repo, CC BY-NC) | **run**; `results/neurosim.json` |
| `interface_model.py` | wire + level-shifter energy of the 1,055 boundary wires, from a measured gate-level VCD | **run**; `results/interface.json` |
| `prepare_rtl.py` | per-build RTL copy for Genus (package defaults, structural ICG `rtl/clk_gate_icg.v`, macros as library cells); checks it elaborates in Yosys | **run, all builds elaborate** |
| `make_floorplan_params.py` | die size and macro positions for Innovus | **run** (`innovus/floorplan_params.tcl`) |
| `genus/run_genus.tcl` | synthesis against the PDK library | **not run - needs Genus** |
| `innovus/run_innovus.tcl`, `innovus/mmmc.tcl` | floorplan with the macro, place, CTS, route, Quantus extraction, post-route STA | **not run - needs Innovus (+ Quantus)** |
| `constraints/cim_neurohdc_top.sdc`, `pdk.tcl` | the constraints of every pre-route number; PDK paths | used by both |
| `openroad/` | `run_flow.sh` (floorplan with the macro, place, CTS, global route), `analyze_openroad.py` (timing both corners, skew, power windows), `interface_routed.py`, `make_pnr_netlist.py`, `sanitize_tech_lef.py` | **run (full design)** |
| `layout_analysis.py` | from the owner's netlists/SPEF/DEF: area, timing at both corners, skew, power (zero-delay gate-level VCD + SPEF, three windows) | **run on the pre-route netlist (`--stage baseline`) and reproduces 0.147 mW**; waits for Innovus files |
| `final_ppa.py` | writes `reports/final_ppa.md` | **run**; post-route cells PENDING |

## What the owner runs

```
cd design/rtl/synth
B=full                                   # then ee_off, fact_off, both_off
python prepare_rtl.py --build $B && python make_floorplan_params.py --build $B
BUILD=$B genus   -batch -files genus/run_genus.tcl
BUILD=$B WORK=$PWD/work/$B innovus -batch -files innovus/run_innovus.tcl
for S in pre_cts post_cts routed; do
  python layout_analysis.py --stage $S --build $B --netlist results/innovus/$B/$S.v --spef results/innovus/$B/$S.spef --def results/innovus/$B/$S.def
done
python final_ppa.py
```

The Genus and Innovus scripts are modelled on the PDK's `genus_new.tcl` / `innovus_new_script.tcl` / `mmmc.tcl` and have **never been executed**: command options may need adapting to your versions.
`layout_analysis.py` needs only OpenSTA (`design/rtl/tools/sta`), Yosys and Icarus (the repository's own tools).

## Things to know before running

* The PDK's two Liberty files are byte-identical to the "lab 45 nm" library every earlier number used (SHA-1 checked), so the pre-route numbers are already PDK numbers.
* The PDK has the clock-gating cell (`TLATNCAX2/12/16/20`, `latch_posedge`) but **no decap cells** and **no Liberty for its level shifters** (`LSHL*`, `LSLH*`: LEF only).
* `/45_nm_PDK/` is now in `.gitignore`: it contains a secured lab PDF and a `cshrc_new` with a licence-server address. Do not commit it.
* The macro pin edge holds 2,178 pin bits on Metal4/Metal6 at 0.4 um pitch (the RTL black-box interface, unchanged); 1,120 of the 1,600 count-output bits are constant zero at g = 4.
