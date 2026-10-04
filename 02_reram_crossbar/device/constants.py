"""Device and circuit constants for the 2T2R read path. Every value is overridable.

Provenance tags (grep-able):
  [SIM]    measured from an actual ngspice run (script named in the comment; results/*.json holds the raw numbers)
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
                   #        W = TX_W_UM, V_WL = V_WL, T = 27 C, from validate/extract_rtx.py -> results/transistor.json.
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
