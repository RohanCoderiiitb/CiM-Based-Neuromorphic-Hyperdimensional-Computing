"""
Extraction of the integer-domain parameters from a frozen float checkpoint.

The float model quantizes on the fly (`neurohdc.fake_quant_int8`):
    s_j   = max_i |Ws[j,i]| / 127            (float32; per-channel)
    s     = max_ji |Ws[j,i]| / 127           (float32; per-tensor -> s_j = s for every j)
    q_ji  = clamp(round(Ws[j,i] / s_j), -127, 127)
    Wq_ji = q_ji * s_j
The granularity is a property of the CHECKPOINT (the quantizer default changed from per-tensor
to per-channel between the N-MNIST run and the frozen DVS-Gesture runs) and is not recorded in
the checkpoint sidecars, so it is fixed per checkpoint in GRANULARITY below, with the evidence.
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
import os

import numpy as np
import torch


# Quantizer granularity each checkpoint was TRAINED and RECORDED with (checkpoint basename -> per_channel).
#   frozen_seed{0,1,2}: per-channel. Integer/float rasters == recorded rasters, 0 differing spikes (run_phase0).
#   nmnist_seed0: per-TENSOR (the old fake_quant_int8 default, see its docstring). Evidence (float model, full
#     N-MNIST test set): per-tensor -> 0 / 20,000,000 spikes differ from the recorded raster, 10000/10000 preds,
#     acc 0.9491 == recorded; per-channel -> 245,112 spikes differ, acc 0.9490.
GRANULARITY = {"frozen_seed0.pt": True, "frozen_seed1.pt": True, "frozen_seed2.pt": True,
               "nmnist_seed0.pt": False}


def granularity_for(ckpt_path: str) -> bool:
    """True = per-channel, False = per-tensor. Unknown checkpoints are refused, not guessed."""
    name = os.path.basename(ckpt_path)
    if name not in GRANULARITY:
        raise KeyError(f"quantizer granularity of {name} is unknown; add it to quantize.GRANULARITY with evidence")
    return GRANULARITY[name]


@dataclass
class IntParams:
    W: np.ndarray            # int8  [20, 512]  two's complement weights q_ji
    scale: np.ndarray        # float32 [20]     s_j (software only; NOT in hardware); all equal if per-tensor
    v_thresh: float          # the float32 v_thresh value, as an exact python float
    thresh_int: np.ndarray   # int64 [20]       ceil(v_thresh / s_j)   (DVS-Gesture, raw counts)
    class_hv: np.ndarray     # uint8 [10, 100, 20]  sign(Wc) > 0, same layout as reference rasters
    Wq_float: np.ndarray     # float32 [20, 512]  q*s exactly as the float model computes it
    ckpt: str
    per_channel: bool        # quantizer granularity the checkpoint was trained with


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


def load_int_params(ckpt_path: str, per_channel: bool | None = None) -> IntParams:
    per_channel = granularity_for(ckpt_path) if per_channel is None else per_channel
    sd = torch.load(ckpt_path, map_location="cpu")
    Ws = sd["Ws"].float()
    # --- identical torch ops to neurohdc.fake_quant_int8(per_channel=...) --------------
    if per_channel:
        scale_t = Ws.abs().amax(dim=1, keepdim=True).clamp_min(1e-8) / 127.0
    else:
        scale_t = Ws.abs().max().clamp_min(1e-8) / 127.0
    q_t = torch.round(Ws / scale_t).clamp(-127, 127)
    Wq_t = q_t * scale_t
    # --- identical to NeuroHDC.v_thresh (softplus + 1e-3, float32) ---------------------
    vth_t = torch.nn.functional.softplus(sd["_v_thresh_raw"]) + 1e-3
    q = q_t.numpy()
    assert np.all(q == np.round(q)) and np.abs(q).max() <= 127
    W = q.astype(np.int8)
    scale = np.broadcast_to(scale_t.reshape(-1).numpy(), (Ws.shape[0],)).astype(np.float32)
    v_thresh = float(vth_t.item())
    class_hv = (torch.sign(sd["Wc"]) > 0).numpy().astype(np.uint8).reshape(10, 100, 20)
    return IntParams(W=W, scale=scale, v_thresh=v_thresh,
                     thresh_int=thresholds(v_thresh, scale), class_hv=class_hv,
                     Wq_float=Wq_t.numpy(), ckpt=ckpt_path, per_channel=per_channel)
