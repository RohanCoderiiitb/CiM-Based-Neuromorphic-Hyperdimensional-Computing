"""C1 (a) profile and (c) ladder-table size from results/full_column/group_tables_r*.json. Writes group_profile_r*.csv and ladder_table_size.json.
Usage: python -m scaleup.table_size"""
from __future__ import annotations

import paths as RP

import csv
import json
import math

import numpy as np

import device.constants as C

LSBS_UA = (0.02, 0.05, 0.1, 0.2, 0.5, 1.0)       # [CHOICE] threshold quantisation steps examined; a threshold stored to +/- LSB/2 is a deterministic budget term


def thr_matrix(tabs: list[dict]) -> tuple[np.ndarray, list[tuple[int, int]]]:
    keys = [(a, k) for a in range(1, C.G_1C + 1) for k in range(a)]
    return np.array([[t["thr"][str(a)][k] for a, k in keys] for t in tabs]), keys


def main() -> None:
    out = {}
    for r in C.BL_R_PER_PITCH_SWEEP:
        tabs = json.loads(RP.full_column_tables(r).read_text())
        T, keys = thr_matrix(tabs)                                        # (64, 36)
        span = np.array([t["span"] for t in tabs]); step = np.array([t["worst_step_full"] for t in tabs]); stepall = np.array([t["worst_step"] for t in tabs])
        with (RP.FULL_COLUMN / f"group_profile_r{r}.csv").open("w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["group", "first_row_pos", "level_span_uA", "worst_step_a8_uA", "worst_step_any_a_uA", "span_vs_near", "step_vs_near", "within_group_halfrange_uA",
                                            "heldout_dev_uA", "antisym_dev_uA", "usable_halfstep_uA"])
            for t, sp, st, sa in zip(tabs, span, step, stepall):
                w.writerow([t["G"], t["pos0"], f"{sp*1e6:.3f}", f"{st*1e6:.3f}", f"{sa*1e6:.3f}", f"{sp/span[0]:.4f}", f"{st/step[0]:.4f}", f"{t['within_a']*1e6:.4f}",
                            f"{t['held_dev_a']*1e6:.4f}", f"{t['antisym_dev']*1e6:.4f}", f"{0.5*(1-C.HEADROOM)*sa*1e6:.3f}"])
        # antisymmetry: threshold(a, k) vs -threshold(a, a-1-k)
        anti = np.array([[abs(t["thr"][str(a)][k] + t["thr"][str(a)][a - 1 - k]) for a, k in keys] for t in tabs])
        n_thr = len(keys); n_half = sum((a + 1) // 2 for a in range(1, C.G_1C + 1))
        tmax = np.abs(T).max(axis=1)
        sizes = {}
        for q in LSBS_UA:
            bits_g = np.ceil(np.log2(2 * tmax / (q * 1e-6) + 1)).astype(int)            # signed word covering +/- tmax_G at step q
            bits_u = int(np.max(bits_g))
            sizes[str(q)] = dict(bits_per_threshold_worst_group=bits_u, full_per_group_range=int((bits_g * n_thr).sum()), full_uniform_width=int(bits_u * n_thr * len(tabs)),
                                 half_per_group_range=int((bits_g * n_half).sum()), half_uniform_width=int(bits_u * n_half * len(tabs)), quant_error_halfLSB_uA=q / 2)
        # factorised: thr_G(a,k) ~ sum_{i<rank} u_G,i v_i(a,k)
        U, S, Vt = np.linalg.svd(T, full_matrices=False)
        fact = {}
        for rank in (1, 2, 3):
            approx = (U[:, :rank] * S[:rank]) @ Vt[:rank]
            fact[str(rank)] = dict(max_resid_uA=float(np.abs(approx - T).max() * 1e6), mean_resid_uA=float(np.abs(approx - T).mean() * 1e6),
                                   far_group_max_resid_uA=float(np.abs(approx - T)[-1].max() * 1e6))
        out[str(r)] = dict(r=r, n_groups=len(tabs), thresholds_per_group=n_thr, thresholds_per_group_half=n_half, thresholds_total=n_thr * len(tabs),
                           levels_per_group=sum(a + 1 for a in range(1, C.G_1C + 1)), span_near_uA=span[0] * 1e6, span_far_uA=span[-1] * 1e6, span_ratio_near_over_far=float(span[0] / span[-1]),
                           step_near_uA=step[0] * 1e6, step_far_uA=step[-1] * 1e6, step_ratio_near_over_far=float(step[0] / step[-1]),
                           worst_step_any_a_far_uA=float(stepall[-1] * 1e6), worst_step_any_a_near_uA=float(stepall[0] * 1e6),
                           monotone_span=bool(np.all(np.diff(span) < 0)), monotone_step_a8=bool(np.all(np.diff(step) < 0)), monotone_step_any_a=bool(np.all(np.diff(stepall) <= 1e-12)),
                           antisym_dev_max_uA=float(anti.max() * 1e6), antisym_dev_far_uA=float(anti[-1].max() * 1e6), antisym_dev_near_uA=float(anti[0].max() * 1e6),
                           antisym_half_error_far_uA=float(anti[-1].max() * 0.5e6), sizes=sizes, factorised=fact,
                           max_within_halfrange_uA=float(max(t["within_a"] for t in tabs) * 1e6), max_heldout_dev_uA=float(max(t["held_dev_a"] for t in tabs) * 1e6))
        o = out[str(r)]
        print(f"r={r}: span {o['span_near_uA']:.0f}->{o['span_far_uA']:.0f} uA ({o['span_ratio_near_over_far']:.2f}x), step {o['step_near_uA']:.1f}->{o['step_far_uA']:.1f} uA ({o['step_ratio_near_over_far']:.2f}x); "
              f"monotone span/step(a=8)/step(any a): {o['monotone_span']}/{o['monotone_step_a8']}/{o['monotone_step_any_a']}; antisym dev max {o['antisym_dev_max_uA']:.3f} far {o['antisym_dev_far_uA']:.3f} uA; "
              f"thresholds {o['thresholds_total']} (half {n_half*len(tabs)}); bits @0.1uA full {sizes['0.1']['full_per_group_range']} half {sizes['0.1']['half_per_group_range']}; rank1 resid {fact['1']['max_resid_uA']:.2f} rank2 {fact['2']['max_resid_uA']:.2f}")
    (RP.FULL_COLUMN / "ladder_table_size.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
