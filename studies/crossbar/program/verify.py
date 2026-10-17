"""1D-ii D2: the program-verify loop, run on the compiled model's pulse flow maps (program/tables.py), vectorised over a Monte-Carlo population of devices.

Loop (per device, all devices of a row in parallel - 1D-i: 160 per pulse):
    read (verify) -> in window? done : choose the next pulse -> apply it -> read -> ...
  - incremental-step pulse programming (ISPP) in the direction of the target: amplitude starts at v0 and rises by dv after every pulse that left the device short of the
    window; a pulse that carries the device PAST the window (measured) reverses the polarity and restarts the opposite ISPP at its own v0 (bidirectional correction);
  - stop when the verify read lands inside the window, or after n_max pulses (a failure: the device keeps whatever it has).
Verify read: 1F's read conditions - row line 0.35 V, sense node 0.25 V, word line 1.1 V, the BSIM4 access transistor on the bitline side (program/read_conditions.py:
at this bias R_tx is ~2 kohm, not the 1016 ohm 1A measured with the source at 0 V) - and 1F's measured per-read random error of the front-end
(thermal + comparator + reset, T = 1 or 2 ns) averaged over n_avg reads: I_meas = I_true(gap) + sigma_read / sqrt(n_avg) * N(0, 1). The window is +/- w on the device
conductance, translated to the two read-current thresholds the comparator uses.
Switching variability: the compact model is DETERMINISTIC (no cycle-to-cycle or device-to-device term). It is imposed as a lognormal scale on the effective pulse duration,
k = exp(sigma_c2c N(0,1)) per pulse and exp(sigma_d2d N(0,1)) per device - the form of an activation-energy / attempt-rate fluctuation (Vel0 exp(-Ea/kT)) - [ASSUM, swept,
zero is a valid point: it is the model's own answer].
Outputs per run: the achieved ln-conductance spread of the device (sigma_lnG as the budget defines it: spread of ln(I0 exp(-gap/g0)) = gap / g0), the yield, pulses, time and
energy per device.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from program.cell import read_current
from program.model import P

G0 = P["g0"]
GAP_GRID = np.linspace(0.0, 2.0, 4001)


@dataclass(frozen=True)
class Loop:
    g_target: float                    # nm, the target gap (the target conductance is I0 exp(-g/g0))
    w: float = 0.05                    # +/- relative window on the device conductance
    n_max: int = 30                    # pulses allowed
    t_w: float = 1e-6                  # s pulse width of the polarity that moves TOWARD the target (SET for an LRS target, RESET for an HRS target)
    t_w_corr: float | None = None      # s width of the opposite (corrective) polarity; None = t_w
    v0_set: float = 1.0                # V first SET amplitude
    v0_reset: float = 0.8              # V first RESET amplitude
    dv: float = 0.05                   # V ISPP step
    v_max_set: float = 2.4
    v_max_reset: float = 2.4
    sigma_read_a: float = 1.42e-6      # A, single verify read, 1 sigma [SIM, 1F: thermal + comparator at T = 1 ns, vb 0.50]
    n_avg: int = 1                     # verify reads averaged
    sigma_c2c: float = 0.0             # ln-scale of the effective pulse duration, per pulse [ASSUM]
    sigma_d2d: float = 0.0             # ln-scale per device [ASSUM]
    t_read_s: float = 10e-9            # one verify read (1F cycle)
    t_mode_s: float = 10e-9            # write <-> verify switch-over (2 x 5 ns, 1D-i)
    e_read_j: float = 228e-12 / 160    # J per device per verify read: 1F's 228 pJ per full-array read shared by 160 columns
    one_sided: bool = False            # accept any device whose measured conductance is BELOW the window's upper edge (an HRS only has to be high-resistance enough)
    start: str = "hrs"                 # where devices start: "hrs" (gap ~ U(1.55, 1.7)) or "lrs" (gap ~ U(g_lo, g_lo + 0.15)) or a float gap
    start_spread: float = 0.15

    def with_(self, **kw) -> "Loop":
        return replace(self, **kw)


class Maps:
    """Pulse flow maps for both polarities: interpolated in gap (linear, 5 pm grid) and in log(width) (linear) - the width interpolation is what the imposed variability
    uses; at k = 1 and a grid width it is exact table lookup."""

    def __init__(self, set_t: dict, reset_t: dict):
        self.t = dict(set=set_t, reset=reset_t)
        self.lw = {k: np.log(v["widths"]) for k, v in self.t.items()}

    def volts(self, d: str) -> np.ndarray:
        return self.t[d]["volts"]

    def _interp(self, d: str, what: str, iv: np.ndarray, t_eff: np.ndarray, g: np.ndarray) -> np.ndarray:
        T = self.t[d]
        lw = self.lw[d]
        x = np.clip(np.log(t_eff), lw[0], lw[-1])
        j = np.clip(np.searchsorted(lw, x) - 1, 0, len(lw) - 2)
        fr = (x - lw[j]) / (lw[j + 1] - lw[j])
        gg = T["gaps"]
        gi = np.clip(g, gg[0], gg[-1])
        k = np.clip(np.searchsorted(gg, gi) - 1, 0, len(gg) - 2)
        fg = (gi - gg[k]) / (gg[k + 1] - gg[k])
        A = T[what]

        def at(jj):
            return A[iv, jj, k] * (1 - fg) + A[iv, jj, k + 1] * fg
        return at(j) * (1 - fr) + at(j + 1) * fr

    def step(self, d: str, iv: np.ndarray, t_eff: np.ndarray, g: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        g_new = self._interp(d, "gap_out", iv, t_eff, g)
        e = self._interp(d, "energy_j", iv, t_eff, g)
        # gaps outside the table range (below 0.2 / above 1.7: the clamp tails) move with the edge row of the map
        lo, hi = self.t[d]["gaps"][0], self.t[d]["gaps"][-1]
        g_new = np.where(g < lo, g + (g_new - lo), np.where(g > hi, g + (g_new - hi), g_new))
        return g_new, e


_I_CACHE: dict = {}


def i_read(g: np.ndarray, r_tx: float | str = "bl|27.0") -> np.ndarray:
    """Branch read current vs gap. r_tx: a key of results/program_verify/read_conditions.json's BSIM4 read table ('bl|27.0' default), or a number = 1F's linear port."""
    key = r_tx
    if key not in _I_CACHE:
        if isinstance(r_tx, str):
            import json
            import paths as RP
            t = json.loads((RP.PROGRAM / "read_conditions.json").read_text())["read_table"]
            _I_CACHE[key] = (np.array(t["gaps"]), np.array(t[r_tx]))
        else:
            _I_CACHE[key] = (GAP_GRID, read_current(GAP_GRID, r_tx=r_tx))
    gg, ii = _I_CACHE[key]
    return np.interp(g, gg, ii)


def window_gaps(g_target: float, w: float) -> tuple[float, float]:
    """+/- w on the conductance: G in [G_t (1 - w), G_t (1 + w)]  <=>  gap in [g_t - g0 ln(1 + w), g_t - g0 ln(1 - w)]."""
    return g_target - G0 * np.log1p(w), g_target - G0 * np.log1p(-w)


def run(L: Loop, maps: Maps, n: int = 4000, seed: int = 1, r_tx: float | str = "bl|27.0", record: bool = False) -> dict:
    rng = np.random.default_rng(seed)
    g_lo, g_hi = window_gaps(L.g_target, L.w)
    i_hi_thr, i_lo_thr = i_read(np.array([g_lo]), r_tx)[0], i_read(np.array([g_hi]), r_tx)[0]      # small gap = large current
    if isinstance(L.start, float):
        g = L.start + L.start_spread * (rng.random(n) - 0.5)
    elif L.start == "hrs":
        g = 1.7 - L.start_spread * rng.random(n)
    else:
        g = 0.2 + L.start_spread * rng.random(n)
    g = g.astype(float)
    vs, vr = maps.volts("set"), maps.volts("reset")
    k_dev = np.exp(L.sigma_d2d * rng.standard_normal(n))
    sig_m = L.sigma_read_a / np.sqrt(L.n_avg)

    def measure(gg):
        return i_read(gg, r_tx) + sig_m * rng.standard_normal(gg.shape)

    if L.one_sided:
        i_lo_thr = -np.inf
    im = measure(g)
    done = (im >= i_lo_thr) & (im <= i_hi_thr)
    direction = np.where(im < i_lo_thr, 1, -1)          # +1: needs SET (gap too large, current too small), -1: needs RESET
    amp_set = np.full(n, L.v0_set)
    amp_res = np.full(n, L.v0_reset)
    pulses = np.zeros(n, int)
    pulse_time = np.zeros(n)
    energy = np.zeros(n)
    reads = np.ones(n, int)
    hist = []
    for it in range(L.n_max):
        act = ~done
        if not act.any():
            break
        lrs_target = L.g_target < 0.95
        tw_set = L.t_w if lrs_target else (L.t_w_corr or L.t_w)
        tw_res = (L.t_w_corr or L.t_w) if lrs_target else L.t_w
        for d, sign, amp, vgrid, tw in (("set", 1, amp_set, vs, tw_set), ("reset", -1, amp_res, vr, tw_res)):
            m = act & (direction == sign)
            if not m.any():
                continue
            iv = np.clip(np.round((amp[m] - vgrid[0]) / (vgrid[1] - vgrid[0])).astype(int), 0, len(vgrid) - 1)
            t_eff = tw * k_dev[m] * np.exp(L.sigma_c2c * rng.standard_normal(m.sum()))
            g_new, e = maps.step(d, iv, t_eff, g[m])
            g[m] = g_new
            energy[m] += e
            pulses[m] += 1
            pulse_time[m] += tw + 2e-9
        im_a = measure(g[act])
        reads[act] += 1
        in_w = (im_a >= i_lo_thr) & (im_a <= i_hi_thr)
        need = np.where(im_a < i_lo_thr, 1, -1)
        idx = np.flatnonzero(act)
        done[idx[in_w]] = True
        rev = (~in_w) & (need != direction[idx])          # overshoot: polarity reverses, the new direction restarts at its v0
        cont = (~in_w) & (need == direction[idx])
        ii = idx[cont]
        amp_set[ii] = np.where(direction[ii] == 1, np.minimum(amp_set[ii] + L.dv, L.v_max_set), amp_set[ii])
        amp_res[ii] = np.where(direction[ii] == -1, np.minimum(amp_res[ii] + L.dv, L.v_max_reset), amp_res[ii])
        jj = idx[rev]
        direction[jj] = need[rev]
        amp_set[jj] = L.v0_set
        amp_res[jj] = L.v0_reset
        if record:
            hist.append(dict(it=it, done=float(done.mean()), sigma_lnG_done=float(np.std(g[done] / G0)) if done.sum() > 2 else None))
    lnG = -g / G0
    lnG_t = -L.g_target / G0
    ok = done
    t_dev = pulse_time + reads * L.n_avg * L.t_read_s + pulses * L.t_mode_s
    out = dict(yield_=float(ok.mean()), sigma_lnG=float(np.std(lnG[ok])) if ok.sum() > 2 else float("nan"), sigma_lnG_all=float(np.std(lnG)),
               bias_lnG=float(np.mean(lnG[ok]) - lnG_t) if ok.any() else float("nan"), rms_lnG_all=float(np.sqrt(np.mean((lnG - lnG_t) ** 2))),
               frac_outside_window_true=float(np.mean((g[ok] < g_lo) | (g[ok] > g_hi))) if ok.any() else float("nan"),
               pulses_mean=float(pulses.mean()), pulses_p99=float(np.percentile(pulses, 99)), reads_mean=float(reads.mean()), time_mean_s=float(t_dev.mean()),
               time_p99_s=float(np.percentile(t_dev, 99)), time_max_s=float(t_dev.max()), energy_mean_j=float(energy.mean()) + float(reads.mean()) * L.n_avg * L.e_read_j,
               energy_pulse_mean_j=float(energy.mean()), n=n)
    # a row finishes when its slowest device does: expected max over 160 devices of the pulse count, from the empirical distribution
    srt = np.sort(pulses)
    out["pulses_row_max_mean"] = float(np.mean([srt[min(len(srt) - 1, int(len(srt) * (1 - 1 / 161)))]]))
    srt_t = np.sort(t_dev)
    out["time_row_s"] = float(srt_t[min(len(srt_t) - 1, int(len(srt_t) * (1 - 1 / 161)))])
    if record:
        out["history"] = hist
        out["gaps_final"] = g.tolist()
    return out
