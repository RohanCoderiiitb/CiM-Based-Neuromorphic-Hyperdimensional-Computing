"""
Exact integer reference model of the NeuroHDC SNN + HDC query.

This is THE golden model. Phase-1+ cocotb testbenches import it directly; it must
never be re-implemented elsewhere (IMPLEMENTATION_README.md, P1.4.7).

Everything is plain two's-complement integer arithmetic (numpy int64 carries the
values; the *hardware* widths are measured in measure.py and frozen from data).

    X_j(t)  = sum_addr c[t,addr] * W[j,addr]            integer
    Vp_j(t) = V_j(t-1) + X_j(t)                         integer (adder output)
    S_j(t)  = Vp_j(t) >= thresh_int_j                   compare
    V_j(t)  = 0 if S_j(t) else Vp_j(t)                  hard reset, no leak, no bias

There are no fractional bits, no rounding, no saturation anywhere.
"""
from dataclasses import dataclass
import numpy as np

T_DEFAULT, N_NEURON, N_ADDR, N_CLASS = 100, 20, 512, 10


@dataclass
class SnnTrace:
    X: np.ndarray        # int64 [T, 20]  MVM output
    Vp: np.ndarray       # int64 [T, 20]  V(t-1)+X(t): adder output, BEFORE compare/reset
    V: np.ndarray        # int64 [T, 20]  register value AFTER reset (what is stored)
    S: np.ndarray        # uint8 [T, 20]  spike raster


def snn_forward(counts: np.ndarray, W: np.ndarray, thresh_int: np.ndarray) -> SnnTrace:
    """counts: unsigned ints [T,512]; W: int8 [20,512]; thresh_int: ints [20]."""
    counts = np.asarray(counts)
    assert counts.ndim == 2 and counts.shape[1] == N_ADDR and counts.min() >= 0
    T = counts.shape[0]
    Wi = W.astype(np.int64)
    X = counts.astype(np.int64) @ Wi.T                      # exact: int64 matmul
    thr = np.asarray(thresh_int, dtype=np.int64)
    Vp = np.empty((T, N_NEURON), np.int64)
    V = np.empty((T, N_NEURON), np.int64)
    S = np.empty((T, N_NEURON), np.uint8)
    v = np.zeros(N_NEURON, np.int64)
    for t in range(T):
        vp = v + X[t]
        s = vp >= thr
        v = np.where(s, 0, vp)
        Vp[t], V[t], S[t] = vp, v, s
    return SnnTrace(X=X, Vp=Vp, V=V, S=S)


def snn_forward_batch(counts: np.ndarray, W: np.ndarray, thresh_int: np.ndarray) -> SnnTrace:
    """counts [B,T,512]; thresh_int [20] (shared) or [B,20] (per-sample, N-MNIST)."""
    B, T, _ = counts.shape
    thr = np.asarray(thresh_int, dtype=np.int64)
    if thr.ndim == 1:
        thr = np.broadcast_to(thr, (B, N_NEURON))
    X = counts.astype(np.int64) @ W.astype(np.int64).T      # [B,T,20]
    Vp = np.empty_like(X); V = np.empty_like(X); S = np.empty(X.shape, np.uint8)
    v = np.zeros((B, N_NEURON), np.int64)
    for t in range(T):
        vp = v + X[:, t]
        s = vp >= thr
        v = np.where(s, 0, vp)
        Vp[:, t], V[:, t], S[:, t] = vp, v, s
    return SnnTrace(X=X, Vp=Vp, V=V, S=S)


# ----------------------------------------------------------------------------------
# HDC query (eq. 9 / eq. 21). class_hv is {0,1}: 1 == +1, 0 == -1.
# ----------------------------------------------------------------------------------
def xnor_scores_prefix(S: np.ndarray, class_hv: np.ndarray) -> np.ndarray:
    """Cumulative XNOR-popcount scores after each timestep. S [T,20] {0,1}, class_hv [10,T,20].
    Returns int32 [T,10]; row T-1 is the final Score_i of eq. (21)."""
    agree = (S[None, :, :] == class_hv).sum(axis=2)         # [10,T]   XNOR popcount per timestep
    return np.cumsum(agree, axis=1).T.astype(np.int32)


def predict(S: np.ndarray, class_hv: np.ndarray) -> tuple[int, np.ndarray]:
    """argmax of the final score. Ties resolve to the lowest class index (same as
    torch/numpy argmax used by the float pipeline)."""
    sc = xnor_scores_prefix(S, class_hv)[-1]
    return int(np.argmax(sc)), sc


def bipolar_scores(S: np.ndarray, class_hv: np.ndarray) -> np.ndarray:
    """h_b . C_i with h_b = 2h-1, C in {+-1}: equals 2*xnor_score - D_hv. Same argmax."""
    h = 2 * S.astype(np.int64).reshape(-1) - 1
    C = 2 * class_hv.astype(np.int64).reshape(class_hv.shape[0], -1) - 1
    return C @ h


# ----------------------------------------------------------------------------------
# Structural identities the hardware relies on (asserted in tests / run_phase0)
# ----------------------------------------------------------------------------------
def event_serial_X(counts_t: np.ndarray, W: np.ndarray) -> np.ndarray:
    """Per-event accumulation R_j += W_j[addr] (paper eq. 20), for ONE timestep.
    Events are materialised from the counts in address order (any order gives the same
    integer sum). Proves the batching identity of IMPLEMENTATION_README P1.1.3."""
    acc = np.zeros(N_NEURON, np.int64)
    for addr in np.nonzero(counts_t)[0]:
        for _ in range(int(counts_t[addr])):
            acc += W[:, addr].astype(np.int64)
    return acc


def bitplane_X(counts_t: np.ndarray, planes: np.ndarray, n_count_bits: int) -> np.ndarray:
    """X via the hardware's bit-serial dataflow. planes: uint8 [20,8,512] weight bit-planes
    (plane 7 = two's-complement sign bit). counts are decomposed into bit-planes too;
    each (b,k) pair is an AND-popcount, weighted by sigma(k)*2^(b+k), sigma(7) = -1."""
    X = np.zeros(N_NEURON, np.int64)
    for b in range(n_count_bits):
        cb = ((counts_t >> b) & 1).astype(np.int64)                 # [512]
        for k in range(8):
            pop = planes[:, k, :].astype(np.int64) @ cb             # [20] AND-popcount
            X += (-1 if k == 7 else 1) * (pop << (b + k))
    return X
