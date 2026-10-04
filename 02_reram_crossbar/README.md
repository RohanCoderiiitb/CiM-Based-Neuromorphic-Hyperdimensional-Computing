# 02_reram_crossbar — ReRAM 2T2R binary crossbar, circuit track (Phase 1)

Sub-phase **1A**: device constants, ngspice harness, vectorised Newton nodal solver, and exhaustive validation of the
solver against ngspice. Results: [results/phase1a_report.md](results/phase1a_report.md). Plan: `PHASE1_FINAL_PLAN.md`.

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
python -m validate.validate_solver [--n-draws 200]   # resumable; writes results/validation.csv
python -m validate.make_report                       # writes results/phase1a_report.md
```
Needs `ngspice` on PATH for validation (`brew install ngspice`). Python 3.10+, numpy, scipy (tests), pytest.

## Status / caveats
`R_tx` and the gap sigmas are **TO BE DETERMINED** placeholders. ngspice models the device as a B-source carrying the
read equation of `rram.va`; the OSDI-compiled model was not exercised.

## Phase 1B-i (margin budget, provisional g)
`solver/budget.py` (framework) + `margin/` (core, point, ladder, leakage, surface). Report: [results/phase1b_i_report.md](results/phase1b_i_report.md).
```
python -m margin.run_sweep       # 960 points -> results/1b_i/surface_points.csv (~15 min, resumable)
python -m margin.run_leakage     # HRS leakage vs ratio, windows -> results/1b_i/leakage.json
python -m margin.make_report     # -> results/phase1b_i_report.md, results/1b_i/ladder_recommended.csv (~2 min)
```
