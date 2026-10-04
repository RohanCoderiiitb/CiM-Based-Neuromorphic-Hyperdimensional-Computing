# results/ - index

Every location is defined once in `../paths.py`. Re-running a script regenerates its files in place.

| directory | what is in it | produced by |
|---|---|---|
| `reports/` | **The documents to read.** `phase1a_report.md` (device values, validated solver), `phase1b_provisional_report.md` (1B-i: margin budget without wire/drift, provisional g), **`phase1b_report.md` (consolidated 1B: final g, wire IR, drift, handoffs)**. `archive/` holds superseded versions. | `validate.make_report`, `margin.make_report`, `margin.make_report_1b` |
| `device_characterization/` | 1A: access-transistor R_tx (PTM 45 nm LP), its off-state leakage vs temperature, the linear-vs-BSIM4 bound, differential level-gap curves | `validate.extract_rtx`, `validate.off_leakage`, `validate.linear_vs_bsim` |
| `solver_validation/` | 1A: Newton nodal solver vs ngspice. `..._sigma0.10.csv` is the full 770-case sweep; the other sigmas are reduced sweeps | `validate.validate_solver` |
| `margin_budget/` | 1B-i: g-surface points (sigma 0-0.20 plus the fine sigma 0.01-0.03 file), HRS leakage vs on/off ratio, spread/leakage crossover, recommended comparator ladder | `margin.run_sweep`, `margin.run_leakage`, `margin.crossover` |
| `wire_resistance/` | 1B-ii: 2-D mesh solver vs ngspice (1792 cases), per-point wire terms, row-line/driver IR; `group_decomposition/` has one JSON per (layout, g, ohm/pitch) for the between/within-group split and the held-out test | `wire.validate_mesh`, `wire.terms`, `wire.rowside`, `wire.decompose` |
| `drift/` | 1B-ii: g* versus drift rate for headroom, refresh and reference-cell strategies | `drift.run_drift` |
| `final_surface/` | 1B: the final g surface (wire IR + drift), one CSV per drift strategy | `wire.final` |
| `figures/` | The six paper figures (PDF, SVG, PNG 300 dpi), their source CSVs, `captions.md` | `margin.figures` |
| `logs/` | Console logs of the long runs | shell redirects |
| `archive/` | Superseded raw results kept for provenance (the 1A run with the clipped gap distribution; the far-group-only wire terms) | - |
