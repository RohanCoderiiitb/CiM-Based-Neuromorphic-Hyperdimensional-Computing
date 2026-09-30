"""
Experiment 1: axis-factorized class hypervector.

Subclasses the FROZEN NeuroHDC model (phase1_firing_characterization/src/
neurohdc.py) and changes exactly one thing, per the task's hard rule: the
parameterization of the class hypervector. Everything else -- the SNN event
loop, IF neuron, int8 QAT on W_s, V_thresh calibration/training, the
sign_ste()/fake_quant_int8() primitives, the score formula and its 1/sqrt(D_hv)
temperature -- is copied verbatim from NeuroHDC.forward(), unchanged.

Baseline:   Wc        in R^{N, T*n}            (unstructured latent)
            C = sign(Wc)

Factorized: A         in R^{N, R, n}            (per-class neuron profiles)
            B         in R^{N, R, T}            (per-class temporal profiles)
            Wc_hat[i,t,j] = sum_r Ahat[i,r,j] * Bhat[i,r,t]
            C = sign(Wc_hat).reshape(N, T*n)

factor_mode="fp":     Ahat=A, Bhat=B (float factors; accuracy ceiling, not deployable)
factor_mode="binary": Ahat=sign_ste(A), Bhat=sign_ste(B) (deployable; R*(n+T) bits/class)
"""
import math
import sys
import os
import torch
import torch.nn as nn
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "phase1_firing_characterization", "src"))
from neurohdc import NeuroHDC, ATanSpike, fake_quant_int8, sign_ste  # noqa: E402


class NeuroHDCFactorized(NeuroHDC):
    def __init__(self, n=20, T=100, n_input=512, n_classes=10, alpha=2.0,
                 v_thresh_init=1.0, head_dropout=0.0, rank=4, factor_mode="binary"):
        # Build the parent exactly as the frozen baseline does (same Ws,
        # v_thresh, SNN parameters) -- we discard only its Wc below.
        super().__init__(n=n, T=T, n_input=n_input, n_classes=n_classes,
                          alpha=alpha, v_thresh_init=v_thresh_init, head_dropout=head_dropout)
        assert factor_mode in ("fp", "binary")
        self.rank = rank
        self.factor_mode = factor_mode
        del self.Wc  # replaced by the factors below; nothing else from the parent changes
        self.A = nn.Parameter(torch.randn(n_classes, rank, n) * 0.1)   # neuron profiles
        self.B = nn.Parameter(torch.randn(n_classes, rank, T) * 0.1)   # temporal profiles

    @torch.no_grad()
    def svd_init(self, Wc_baseline):
        """
        OUR CHOICE (task-specified init): seed A, B from a per-class rank-R
        SVD of the trained BASELINE's Wc, reshaped to [T, n] per class
        (matches the flatten order used everywhere in NeuroHDC: raster is
        [B,T,n] -> reshape(B, T*n), so dimension m = t*n + j).

        M_i[t,j] = sum_r S[r] * U[t,r] * V[j,r]
        Set B[i,r,t] = U[t,r]*sqrt(S[r]), A[i,r,j] = V[j,r]*sqrt(S[r]) so
        their product reconstructs M_i exactly at full rank, and best-fits it
        (in Frobenius norm, by the Eckart-Young theorem) at rank R < full.
        """
        N = Wc_baseline.shape[0]
        R = self.rank
        Wc_baseline = Wc_baseline.detach().cpu()
        for i in range(N):
            M = Wc_baseline[i].reshape(self.T, self.n)  # [T, n]
            U, S, Vt = torch.linalg.svd(M, full_matrices=False)  # U:[T,k] S:[k] Vt:[k,n]
            k = min(R, S.shape[0])
            sqrtS = S[:k].clamp_min(0).sqrt()
            self.B.data[i, :k, :] = (U[:, :k] * sqrtS).t()       # [k, T]
            self.A.data[i, :k, :] = (Vt[:k, :].t() * sqrtS).t()  # [k, n]
            if k < R:  # rank of M smaller than R (shouldn't happen here, T,n >> R), pad randomly
                self.B.data[i, k:, :] = torch.randn(R - k, self.T) * 0.1
                self.A.data[i, k:, :] = torch.randn(R - k, self.n) * 0.1

    def class_hv_bits(self):
        """Storage cost of the deployable (binary) representation, in bits, all classes."""
        return self.n_classes * self.rank * (self.n + self.T)

    def _reconstruct_C(self):
        if self.factor_mode == "fp":
            Ahat, Bhat = self.A, self.B
        else:
            Ahat, Bhat = sign_ste(self.A), sign_ste(self.B)
        # Wc_hat[i,t,j] = sum_r Ahat[i,r,j] * Bhat[i,r,t]
        Wc_hat = torch.einsum("irj,irt->itj", Ahat, Bhat)  # [N, T, n]
        Wc_hat = Wc_hat.reshape(self.n_classes, self.T * self.n)
        return sign_ste(Wc_hat)

    def forward(self, frames):
        # --- SNN event loop: byte-for-byte identical to NeuroHDC.forward() ---
        B = frames.shape[0]
        device = frames.device
        Wq = fake_quant_int8(self.Ws)
        V = torch.zeros(B, self.n, device=device)
        raster = torch.empty(B, self.T, self.n, device=device)
        vth = self.v_thresh
        for t in range(self.T):
            X = frames[:, t, :] @ Wq.t()
            Vp = V + X
            S = ATanSpike.apply(Vp - vth, self.alpha)
            V = Vp * (1.0 - S)
            raster[:, t, :] = S
        h_u = raster.reshape(B, self.T * self.n)
        h_b = 2.0 * h_u - 1.0
        if self.training and self.head_dropout > 0:
            h_b = torch.nn.functional.dropout(h_b, p=self.head_dropout, training=True)
        # --- the ONLY change: C comes from the rank-R factorization ---
        C = self._reconstruct_C()
        scores = (h_b @ C.t()) / math.sqrt(self.n * self.T)
        return scores, raster
