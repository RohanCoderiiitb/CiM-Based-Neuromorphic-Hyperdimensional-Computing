"""
Extraction of the integer-domain parameters from a frozen float checkpoint.

The float model quantizes on the fly (`neurohdc.fake_quant_int8`, per-channel):
    s_j   = max_i |Ws[j,i]| / 127            (float32)
    q_ji  = clamp(round(Ws[j,i] / s_j), -127, 127)
    Wq_ji = q_ji * s_j
Hardware stores q (int8, never -128) and never sees s_j. The scale is folded
into the per-neuron integer threshold:

    V_real >= v_thresh   <=>   s_j * V_int >= v_thresh
                         <=>   V_int >= v_thresh / s_j
                         <=>   V_int >= ceil(v_thresh / s_j)     (V_int is an integer)

The ceil is EXACT. There is no fixed-point format and no fractional bit.

The division is done in exact rational arithmetic (fractions.Fraction) on the
exact float32 values the float model uses. Plain float division could return
1133.0000001 for a true 1133 and ceil() would then be off by a whole unit.
"""
from dataclasses import dataclass
from fractions import Fraction
import math

import numpy as np
import torch


@dataclass
class IntParams:
    W: np.ndarray            # int8  [20, 512]  two's complement weights q_ji
    scale: np.ndarray        # float32 [20]     s_j (software only; NOT in hardware)
    v_thresh: float          # the float32 v_thresh value, as an exact python float
    thresh_int: np.ndarray   # int64 [20]       ceil(v_thresh / s_j)   (DVS-Gesture, raw counts)
    class_hv: np.ndarray     # uint8 [10, 100, 20]  sign(Wc) > 0, same layout as reference rasters
    Wq_float: np.ndarray     # float32 [20, 512]  q*s exactly as the float model computes it
    ckpt: str


def exact_ceil_div(num: float, den: float, mult: int = 1) -> int:
    """ceil(num * mult / den), evaluated exactly on the binary values of the floats."""
    return math.ceil(Fraction(num) * mult / Fraction(den))


def near_integer_margin(num: float, den: float, mult: int = 1) -> Fraction:
    """Distance of num*mult/den from the nearest integer (exact). Used to prove no
    threshold sits in the float-error 'danger zone'."""
    q = Fraction(num) * mult / Fraction(den)
    return abs(q - round(q))


def thresholds(v_thresh: float, scale: np.ndarray, mult: int = 1) -> np.ndarray:
    """Per-neuron integer thresholds. `mult` = N_e for input-normalised (N-MNIST) models,
    where the float model sees c/N_e instead of c (see phase0_report.md section 6)."""
    return np.array([exact_ceil_div(v_thresh, float(s), mult) for s in scale], dtype=np.int64)


def load_int_params(ckpt_path: str) -> IntParams:
    sd = torch.load(ckpt_path, map_location="cpu")
    Ws = sd["Ws"].float()
    # --- identical torch ops to neurohdc.fake_quant_int8(per_channel=True) -------------
    scale_t = Ws.abs().amax(dim=1, keepdim=True).clamp_min(1e-8) / 127.0
    q_t = torch.round(Ws / scale_t).clamp(-127, 127)
    Wq_t = q_t * scale_t
    # --- identical to NeuroHDC.v_thresh (softplus + 1e-3, float32) ---------------------
    vth_t = torch.nn.functional.softplus(sd["_v_thresh_raw"]) + 1e-3
    q = q_t.numpy()
    assert np.all(q == np.round(q)) and np.abs(q).max() <= 127
    W = q.astype(np.int8)
    scale = scale_t.squeeze(1).numpy().astype(np.float32)
    v_thresh = float(vth_t.item())
    class_hv = (torch.sign(sd["Wc"]) > 0).numpy().astype(np.uint8).reshape(10, 100, 20)
    return IntParams(W=W, scale=scale, v_thresh=v_thresh,
                     thresh_int=thresholds(v_thresh, scale), class_hv=class_hv,
                     Wq_float=Wq_t.numpy(), ckpt=ckpt_path)
