"""
Phase 2-4 reference: the HDC query stage, the R=1 factorized class-HV mapping, the margin and the early-exit rule. Integer arithmetic only.

The Phase 0 scoring (int_model.xnor_scores_prefix) is the definition of the score; everything here is an *equivalent form* of it, or a decision taken on it:

  class_hv  C_i[t,j] in {0,1} (1 == +1, 0 == -1), i = class, t = timestep, j = neuron
  agree_i(t)      = sum_j [ S[t,j] == C_i[t,j] ]                  XNOR-popcount of one timestep, 0..20
  score_i(t)      = sum_{t'<=t} agree_i(t')                        prefix score, 0..2000 (11 bits), the eq. (21) score at t = T-1

Mapping (a), UNFACTORIZED: C is a 2000 x N memory, the 20-bit slice of timestep t is read and XNOR-popcounted against S[t].
Mapping (b), R = 1 FACTORIZED: C_i[t,j] = XNOR(a_i[j], b_i[t])  (the product of the +-1 signs), stored as a 20 x N stationary array a and a T x N sign table b:
    P_i(t)     = sum_j [ S[t,j] == a_i[j] ] = 20 - |S[t]| - |a_i| + 2 q_i(t)       q_i = AND-popcount(S, a_i), |a_i| the per-class bias register
    agree_i(t) = P_i(t) if b_i[t] else 20 - P_i(t)                                   (XNOR with a constant bit is the identity or the complement)
  The factorization is not an approximation of THIS mapping: agree_i(t) is identical, integer for integer, to the unfactorized one for C = expand_r1(a, b).
  What factorization changes is which class hypervectors can be represented (rank 1), i.e. the trained model: its accuracy is measured, not assumed.

Early exit (Phase 4): after the score update of timestep t, margin(t) = top1(t) - top2(t) over the N prefix scores (top2 = the second-largest VALUE; two classes tied for the
lead give margin 0). The sample exits at the first t with margin(t) >= theta; the prediction is argmax_i score_i(t) (ties -> lowest class index). theta = THETA_NEVER (> max margin)
disables the exit. The software study (studies/algorithm/phase3_experiments/src/exp2_early_exit.py) works on the BIPOLAR score 2*score - 20 (t+1), whose margin is exactly twice
this one: theta_bipolar = 2 theta (theta_from_bipolar).
"""
from __future__ import annotations

import math

import numpy as np

T_DEFAULT, N_NEURON = 100, 20
W_SCORE = 11                    # 2000 = 100 x 20 needs 11 bits
SCORE_MAX = T_DEFAULT * N_NEURON
W_THETA = 12                    # threshold register width
THETA_NEVER = (1 << W_THETA) - 1    # 4095 > SCORE_MAX: the margin can never reach it


# ---------------------------------------------------------------------------------------------------------------- class-HV mappings
def expand_r1(a_bits: np.ndarray, b_bits: np.ndarray) -> np.ndarray:
    """a_bits [N,20], b_bits [N,T] in {0,1} -> class_hv [N,T,20] uint8, C = XNOR(a, b)."""
    a = np.asarray(a_bits, np.uint8); b = np.asarray(b_bits, np.uint8)
    return (a[:, None, :] == b[:, :, None]).astype(np.uint8)


def agree_unfactorized(S: np.ndarray, class_hv: np.ndarray) -> np.ndarray:
    """S [T,20] {0,1}, class_hv [N,T,20] -> agree [T,N] int64: XNOR-popcount of each timestep's spike vector with each class slice."""
    return (np.asarray(S)[None, :, :] == np.asarray(class_hv)).sum(axis=2).T.astype(np.int64)


def and_popcount(S: np.ndarray, a_bits: np.ndarray) -> np.ndarray:
    """q[t,i] = sum_j S[t,j] a_i[j]  - the only thing the CIM array computes (spike-gated rows, N columns)."""
    return np.asarray(S, np.int64) @ np.asarray(a_bits, np.int64).T


def agree_factorized(S: np.ndarray, a_bits: np.ndarray, b_bits: np.ndarray, bias: np.ndarray | None = None) -> np.ndarray:
    """AND-popcount against the stationary array, bias from the register, sign from the table -> agree [T,N]. bias[i] = |a_i| unless given."""
    S = np.asarray(S, np.int64); a = np.asarray(a_bits, np.int64); b = np.asarray(b_bits, np.int64)
    bias = a.sum(axis=1) if bias is None else np.asarray(bias, np.int64)
    p = N_NEURON - S.sum(axis=1)[:, None] - bias[None, :] + 2 * and_popcount(S, a)          # XNOR popcount of S against a_i
    assert p.min() >= 0 and p.max() <= N_NEURON
    return np.where(b.T == 1, p, N_NEURON - p)


def prefix_scores(agree: np.ndarray) -> np.ndarray:
    return np.cumsum(agree, axis=0)


# ---------------------------------------------------------------------------------------------------------------- argmax, top-2, margin
def argmax_lowest(scores: np.ndarray) -> int:
    """argmax, ties -> lowest class index (np.argmax; what the float pipeline and Phase 0 use)."""
    return int(np.argmax(scores))


def top2_tournament(scores) -> tuple[int, int, int]:
    """(index of the leader, leader value, second-largest value) by a binary tournament of pairwise merges - no sort. This is the structure the RTL implements; the pad leaves
    of a non-power-of-two N carry value 0 and an index beyond N (scores are >= 0, so a pad can never change the leader or the second value)."""
    n = len(scores)
    size = 1 << max(1, math.ceil(math.log2(n)))
    nodes = [(int(scores[i]), i, 0) if i < n else (0, i, 0) for i in range(size)]      # (leader value, leader index, second value)
    while len(nodes) > 1:
        nxt = []
        for k in range(0, len(nodes), 2):
            l, r = nodes[k], nodes[k + 1]
            if l[0] >= r[0]:                       # tie -> left (lower index) keeps the lead
                nxt.append((l[0], l[1], max(l[2], r[0])))
            else:
                nxt.append((r[0], r[1], max(r[2], l[0])))
        nodes = nxt
    v1, i1, v2 = nodes[0]
    return i1, v1, v2


def margins(prefix: np.ndarray) -> np.ndarray:
    """prefix [T,N] -> margin[t] = top1 - top2 (sort-based; test_top2 proves the tournament equals it)."""
    s = np.sort(prefix, axis=1)
    return s[:, -1] - s[:, -2]


# ---------------------------------------------------------------------------------------------------------------- early exit
def exit_point(prefix: np.ndarray, theta: int) -> tuple[int, int, bool]:
    """(exit timestep t (0-based), prediction, fired). Never fires -> (T-1, argmax at T-1, False)."""
    T = prefix.shape[0]
    m = margins(prefix)
    hit = np.flatnonzero(m >= theta)
    t = int(hit[0]) if len(hit) else T - 1
    return t, argmax_lowest(prefix[t]), bool(len(hit))


def theta_from_bipolar(theta_bipolar: float) -> int:
    """Exact translation of a threshold of the software study (margin of the bipolar score) into the integer margin: bipolar margin = 2 x xnor margin, always even."""
    return int(math.ceil(theta_bipolar / 2.0))


def sweep(prefix_batch: np.ndarray, labels: np.ndarray, thetas) -> list[dict]:
    """prefix_batch [S,T,N] -> accuracy and mean exit timestep per theta (the Phase 4 curve). Vectorised over samples; identical to exit_point per sample."""
    S, T, N = prefix_batch.shape
    srt = np.sort(prefix_batch, axis=2)
    m = srt[:, :, -1] - srt[:, :, -2]                                  # [S,T]
    am = prefix_batch.argmax(axis=2)                                   # ties -> lowest index
    full_acc = float((am[:, -1] == labels).mean())
    rows = []
    for th in thetas:
        hit = m >= th
        t_exit = np.where(hit.any(axis=1), hit.argmax(axis=1), T - 1)
        pred = am[np.arange(S), t_exit]
        rows.append(dict(theta=int(th), mean_exit_timestep=float((t_exit + 1).mean()), accuracy=float((pred == labels).mean()), accuracy_full_T=full_acc,
                         fired_fraction=float(hit.any(axis=1).mean()), mean_fraction_of_T=float((t_exit + 1).mean() / T)))
    return rows


# ---------------------------------------------------------------------------------------------------------------- the unipolar identity (README Phase 2 task 2)
def unipolar_prefix(S: np.ndarray, class_hv: np.ndarray) -> np.ndarray:
    """prefix of 2 S.C_i - |C_i(t)|  (the argmax-equivalent form a spike-gated CIM array computes); differs from the XNOR score by a class-independent term."""
    S = np.asarray(S, np.int64); C = np.asarray(class_hv, np.int64)
    per_t = 2 * np.einsum("tj,itj->ti", S, C) - C.sum(axis=2).T
    return np.cumsum(per_t, axis=0)


def class_independent_offset(S: np.ndarray) -> np.ndarray:
    """xnor_prefix(t) = unipolar_prefix(t) + this, for every class: sum_{t'<=t} (20 - |S[t']|)."""
    return np.cumsum(N_NEURON - np.asarray(S, np.int64).sum(axis=1))
