"""Single source of truth for where every result artefact lives. Nothing else in the repo hard-codes a results path.

results/
  reports/                    the documents to read
    phase1a_report.md           1A: device values and the validated solver
    phase1b_provisional_report.md   1B-i: electrical margin budget (no wire, no drift) - provisional g
    phase1b_report.md           1B: consolidated final report (wire IR, drift, final g)
    archive/                    superseded versions
  device_characterization/    1A: access transistor R_tx, off-state leakage, linear-vs-BSIM4 bound, level-gap curves
  solver_validation/          1A: Newton solver vs ngspice (full sweep + sigma sweeps)
  margin_budget/              1B-i: g surface points, HRS leakage vs ratio, spread/leakage crossover, comparator ladder
  wire_resistance/            1B-ii: mesh validation, group decomposition, row-line IR, per-point wire terms
    group_decomposition/        one JSON per (layout, g, ohm/pitch)
  drift/                      1B-ii: g* versus drift rate for the three strategies
  final_surface/              1B: final g surface with wire IR and drift (one CSV per drift strategy)
  figures/                    the six paper figures (PDF, SVG, PNG 300 dpi), their source CSVs, captions
  logs/                       console logs of the long runs
  archive/                    superseded raw results
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

REPORTS = RESULTS / "reports"
REPORTS_ARCHIVE = REPORTS / "archive"
DEVICE = RESULTS / "device_characterization"
SOLVER_VALIDATION = RESULTS / "solver_validation"
MARGIN = RESULTS / "margin_budget"
WIRE = RESULTS / "wire_resistance"
WIRE_DECOMP = WIRE / "group_decomposition"
DRIFT = RESULTS / "drift"
FINAL = RESULTS / "final_surface"
FIGURES = RESULTS / "figures"
LOGS = RESULTS / "logs"
ARCHIVE = RESULTS / "archive"

# reports
REPORT_1A = REPORTS / "phase1a_report.md"
REPORT_1B_PROVISIONAL = REPORTS / "phase1b_provisional_report.md"
REPORT_1B = REPORTS / "phase1b_report.md"
REPORT_1A_V1 = REPORTS_ARCHIVE / "phase1a_report_v1.md"

# 1A
TRANSISTOR_JSON = DEVICE / "access_transistor_rtx.json"
OFF_LEAKAGE_JSON = DEVICE / "access_transistor_off_leakage.json"
LINEAR_VS_BSIM_JSON = DEVICE / "linear_vs_bsim4_bound.json"
LEVEL_GAP_CSV = DEVICE / "differential_level_gap_vs_m.csv"
LEVEL_GAP_PNG = DEVICE / "differential_level_gap_vs_m.png"
VALIDATION_CSV = SOLVER_VALIDATION / "newton_vs_ngspice_sigma0.10.csv"


def validation_sigma_csv(sigma: float) -> Path:
    return SOLVER_VALIDATION / f"newton_vs_ngspice_sigma{sigma:.2f}.csv"


# 1B-i
SURFACE_POINTS_CSV = MARGIN / "g_surface_points.csv"
SURFACE_POINTS_FINE_CSV = MARGIN / "g_surface_points_fine_sigma.csv"
HRS_LEAKAGE_JSON = MARGIN / "hrs_leakage_vs_ratio.json"
CROSSOVER_JSON = MARGIN / "spread_leakage_crossover.json"
LADDER_CSV = MARGIN / "comparator_ladder_recommended.csv"

# 1B-ii
MESH_VALIDATION_CSV = WIRE / "mesh_vs_ngspice_validation.csv"
ROW_LINE_JSON = WIRE / "row_line_ir.json"
WIRE_TERMS_JSON = WIRE / "wire_terms_per_point.json"


def decomposition_json(layout: str, g: int, r: float) -> Path:
    return WIRE_DECOMP / f"{layout}_g{g}_r{r}.json"


DRIFT_SWEEP_JSON = DRIFT / "drift_sweep.json"


def final_points_csv(strategy: str = "S1") -> Path:
    return FINAL / f"final_g_surface_{strategy}.csv"
