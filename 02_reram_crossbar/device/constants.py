"""Device and circuit constants for the 2T2R read path. Every value is overridable.

Provenance tags (grep-able):
  [SIM]    measured from an actual ngspice run (script named in the comment; results/device_characterization/*.json holds the raw numbers)
  [MODEL]  computed from an analytic expression stated in the code
  [ASSUM]  taken from literature or assumed; source / range in the comment
  [CHOICE] a design decision we made; reasoning in the comment
  [SP]     Stanford-PKU RRAM compact model default (rram.va) -- a published-model parameter
"""
from __future__ import annotations

from dataclasses import dataclass, replace

# --- Stanford-PKU read-current model: I = I0*exp(-Gap/g0)*sinh(V/V0) + GMIN*V ---
I0 = 1e-3          # A      [SP] rram.va parameter I0
G0 = 0.25          # nm     [SP] rram.va parameter g0
V0 = 0.25          # V      [SP] rram.va parameter V0
GMIN = 1e-12       # S      [SP] rram.va parameter GMIN (parallel leak across each device)
MIN_GAP = 0.2      # nm     [SP] rram.va minGap
MAX_GAP = 1.7      # nm     [SP] rram.va maxGap

# --- Stored-state gaps (model has no discrete states, so this is a design choice) ---
GAP_LRS = MIN_GAP  # nm     [CHOICE] fully-formed filament -> ~541.8 ohm at 0.1 V. With log-normal spread (below)
GAP_HRS = MAX_GAP  # nm     [CHOICE] fully-retracted filament -> ~218586 ohm. there is no clipping, so sitting on
                   #        the model limits costs nothing; spread is applied to conductance, not to the bounded gap.
                   #        This is also the 1D program-verify TARGET: 1D's window must be consistent with it.

# --- Circuit ---
R_S = 20.0         # ohm    [ASSUM] sense resistor from the plan; 1B sweeps it (not swept in 1A)
V_READ = 0.1       # V      [ASSUM] read voltage from the plan
V_WL = 1.1         # V      [CHOICE] wordline high = PTM 45nm LP nominal Vdd (core device is rated 1.1 V)

# --- Access transistor: PTM 45 nm LP BSIM4 (see device/ptm/, README, report section 1) ---
FEATURE_NM = 45.0          # nm   [CHOICE] node of the PTM card
TX_L_NM = 45.0             # nm   [CHOICE] drawn L = F. Leff == L: card has lint = 0, ll = 0, no xl [SIM-confirmed]
CELL_AREA_F2 = 40.0        # F^2  [CHOICE] 1T1R cell area, mid of the published 20-60 F^2 band; set by SET-current
                           #      requirement (see report section 3d), not by read margin
TX_FILL = 0.6              # -    [CHOICE] W = TX_FILL * CELL_AREA_F2 * F  (device-width fill factor of the cell)
TX_W_UM = TX_FILL * CELL_AREA_F2 * FEATURE_NM * 1e-3   # um  [MODEL] = 1.08 um at 40 F^2
R_TX = 505.79      # ohm    [SIM] linear-equivalent access-transistor resistance of an LRS branch (~93 uA) at
                   #        W = TX_W_UM, V_WL = V_WL, T = 27 C, from validate/extract_rtx.py -> results/device_characterization/access_transistor_rtx.json.
                   #        tests/test_provenance.py fails if this drifts from the json.

# --- Spread: the compact model has NO mismatch parameters; variability is imposed ---
# Log-normal on conductance prefactor A = I0*exp(-gap/g0):  A = A_nom*exp(sigma*randn). Since A ~ exp(-gap/g0),
# sigma_lnG = sigma_gap / g0 (a change of variable, not of physics). No clipping, no limits.
SIGMA_LNG = 0.10                          # [ASSUM] default; "ReRAM programming spread is typically 5-20%" (related work, no citation)
SIGMA_LNG_SWEEP = (0.0, 0.05, 0.10, 0.15, 0.20)   # [ASSUM] same range; results reported vs sigma, not at one value

# --- Off-state variability (BSIM4 card has no mismatch parameters either) ---
AVT_MV_UM = 2.5    # mV*um  [ASSUM] Pelgrom Vth-mismatch coefficient, typical of high-k/metal-gate 45 nm (literature range ~1.5-3.5)

# --- Parasitics recorded for 1B (not used in 1A) ---
BL_R_PER_CELL_65NM = 0.5   # ohm    [ASSUM] related work, 65 nm
BL_C_PER_CELL_65NM = 0.2   # fF     [ASSUM] related work, 65 nm

# --- Numerical settings ---
NEWTON_MAX_ITER = 50       # [CHOICE] iteration cap; solver raises if any case exceeds it
NEWTON_TOL_V = 1e-14       # V   [CHOICE] convergence on the bitline-voltage update
ACCEPT_REL_DIFF = 1e-4     # [CHOICE] 1A acceptance: worst-case relative disagreement 0.01%


# ===================== Phase 1B-i constants =====================
# --- Sweep axes (plan: PHASE1B_PLAN.md step 2) ---
R_S_SWEEP = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0)        # ohm  [CHOICE] from the 1B plan
AREA_SWEEP_F2 = (20, 40, 60, 100)                     # F^2  [CHOICE] from the 1B plan (published 1T1R band)
G_SWEEP = (1, 2, 4, 8, 16, 32, 64, 128)              # rows [CHOICE] powers of two dividing 512. Plan lists 4..64; 1, 2 and 128 are added
                                                      #      so the limit is visible where 4..64 alone would clip (spread forces g below 4;
                                                      #      128 shows whether anything is still grid-limited at 64)
# R_tx per cell area: R_tx * W = ~547 ohm*um (1A section 3), values copied from results/device_characterization/access_transistor_rtx.json (tests/test_margin.py enforces)
RTX_BY_AREA = {20: 1016.0459, 40: 505.79, 60: 336.8506, 100: 202.0276}      # ohm  [SIM] 1A validate/extract_rtx.py
ILRS_BY_AREA_A = {20: 6.2868e-5, 40: 9.2739e-5, 60: 1.10155e-4, 100: 1.29708e-4}    # A    [SIM] 1A: single LRS branch current (reporting only)

SIGMA_LNG_FINE = (0.01, 0.02, 0.03)    # [CHOICE] 1B Part A: fills the 0 -> 0.05 gap so the leakage-limited -> spread-limited crossover is visible

# --- Budget framework ---
N_SIGMA = 5.0              # [CHOICE] plan: random terms at 5 sigma
HEADROOM = 0.20            # [CHOICE] 20% of the decision margin held back. Reason: the two terms not yet modelled (wire IR, drift - 1B-ii) and
                           #          the Gaussian-tail extrapolation in the 5-sigma estimate both need room; the plan names 20% as the starting point.
CM_ERR_FRACTION = 0.10     # [CHOICE] plan: common-mode-induced error held to 10% of a step
MC_DRAWS = 1000            # [CHOICE] spread Monte-Carlo draws per (g, area, R_s); common random numbers across sigma
MC_SEED = 20260            # [CHOICE] reproducibility

# --- Comparator ---
CMRR_ACHIEVABLE_DB = 60.0  # dB [ASSUM] practical differential comparator/sense stage without trimming. Textbook range for a CMOS differential
                           #    pair ~60-80 dB (e.g. Razavi, Design of Analog CMOS Integrated Circuits). NOT verified for this process.
CMRR_SENS_DB = (50.0, 60.0, 70.0)   # dB [ASSUM] sensitivity around the above
COMP_SIGMA_I_A = 1e-6      # A  [ASSUM] input-referred current resolution (noise + residual offset after calibration) of a current-mode sense
                           #    stage, 1 sigma. Engineering estimate (typical few-hundred-nA to few-uA), NOT sourced. Enters as a random term at 5 sigma.
COMP_SIGMA_SENS_A = (3e-7, 1e-6, 3e-6)   # A [ASSUM] sensitivity
COMP_OFFSET_V = 5e-3       # V  [ASSUM] 1-sigma input offset of an uncalibrated voltage-mode comparator (informational: voltage-sense feasibility only)

# --- ReRAM HRS leakage (term 3) ---
RATIO_CEILING = 403.4      # -  [MODEL] gap 0.2 / 1.7 nm at V_read (1A section 2)
RATIO_SWEEP = (403.4, 330.3, 270.4, 221.4, 181.3, 150.0)   # [MODEL] 1A section 4 mapping (150 = floor of the plan's sweep)
RATIO_TOL = 0.25           # [CHOICE] +/- fractional systematic shift of the achieved HRS/LRS ratio from the ladder's design ratio (program-verify
                           #    window, die-to-die). 1D must hold this; the crossover analysis returns the window it may be allowed.
LEAK_BUDGET_SHARE = 0.25   # [CHOICE] leakage residual may take at most 25% of the usable margin before the crossover is declared
GAP_NO_HRS = 30.0          # nm [MODEL] gap large enough that exp(-gap/g0) ~ 1e-52: removes HRS conduction ("ideal, no leakage" reference)

# --- Array / workload (plan, fixed by the algorithm) ---
ROWS_TOTAL = 512           # [plan]
BITROW_PAIRS = 88          # [plan] 11 count bit-rows x 8 weight bit-columns. The plan counts one read per pair per group, i.e. columns sensed one
                           #   weight bit-plane at a time. If all 160 columns are sensed at once the figure is 11 x 512/g (1C decides).
TIMESTEPS = 100            # [plan]


# ===================== Phase 1B-ii constants (wire resistance, drift) =====================
BL_R_PER_PITCH_SWEEP = (0.5, 0.72)   # ohm per cell pitch [ASSUM] bitline; 1A section 9: related work 0.5 ohm @65 nm; brief's 1/F scaling gives 0.72. The source
                                     #   pitch is unknown, so both are carried as a sensitivity range, not a value.
WL_R_PER_PITCH_SWEEP = (0.5, 0.72)   # ohm per cell pitch [ASSUM] row line (same metal assumption as the bitline)
R_DRV_SWEEP = (1.0, 10.0, 100.0)     # ohm [ASSUM] row driver resistance. Related work: 10-100 ohm at 65 nm; 1 ohm added as the 'wide driver' bound.
R_DRV_DEFAULT = 10.0                 # ohm [ASSUM] low end of the related-work range
PITCH_UM = {20: 0.2012, 40: 0.2846, 60: 0.3486, 100: 0.4500}   # um [MODEL] 1A cell pitch = sqrt(area_F2) * F
MACRO_COLS = 32                      # [plan] NeuroHDC macro: 4 neurons x 8 bit-planes (1C's first step); full array is 160
FULL_COLS = 160                      # [plan] 20 neurons x 8 bit-planes
WIRE_PATTERNS_PER_CELL = 40          # [CHOICE] random activation patterns per (group, a, m); half fit the correction, half are held out
WIRE_SEED = 7                        # [CHOICE]


# --- Drift (1B Part D). No authoritative value exists; every drift number is [ASSUM] and swept. ---
DRIFT_T0_S = 3600.0                  # s  [CHOICE] reference age t0: first read after program-verify; sigma_lnG is the spread MEASURED at t0
DRIFT_LIFE_YEARS = (1.0, 10.0)       # years [CHOICE] product-life horizons swept
SECONDS_PER_YEAR = 365.25 * 24 * 3600.0   # s [MODEL]
NU_MEAN_SWEEP = (0.0, 0.001, 0.003, 0.01, 0.03)   # [ASSUM] mean drift exponent nu in G(t) = G(t0) (t/t0)^-nu (PCM-like values ~0.01-0.1 are the literature
                                                  #   analogue; resistive-switching drift is usually weaker/non-power-law; unverified for this device)
NU_REL_SPREAD_SWEEP = (0.25, 0.5)    # [ASSUM] sigma_nu / nu_mean, the device-to-device spread of the exponent
DRIFT_AGES = 7                       # [CHOICE] log-spaced ages between t0 and the horizon at which the budget is checked
REFRESH_INTERVALS_DAYS = (1.0, 7.0, 30.0, 90.0, 365.0, 1095.0, 3652.5)   # [CHOICE] candidate refresh intervals
REF_CELLS_SWEEP = (8, 32, 128, 512)  # [CHOICE] reference cells contributing to one ladder-scale estimate
WRITE_ENERGY_PJ = 10.0               # pJ per SET/RESET pulse [ASSUM] order-of-magnitude RRAM write energy (literature range ~0.1-100 pJ); 1D must measure
WRITE_RETRIES = 3.0                  # [ASSUM] mean verify-and-retry pulses per device, before 1D measures it
ENDURANCE_CYCLES = 1e6               # [ASSUM] conservative RRAM endurance (plan quotes 1e6-1e9)

DRIFT_SCENARIOS = {"none": (0.0, 0.25), "moderate": (0.003, 0.25), "strong": (0.01, 0.25)}   # [ASSUM] (nu_mean, sigma_nu/nu_mean) used for the final surface
SIGMA_FINAL_SWEEP = (0.03, 0.05, 0.10, 0.15, 0.20)   # [CHOICE] sigma_lnG values of the final surface (0.03 shows where leakage/compression/wire take over)
ROW_DRIVER_DEFAULT_COLS = 32         # [CHOICE] row-line length (columns) of the final surface = one NeuroHDC macro; 160 columns on one row line is rejected (wire section)

# --- TO BE DETERMINED ---
# ReRAM read-current temperature coefficient: rram.va has none ($vt appears only in the gap-evolution equation).
# Recorded as an explicit LIMITATION; the temperature-sensitive term in this design is transistor off-leakage.


@dataclass(frozen=True)
class Params:
    """Bundle of every value the solver/netlist needs. Use with_() to override."""
    i0: float = I0
    g0: float = G0
    v0: float = V0
    gmin: float = GMIN
    r_s: float = R_S
    v_read: float = V_READ
    r_tx: float = R_TX
    gap_lrs: float = GAP_LRS
    gap_hrs: float = GAP_HRS
    v_wl: float = V_WL
    tx_w_um: float = TX_W_UM
    tx_l_nm: float = TX_L_NM

    def with_(self, **kw: float) -> "Params":
        return replace(self, **kw)


DEFAULT = Params()
