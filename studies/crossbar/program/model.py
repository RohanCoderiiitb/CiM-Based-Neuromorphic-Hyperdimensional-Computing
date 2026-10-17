"""1D-ii: the compact model's equations, mirrored in Python for ANALYSIS only (closed forms, plots, sanity checks).
Every number the report rests on comes from the compiled model in ngspice (program/cell.py, spice/osdi.py); tests/test_program.py checks this mirror against it.

rram.va (Wang & Roychowdhury, "Well-posed models of memristive devices", arXiv:1605.04897 - a well-posed, isothermal, deterministic reduction of the Stanford-PKU model):
  I(t,b)       = I0 exp(-Gap/g0) sinh(V/V0) + GMIN V                       read / conduction           [SP]
  ddt_gap      = -Vel0 exp(-Ea/vt) sinh(V Gamma a0 / (tox vt)),  Gamma = gamma0 - Beta Gap^3   (m/s)
  clip_minGap  = (limexp(Kclip (minGap - Gap)) - ddt_gap) * smoothstep(minGap - Gap, smoothing)
  clip_maxGap  = (-limexp(Kclip (Gap - maxGap)) - ddt_gap) * smoothstep(Gap - maxGap, smoothing)
  KCL at nGap:  1e-9 dGap/dt = ddt_gap + clip_minGap + clip_maxGap      (Gap in nm, so dGap/dt in nm/s = 1e9 x the right-hand side)
Positive V(t,b) closes the gap (SET); negative opens it (RESET).
"""
from __future__ import annotations

import numpy as np

K_B_EV = 8.617333262e-5          # eV/K
T0_K = 273.15
P = dict(g0=0.25, V0=0.25, Vel0=10.0, I0=1e-3, Beta=0.8, gamma0=16.0, Ea=0.6, a0=0.25, tox=12.0, maxGap=1.7, minGap=0.2, smoothing=1e-8, GMIN=1e-12, Kclip=50.0)   # [SP] rram.va defaults


def vt(temp_c: float = 27.0) -> float:
    return K_B_EV * (temp_c + T0_K)


def current(v, gap, p: dict = P):
    v, gap = np.asarray(v, float), np.asarray(gap, float)
    return p["I0"] * np.exp(-gap / p["g0"]) * np.sinh(v / p["V0"]) + p["GMIN"] * v


def r_read(gap, v: float = 0.1, p: dict = P):
    return v / current(v, gap, p)


def gap_for_r(r, v: float = 0.1, p: dict = P):
    """Gap (nm) whose secant resistance at v is r (GMIN neglected: < 1e-6 relative for r < 1 Mohm)."""
    return p["g0"] * np.log(np.asarray(r, float) * p["I0"] * np.sinh(v / p["V0"]) / v)


def smoothstep(x, s):
    return 0.5 * x / np.sqrt(x * x + s) + 0.5


def gap_rate_nm_s(v, gap, temp_c: float = 27.0, p: dict = P):
    """dGap/dt in nm/s at device voltage v (V) and gap (nm): the physical term plus both clamps."""
    v, gap = np.asarray(v, float), np.asarray(gap, float)
    t = vt(temp_c)
    gamma = p["gamma0"] - p["Beta"] * gap ** 3
    ddt = -p["Vel0"] * np.exp(-p["Ea"] / t) * np.sinh(v * gamma * p["a0"] / p["tox"] / t)
    f1, f2 = smoothstep(p["minGap"] - gap, p["smoothing"]), smoothstep(gap - p["maxGap"], p["smoothing"])
    clip_min = (np.exp(np.minimum(p["Kclip"] * (p["minGap"] - gap), 80.0)) - ddt) * f1
    clip_max = (-np.exp(np.minimum(p["Kclip"] * (gap - p["maxGap"]), 80.0)) - ddt) * f2
    return 1e9 * (ddt + clip_min + clip_max)


def physical_rate_nm_s(v, gap, temp_c: float = 27.0, p: dict = P):
    """The physical (field- and temperature-activated) term alone, without the clamps."""
    v, gap = np.asarray(v, float), np.asarray(gap, float)
    t = vt(temp_c)
    return -1e9 * p["Vel0"] * np.exp(-p["Ea"] / t) * np.sinh(v * (p["gamma0"] - p["Beta"] * gap ** 3) * p["a0"] / p["tox"] / t)


def zero_bias_clamp_rate_nm_s(gap, p: dict = P):
    """At V = 0 the physical term is exactly zero; this is the clamp tail alone (a numerical artefact of `smoothing`)."""
    return gap_rate_nm_s(0.0, gap, p=p)
