"""F3: energy per inference with the sense front-end, the threshold path and the supply at the pulse length the front-end needs, against NeuroHDC-small's 3.01 uJ.

Components (per inference, 1E's real read pattern, a = 0 reads skipped = the 1E follow-up):
  array            1C's array energy E_arr(T) (scaleup.energy_inference, 5 macros, ideal supply at V_READ = 0.1 V) x (V_VG + V_READ)/V_READ: the row supply must sit V_READ above the held sense node [SIM, 1C] x [MODEL]
  word line        1C, 16 nJ
  sense bias       160 columns x VDD x ( I_idle(vb) x (t_en(vb) + T + tail) + I_signal x (T + tail) ) per non-zero read: front-end powered only for its own read (t_en = measured power-up) [SIM]
  decision stage   preamplifier 51 uA x VDD during each comparison (0.3 ns), n_cmp comparisons (binary search, mean over the a-distribution), plus latch and capacitor-DAC switching [SIM + ASSUM]
  threshold path   digital correction of the thresholds per read (sense.threshold_path): energy per op from Horowitz ISSCC 2014 (45 nm) [ASSUM, cited]
  supply           loss in R_pad recharging the decoupling between reads: C_dec V^2 / 2 x (R_loss fraction) is NOT counted as it is returned by the regulator only in part - reported separately as 'decap recharge'
Exclusions named (as in 1C): table reads of the class hypervectors / HDC side, 1E digital logic (flip-flops), clock tree. Included here that 1C excluded: the sense front-end, its bias and the threshold path.
Usage: python -m sense.energy_1f"""
from __future__ import annotations

import json

import numpy as np

import device.constants as C
import paths as RP

VDD = 1.1
V_VG = 0.25
N_COL = C.FULL_CELLS
NEUROHDC_J = 3.01e-6
E_WL_J = 16.0e-9
COMP_I_A = 51e-6                    # preamplifier current (sense.comparator, W = 32 um) [SIM]
T_CMP = 0.3e-9
E_LATCH_J = 10e-15                  # latch regeneration per comparison [ASSUM]
E_DAC_J = 100e-15                   # threshold capacitor-array switching per comparison [ASSUM]
HOROWITZ = dict(mult12_J=0.45e-12, add12_J=0.05e-12, sram_read_per_bit_J=10e-12 / 64)    # 45 nm: 8-bit mult 0.2 pJ scaled (12/8)^2; 16-bit add 0.05 pJ; 8 KB SRAM 10 pJ / 64 bit [ASSUM, Horowitz ISSCC 2014]


def load():
    arr = json.loads((RP.FULL_ARRAY / "energy_per_inference.json").read_text())
    en = json.loads((RP.SENSE / "enable_and_supply.json").read_text())
    rc = json.loads((RP.SENSE / "read_counts.json").read_text())
    return arr, en, rc


def n_comparisons(hist: list[float]) -> float:
    """Mean number of comparisons of a binary search over the a + 1 possible match counts, over the non-zero reads."""
    h = np.array(hist[1:], float); a = np.arange(1, len(h) + 1)
    return float((h * np.ceil(np.log2(a + 1))).sum() / h.sum())


def threshold_path_J(g: int, mode: str, rc: dict) -> float:
    """Digital energy per inference of delivering the corrected thresholds (see sense.threshold_path for the options)."""
    r = rc[str(g)]; nc = n_comparisons(r["a_hist"]); h = HOROWITZ
    if mode == "per_column_digital":           # gain(c) = sum_r u_r(c) v_r (3 MAC) then thr x gain per comparison, 160 columns
        e = N_COL * (3 * (h["mult12_J"] + h["add12_J"]) + nc * h["mult12_J"])
    elif mode == "per_position_digital":       # the 32 distinct column positions of a macro row (5 macros share them)
        e = C.CELLS_PER_MACRO_ROW * (3 * (h["mult12_J"] + h["add12_J"]) + nc * h["mult12_J"])
    elif mode == "stored_corrected":           # corrected thresholds stored per (position, group, a, comparison): one SRAM read of nc x 32 x 12 bit per read
        e = C.CELLS_PER_MACRO_ROW * nc * 12 * h["sram_read_per_bit_J"]
    else:
        raise ValueError(mode)
    return e * r["reads_nonzero"]


def energy(vb: float, T: float, tail: float, g: int = 8, thr_mode: str = "per_position_digital", v_vg: float = V_VG) -> dict:
    arr, en, rc = load()
    r = rc[str(g)]
    key = {0.42: "0.42", 0.46: "0.46", 0.5: "0.5"}[round(vb, 2)]
    sup = en[key]["supply_uA"]; t_en = en[key]["power_up"]["t_settle_ns"] * 1e-9
    i_idle = float(np.mean([sup["far"]["idle"], sup["near"]["idle"]])) * 1e-6
    i_sig8 = float(np.mean([np.mean([sup[w][str(m)] - sup[w]["idle"] for m in range(9)]) for w in ("far", "near")])) * 1e-6
    i_sig = i_sig8 * r["mean_active_per_nonzero"] / 8.0
    # array energy at pulse length T from the 1C table (interpolated, linear in T beyond the table)
    tab = arr["energy_per_inference_J"]; ts = sorted(float(k) for k in tab); e_arr1c = np.interp(T, ts, [tab[str(t)]["array_J"] for t in ts])
    e_arr = e_arr1c * (v_vg + C.V_READ) / C.V_READ
    nread = r["reads_nonzero"]
    nc = n_comparisons(r["a_hist"])
    e_sense = nread * N_COL * VDD * (i_idle * (t_en + T + tail) + i_sig * (T + tail))
    e_dec = nread * N_COL * (COMP_I_A * VDD * T_CMP + E_LATCH_J + E_DAC_J) * nc
    e_thr = threshold_path_J(g, thr_mode, rc)
    tot = e_arr + E_WL_J + e_sense + e_dec + e_thr
    return dict(vb=vb, T=T, tail=tail, g=g, thr_mode=thr_mode, t_en_ns=t_en * 1e9, i_idle_uA=i_idle * 1e6, i_sig_uA=i_sig * 1e6, n_cmp=nc, reads_nonzero=nread,
                array_J=e_arr, array_1c_J=e_arr1c, wordline_J=E_WL_J, sense_bias_J=e_sense, decision_J=e_dec, threshold_J=e_thr, total_J=tot, ratio_to_neurohdc=tot / NEUROHDC_J,
                per_read_pJ=tot / nread * 1e12, sense_per_col_read_pJ=e_sense / nread / N_COL * 1e12)


def main() -> None:
    rows = []
    for vb in (0.42, 0.46, 0.5):
        for T, tail in ((0.5e-9, 0.3e-9), (1e-9, 0.3e-9), (1e-9, 1e-9), (2e-9, 1e-9)):
            for g in (4, 8):
                rows.append(energy(vb, T, tail, g))
    for r in rows:
        print(f"vb {r['vb']} T {r['T']*1e9:g} tail {r['tail']*1e9:g} g {r['g']}: total {r['total_J']*1e6:.2f} uJ ({r['ratio_to_neurohdc']:.2f}x 3.01): array {r['array_J']*1e6:.2f} sense {r['sense_bias_J']*1e6:.2f} decision {r['decision_J']*1e6:.2f} threshold {r['threshold_J']*1e6:.2f}")
    thr = {m: {g: energy(0.46, 2e-9, 1e-9, g, m)["threshold_J"] * 1e6 for g in (4, 8)} for m in ("per_column_digital", "per_position_digital", "stored_corrected")}
    print("threshold path uJ per inference:", thr)
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "energy_per_inference_1f.json").write_text(json.dumps(dict(rows=rows, threshold_options_uJ=thr), indent=1, default=float))


if __name__ == "__main__":
    main()
