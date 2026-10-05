# 02_reram_crossbar — ReRAM 2T2R binary crossbar, circuit track (Phase 1)

Sub-phase **1A**: device constants, ngspice harness, vectorised Newton nodal solver, and exhaustive validation of the
solver against ngspice. Results: [results/reports/phase1a_report.md](results/reports/phase1a_report.md). Plan: `PHASE1_FINAL_PLAN.md`.

```
device/constants.py   every value named, sourced, overridable (Params dataclass); TBD values marked
device/model.py       read I-V of the Stanford-PKU model at fixed gap
device/spread.py      gap-distribution sampling (the model has no mismatch parameters)
solver/newton.py      vectorised Newton nodal solve; takes per-branch gaps + active mask; returns raw currents
solver/comparator.py  currents -> integer count (nearest level; 1B replaces with a non-uniform ladder)
spice/netlist.py      Python builds decks (many independent columns per deck)
spice/runner.py      runs ngspice -b, parses node voltages
spice/rram.va         compact model with the clip_0 -> clip_minGap declaration fix (NOT compiled; OpenVAF absent)
validate/             validate_solver.py (resumable sweep), analysis.py, make_report.py
tests/                solver unit tests (no ngspice needed)
```

## Run (from this directory, repo venv)
```
python -m pytest tests -q
python -m validate.validate_solver [--n-draws 200]   # resumable; writes results/solver_validation/newton_vs_ngspice_sigma0.10.csv
python -m validate.make_report                       # writes results/reports/phase1a_report.md
```
Needs `ngspice` on PATH for validation (`brew install ngspice`). Python 3.10+, numpy, scipy (tests), pytest.

## Status / caveats
`R_tx` and the gap sigmas are **TO BE DETERMINED** placeholders. ngspice models the device as a B-source carrying the
read equation of `rram.va`; the OSDI-compiled model was not exercised.

## Phase 1B-i (margin budget, provisional g)
`solver/budget.py` (framework) + `margin/` (core, point, ladder, leakage, surface). Report: [results/reports/phase1b_provisional_report.md](results/reports/phase1b_provisional_report.md).
```
python -m margin.run_sweep       # 960 points -> results/margin_budget/g_surface_points.csv (~15 min, resumable)
python -m margin.run_leakage     # HRS leakage vs ratio, windows -> results/margin_budget/hrs_leakage_vs_ratio.json
python -m margin.make_report     # -> results/reports/phase1b_provisional_report.md, results/margin_budget/comparator_ladder_recommended.csv (~2 min)
```

## Phase 1B-ii (wire IR, drift, final g) and the consolidated 1B report
Consolidated report: [results/reports/phase1b_report.md](results/reports/phase1b_report.md) (supersedes the 1B-i report for reading; 1B-i stays on disk). Figures: `results/figures/` (PDF/SVG/PNG300, source CSVs, captions.md).
```
python -m wire.validate_mesh        # 2-D mesh solver vs ngspice, 1792 cases  -> results/wire_resistance/mesh_vs_ngspice_validation.csv
python -m wire.decompose            # between/within-group split, contiguous vs interleaved, held-out test
python -m wire.rowside              # row line / driver across K columns
python -m wire.terms                # mesh wire terms over the (g, area, R_s, r) grid -> results/wire_resistance/wire_terms_per_point.json
python -m drift.run_drift           # g* vs drift rate, three strategies -> results/drift/drift_sweep.json
python -m wire.final --strategy S1  # final surface -> results/final_surface/final_g_surface_S1.csv (~5 min, 9 workers)
python -m margin.figures            # six paper figures
python -m margin.make_report_1b     # -> results/reports/phase1b_report.md (~2 min)
```

All result locations are defined once in `paths.py`; `results/README.md` is the index of the results tree.


## Phase 1C (the full 512 x 160 array)
Report: [results/reports/phase1c_report.md](results/reports/phase1c_report.md). Code in `scaleup/` (the package is not called `array`: that would shadow the standard-library module), with the solver extension in `wire/mesh.py` (`solve_mesh_ext`) and its ngspice
validation in `wire/validate_mesh_ext.py`.
```
python -m wire.validate_mesh_ext --n 300            # extended mesh (blocks, supply/ground rail, both-end drive) vs ngspice -> results/array_validation/
python -m validate.gate_cap                          # access-transistor gate capacitance from the PTM card
python -m scaleup.run_column && python -m scaleup.run_accumulate && python -m scaleup.run_controls && python -m scaleup.table_size      # C1: 64 groups, accumulation, ladder size
python -m scaleup.run_energy_latency && python -m scaleup.analyze_c1d                                                                 # C1d (long)
python -m scaleup.run_rowline && python -m scaleup.run_rowline_ext && python -m scaleup.run_droop && python -m scaleup.gain_matrix     # C2 DC
python -m scaleup.run_crosstalk && python -m scaleup.analyze_crosstalk && python -m scaleup.run_crosstalk_bitplane && python -m scaleup.c2_budget
python -m scaleup.run_array && python -m scaleup.run_array_transient && python -m scaleup.energy_inference && python -m scaleup.area  # C3
python -m scaleup.run_variants && python -m scaleup.run_variants_breakeven && python -m scaleup.c5_decision                           # C4, C5
python -m scaleup.figures && python -m scaleup.make_report
```
`energy_inference` and `c5_decision` read 1E's measured regression JSONs and the golden count vectors under `../03_rtl` and `../01_integer_reference_model` (read-only).

Figure 13 (architecture diagram, cell schematic + array block diagram): `python scripts/make_architecture_fig.py` (needs `pip install schemdraw`).


## Phase 1F (the sense front-end and the read timing budget)
Report: [results/reports/phase1f_report.md](results/reports/phase1f_report.md). Code in `sense/` (transistor-level, ngspice, PTM 45 nm LP: `device/ptm/ptm45n_lp.lib` from 1A and the new `ptm45p_lp.lib`), tests in `tests/test_sense_frontend.py`. Raw results in
`results/sense_frontend/` and `results/pdn/`; figures 14-21 in `results/figures/`.
```
python -m sense.run_topologies && python -m sense.run_ground                                   # F1: four topologies on the same step
python -m sense.sweep_b && python -m sense.run_mismatch && python -m sense.cal                  # F2: noise, mismatch, calibration
python -m sense.run_cal_transient && python -m sense.run_drift_sources && python -m sense.az && python -m sense.comparator && python -m sense.run_chop
python -m sense.enable && python -m sense.pareto && python -m sense.reads                        # F3: bias power-up, per-point error terms, read counts
python -m sense.budget_1f && python -m sense.closure_1f && python -m sense.energy_1f            # F3/F6: budget, closure map, energy per inference
python -m sense.pdn && python -m sense.pdn --pad                                                # F4: power delivery
python -m sense.threshold_path && python -m sense.area_1f && python -m sense.recommend_1f       # F5/F7
python -m sense.figures && python -m sense.make_report
```
`sense.reads` and `sense.energy_1f` read 1E's golden count vectors under `../03_rtl` and 1C's `results/full_array/energy_per_inference.json` (read-only). The long runs are `sense.cal` (~10 min), `sense.run_cal_transient` (~15 min) and `sense.closure_1f` (~5 min) on 10 cores.

