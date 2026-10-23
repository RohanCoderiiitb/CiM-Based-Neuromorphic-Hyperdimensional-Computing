"""ArraySpec - every dimension and resistance of the crossbar netlist. Nothing is written here: each default is a name in studies/crossbar/device/constants.py.

The defaults are the 1C design point (512 x 160 cells = five 512 x 32-cell macros, g = 8, 20 F^2 devices, row drivers at both ends, rails fed from both ends).
Overriding a field gives a different array; the validation (validate_netlist.py) overrides them freely, including odd block widths the real macro does not have.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

_STUDIES = Path(__file__).resolve().parents[3] / "studies" / "crossbar"          # device/, spice/, margin/ ... live here
if str(_STUDIES) not in sys.path:
    sys.path.insert(0, str(_STUDIES))

import device.constants as C  # noqa: E402
from device.constants import Params  # noqa: E402
from margin.core import params_for  # noqa: E402

R_FLOOR = 1e-4          # ohm: smallest wire / driver resistance written (same floor as the mesh solver wire.mesh.R_FLOOR and the old transient deck)

DEVICES = ("sinh", "resistor")
TXS = ("switch", "linear", "bsim")
DRIVERS = ("switch", "resistor")


def _default_params() -> Params:
    return params_for(C.AREA_1C, C.RS_1C)


@dataclass(frozen=True)
class ArraySpec:
    rows: int = C.ROWS_TOTAL                                     # physical rows of every macro
    blocks: tuple[int, ...] = (C.MACRO_BITLINES,) * C.N_MACROS   # bitlines (mesh columns) per macro; the row line is broken between macros
    g: int = C.G_1C                                              # cells per group on a bitline pair
    p: Params = field(default_factory=_default_params)           # device law, R_tx, V_read, V_WL, transistor W/L
    r_bl: float = C.BL_R_PER_PITCH_1C                            # ohm per cell pitch, bitline
    r_wl: float = C.WL_R_PER_PITCH_1C                            # ohm per cell pitch, row line
    r_drv: float = C.R_DRV_DEFAULT                               # ohm, one row driver
    r_rail: float | None = C.RAIL_R_DEFAULT                      # ohm per pitch, supply rail; None = ideal supply at every driver
    r_gnd: float | None = C.RAIL_R_DEFAULT                       # ohm per pitch, ground rail along the sense nodes; None = ideal ground
    rail_feed_both_ends: bool = C.RAIL_FEED_BOTH_ENDS            # second supply pad at rail_length
    rail_length: float | None = None                             # pitches from pad 1 to pad 2; None -> rows + 1
    rail_pos: tuple[float, ...] | None = None                    # distance of row i's driver tap from pad 1; None -> i + 1
    r_s: float | tuple[float, ...] = C.RS_1C                     # ohm, sense (virtual-ground) resistor, per bitline or one value
    drive_both_ends: bool = True                                 # a driver at BOTH ends of every row line of a macro
    gnd_pad_pitches: float = 1.0                                 # ground-rail pad distance from the first column of a macro
    gnd_pad_per_block: bool = True                               # one ground pad per macro (else a single pad on macro 0)
    device: str = "sinh"                                         # 'sinh': the device law of constants.py; 'resistor': fixed R at the read bias
    tx: str = "switch"                                           # access transistor: 'switch' (R_tx, gated by the word line), 'linear' (always on), 'bsim' (PTM card)
    driver: str = "switch"                                       # row driver: 'switch' (R_DRV, gated by the word line) or 'resistor' (always on)
    caps: bool = False                                           # parasitic capacitance (needs c_line etc.)
    c_line: float = C.C_LINE_PER_PITCH_F
    cc_fraction: float = C.CC_FRACTION_DEFAULT
    c_sense: float = C.C_SENSE_F
    c_dec: float = 0.0                                           # decoupling at each row's supply tap

    def __post_init__(self):
        if self.device not in DEVICES or self.tx not in TXS or self.driver not in DRIVERS:
            raise ValueError("unknown device / tx / driver option")
        if self.g < 1 or self.rows < 1 or any(b < 1 for b in self.blocks):
            raise ValueError("g, rows and block widths must be positive")

    # ------------------------------------------------------------------ derived
    @property
    def K(self) -> int:
        return int(sum(self.blocks))

    @property
    def col0(self) -> np.ndarray:
        return np.concatenate([[0], np.cumsum(self.blocks)[:-1]]).astype(int)

    @property
    def rs(self) -> np.ndarray:
        return np.broadcast_to(np.asarray(self.r_s, dtype=float), (self.K,)).copy()

    @property
    def rail_pos_arr(self) -> np.ndarray:
        return np.arange(self.rows) + 1.0 if self.rail_pos is None else np.asarray(self.rail_pos, dtype=float)

    @property
    def rail_len(self) -> float | None:
        if self.rail_length is not None:
            return self.rail_length
        return self.rows + 1.0 if self.rail_feed_both_ends else None

    @property
    def n_groups(self) -> int:
        return -(-self.rows // self.g)

    def with_(self, **kw) -> "ArraySpec":
        return replace(self, **kw)

    # ------------------------------------------------------------------ device states
    def gap_to_state(self, gap):
        """Device state variable written into the netlist: the gap (nm) for 'sinh', the resistance at the read bias (ohm) for 'resistor'."""
        return gap if self.device == "sinh" else device_resistance(gap, self.p)


def device_resistance(gap, p: Params = None):
    """[MODEL] secant resistance V_read / I(V_read) of the device law at a filament gap (nm): the fixed resistor of the 'resistor' device flavour."""
    p = _default_params() if p is None else p
    gap = np.asarray(gap, dtype=float)
    i = p.i0 * np.exp(-gap / p.g0) * np.sinh(p.v_read / p.v0) + p.gmin * p.v_read
    return p.v_read / i


def weights_to_gaps(w: np.ndarray, p: Params = None) -> np.ndarray:
    """Stored weight bits (rows, cells) -> device gaps (rows, 2*cells). Bit 1: + device LRS, - device HRS; bit 0: the reverse (the 1A/1C convention)."""
    p = _default_params() if p is None else p
    w = np.asarray(w, dtype=bool)
    K = 2 * w.shape[1]
    stored = np.repeat(w, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1)
    return np.where(stored, p.gap_lrs, p.gap_hrs)
