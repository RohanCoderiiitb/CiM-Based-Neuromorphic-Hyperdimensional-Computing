# results/ - index

Every location is defined once in `../paths.py`. Re-running a script regenerates its files in place.

| directory | what is in it | produced by |
|---|---|---|
| `reports/` | **The documents to read.** `phase1a_report.md` (device values, validated solver), `phase1b_provisional_report.md` (1B-i: margin budget without wire/drift, provisional g), **`phase1b_report.md` (consolidated 1B: final g, wire IR, drift, handoffs)**, **`phase1c_report.md` (1C: the full 512 x 160 array - group profile, supply/crosstalk, energy/latency/area, centre tap, column-sensing decision, handoffs)**. `archive/` holds superseded versions. | `validate.make_report`, `margin.make_report`, `margin.make_report_1b` |
| `device_characterization/` | 1A: access-transistor R_tx (PTM 45 nm LP), its off-state leakage vs temperature, the linear-vs-BSIM4 bound, differential level-gap curves | `validate.extract_rtx`, `validate.off_leakage`, `validate.linear_vs_bsim` |
| `solver_validation/` | 1A: Newton nodal solver vs ngspice. `..._sigma0.10.csv` is the full 770-case sweep; the other sigmas are reduced sweeps | `validate.validate_solver` |
| `margin_budget/` | 1B-i: g-surface points (sigma 0-0.20 plus the fine sigma 0.01-0.03 file), HRS leakage vs on/off ratio, spread/leakage crossover, recommended comparator ladder | `margin.run_sweep`, `margin.run_leakage`, `margin.crossover` |
| `wire_resistance/` | 1B-ii: 2-D mesh solver vs ngspice (1792 cases), per-point wire terms, row-line/driver IR; `group_decomposition/` has one JSON per (layout, g, ohm/pitch) for the between/within-group split and the held-out test | `wire.validate_mesh`, `wire.terms`, `wire.rowside`, `wire.decompose` |
| `drift/` | 1B-ii: g* versus drift rate for headroom, refresh and reference-cell strategies | `drift.run_drift` |
| `final_surface/` | 1B: the final g surface (wire IR + drift), one CSV per drift strategy | `wire.final` |
| `array_validation/` | 1C: the extended mesh solver (macro blocks, supply rail, ground rail, both-end drive) vs ngspice, 300 cases | `wire.validate_mesh_ext` |
| `full_column/` | C1: per-group ladder tables for all 64 groups (r = 0.5, 0.72), group profile CSVs, ladder-table size, accumulation test and its negative controls | `scaleup.run_column`, `scaleup.table_size`, `scaleup.run_accumulate`, `scaleup.run_controls` |
| `transient/` | C1d/C2/C3: ngspice read-pulse transients - energy and latency per group read (64 groups), crosstalk (macro and bit-plane mode) | `scaleup.run_energy_latency`, `scaleup.run_crosstalk`, `scaleup.run_crosstalk_bitplane` |
| `macro_512x32/` | C2: row line of the true 64-bitline macro (levers), supply/ground droop, row-gain matrix, the budget re-closed | `scaleup.run_rowline`, `scaleup.run_droop`, `scaleup.gain_matrix`, `scaleup.c2_budget` |
| `full_array/` | C3: five macros on shared rails, full-array transient, area model, energy per inference | `scaleup.run_array`, `scaleup.run_array_transient`, `scaleup.area`, `scaleup.energy_inference` |
| `readout_variants/` | C4: centre-tap and segmented columns, g* and break-even sigma | `scaleup.run_variants`, `scaleup.run_variants_breakeven` |
| `column_sensing/` | C5: columns-at-once table (electrical margin, cycles) | `scaleup.c5_decision` |
| `figures/` | The six paper figures (1B: fig1-6; 1C: fig7-12) (PDF, SVG, PNG 300 dpi), their source CSVs, `captions.md` | `margin.figures`, `scaleup.figures` |
| `logs/` | Console logs of the long runs | shell redirects |
| `archive/` | Superseded raw results kept for provenance (the 1A run with the clipped gap distribution; the far-group-only wire terms) | - |
