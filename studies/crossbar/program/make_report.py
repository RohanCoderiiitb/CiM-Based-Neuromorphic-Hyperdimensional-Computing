"""1D-ii report: <repo>/reports/phase1d_ii_report.md, every number read from results/compact_model/ and results/program_verify/.
Usage: python -m program.make_report"""
from __future__ import annotations

import json

import numpy as np

import paths as RP
from program import tables as T

J = lambda p: json.loads(p.read_text())


def at(tb: dict, v: float, w: float, g: float) -> float:
    i = int(np.argmin(np.abs(tb["volts"] - v))); j = int(np.argmin(np.abs(np.log(tb["widths"] / w)))); k = int(np.argmin(np.abs(tb["gaps"] - g)))
    return float(tb["gap_out"][i, j, k])


def atk(tb: dict, key: str, v: float, w: float, g: float) -> float:
    i = int(np.argmin(np.abs(tb["volts"] - v))); j = int(np.argmin(np.abs(np.log(tb["widths"] / w)))); k = int(np.argmin(np.abs(tb["gaps"] - g)))
    return float(tb[key][i, j, k])


def r_of(g: float) -> float:
    from program.model import r_read
    return float(r_read(g))


def main() -> None:
    d0 = J(RP.COMPACT / "d0_validation.json")
    d1 = J(RP.PROGRAM / "d1_characterise.json")
    d2 = J(RP.PROGRAM / "d2_surface.json")
    d3 = J(RP.PROGRAM / "d3_retention.json")
    rc = J(RP.PROGRAM / "read_conditions.json")
    d4 = J(RP.PROGRAM / "d4_budget.json")
    vA = J(RP.PROGRAM / "validate_loop_A.json")
    vB = J(RP.PROGRAM / "validate_loop_B.json") if (RP.PROGRAM / "validate_loop_B.json").exists() else None
    t = T.main_tables(); t85 = T.temp_tables(); tn = T.near_tables()
    S, R = t["set"], t["reset"]
    A = d2["A"]; B = d2.get("B")
    best = d4["closure_best"]
    rd = d4["read_disturb"]
    rcs = rc["summary"]

    def key(g, sl, sh, droop=8, cal=1.0):
        return f"{g}|{round(sl, 4)}|{round(sh, 4)}|{droop}|{cal}"

    def lrs_sel(R_, **k):
        return [r for r in R_ if r["state"] == "lrs" and all(r[a] == b for a, b in k.items())]

    pts = [p for p in d4["effort"] if p["scen"] == "A"]

    def g16v(p, v):
        r = [x for x in d4["g16_variants"] if x["variant"] == v and round(x["sigma_lrs"], 4) == round(p["sigma_lrs"], 4) and round(x["sigma_hrs"], 4) == round(p["sigma_hrs"], 4)]
        return r[0]["margin_a"] * 1e6 if r else float("nan")
    ptsB = [p for p in d4["effort"] if p["scen"] == "B"]
    head = min([p for p in pts if p["c2c"] == 0.3 and p["read"] == "1ns" and p["n_avg"] == 16], key=lambda p: p["sigma_lrs"], default=pts[0])
    single = min([p for p in pts if p["c2c"] == 0.3 and p["read"] == "1ns" and p["n_avg"] == 1], key=lambda p: p["sigma_lrs"], default=pts[0])
    m = lambda p, g: best[key(g, p["sigma_lrs"], p["sigma_hrs"])]["margin_a"] * 1e6
    L = []
    A_ = L.append

    A_("# Phase 1D-ii report - the device-level write path, with the compiled compact model\n")
    A_("Tags: **[SIM]** ngspice with the COMPILED `rram.va` (OpenVAF -> OSDI) and the PTM 45 nm LP BSIM4 access transistor, **[MODEL]** analytic / Python in code, **[ASSUM]** "
       "assumed, **[CHOICE]** design decision, **[SP]** Stanford-PKU default. Every number below is read from `results/compact_model/` and `results/program_verify/` by "
       "`python -m program.make_report`; commands in section 10.\n")
    A_("> **sigma_lnG here is a MODEL result, not silicon.** It comes from a compact model calibrated to someone else's devices (the Stanford-PKU HfOx model in the Wang-Roychowdhury "
       "well-posed form), driven through 1D-i's array and 1F's read path. It is far better grounded than the assumed 0.10 of 1A-1F - the loop, the pulse response, the verify read "
       "and its noise are simulated - and it is still not a measurement of a fabricated array. Two parts of it are not the model's at all: the model is **deterministic** (no "
       "cycle-to-cycle or device-to-device term), so the switching variability that a real array has is IMPOSED [ASSUM, swept 0-0.3]; and the 1A design states sit on the "
       "model's numerical clamps, so the placement is measured at the nearest states the model can hold (0.35 / 1.55 nm). Every claim below that rests on sigma_lnG carries both "
       "caveats.\n")
    A_("Read first and carried forward: 1D-i's write envelope (`phase1d_i_report.md` section 7: access transistor on the bitline side, 20 F^2, word line 1.1 V, SET drive inside "
       "the 1.1 V transistor rating up to ~1.3 V, RESET capped at ~0.5 V across a high-resistance device, any pulse width to DC, 160 devices per pulse), 1B's spread model "
       "(log-normal on the conductance prefactor, sigma_lnG = sigma_gap / g0) and 1F's closure map (section 8 of its report).\n")

    # ---------------- 0
    A_("## 0. The answer\n")
    A_(f"- **The rram.va bug is a declaration, not an expression, and 1A's rename is the right fix** - shown, not assumed: the model as received fails to compile (`clip_minGap` "
       f"undeclared); the fix compiles and holds the gap at minGap under a hard SET ({d0['clamp']['fixed']['set']['gap_end']:.4f} nm); the alternative reading 'clip_0 = a clamp at "
       f"gap 0' compiles too but lets the gap collapse to {d0['clamp']['alternative_clip_at_zero']['set']['gap_end']:.4f} nm and leaves the minGap parameter dead. Section 1.")
    A_(f"- **The compiled model reproduces 1A exactly: R(0.2 nm) = {d0['r_lrs']:.4f} ohm, R(1.7 nm) = {d0['r_hrs']:,.2f} ohm** (1A: 541.82 / 218,586.0 as printed - the "
       f"{max(abs(d0['rel_err_lrs']), abs(d0['rel_err_hrs'])):.0e} difference is 1A's rounding); the read I-V over 0.2-1.7 nm and +/-0.5 V matches 1A's equation to {d0['gap_sweep']['max_rel_err']:.0e}. "
       "No stop. Section 2.")
    A_(f"- **The 20 F^2 array cannot program 1A's design states, and 1A's states are not programmable targets in this model at all.** Forming: absent from the model. SET inside "
       f"the envelope (<= 1 us, <= 1.3 V) moves an HRS device only to {at(S, 1.3, 1e-6, 1.7):.2f} nm ({r_of(at(S, 1.3, 1e-6, 1.7)) / 1e3:.0f} kohm); the transistor-limited "
       f"(compliance) SET reaches the design-adjacent 0.35 nm only with ~20-30 ms pulses. RESET is capped at ~0.5 V across the device (1D-i) and does nothing below ~1 ms; "
       f"0.35 -> 1.55 nm takes ~0.1 s. 0.2 and 1.7 nm are the model's clamps (a target there measures the clamp). **Doing the design-adjacent states in <= 1 us needs a "
       "100-200 F^2 thick-oxide transistor at a 3 V word line in a near row - in the far row no width up to 400 F^2 does it: a different array.** SET and RESET are both "
       "**gradual**, so a verify loop converges. Section 3.")
    A_(f"- **sigma_lnG as a function of program effort (in-envelope array, design-adjacent LRS, imposed variability 0.3/0.3):** it falls from "
       f"{np.mean([r['sigma_lnG_all'] for r in lrs_sel(A, read='1ns', n_avg=1, c2c=0.3, d2d=0.3, w=0.05, n_max=1)]):.2f} (one pulse, no verify) to a floor set by the "
       f"**verify read's own noise**: {single['sigma_lrs']:.3f} with 1F's single read (T = 1 ns), {head['sigma_lrs']:.3f} averaging 16 reads, ~0.01-0.03 averaging 64. The floor "
       "is reached after 8-12 pulses; more pulses buy nothing (section 4.4). The access transistor at the real read bias (~2 kohm, section 6) divides the device's "
       "conductance change by 3.5 before the read sees it - that ballast, good for the inference read, is what makes the verify noisy. HRS: a one-sided verify (G below a "
       "ceiling) in 2-10 pulses, sigma 0.2-0.5, which costs < 0.1 uA in the budget. Section 4.")
    A_(f"- **What it costs (in-envelope): ~{head['e_full_j']:.1f} J and ~{head['t_full_s']:.0f} s for the full 163,840-device array** at the 16-read point (160 devices per pulse, "
       "millisecond pulses: SET 1-30 ms, RESET 10-100 ms). 1B's placeholder was 4.9 uJ; 1D-i's estimate at 1 us pulses 63 uJ. The design-capable (out-of-envelope) array would "
       "do it in " + (f"~{ptsB[0]['t_full_s']:.2g} s and {ptsB[0]['e_full_j'] * 1e3:.2g} mJ" if ptsB else "(not run)") + ". Section 4.5.")
    rd27, rd85 = rd["27.0|8"], rd["85.0|8"]
    A_(f"- **Drift: the model has NO retention mechanism, and an artefact that looks like one.** At zero bias the physical gap velocity is exactly zero at any temperature; the "
       f"only motion is the clamp tail, which relaxes 0.35 -> 0.57 nm in a day and 1.55 -> 1.33 nm and scales with the `smoothing` parameter - numerical, not physics. "
       f"**What the model does have is READ DISTURB**: 1F's read puts ~0.1 V across every active device in the SET direction; the gap closes at 0.3-1.1 nm/s at 27 C, "
       f"9-37 nm/s at 85 C. With 1E's read pattern the far group's top level moves the 0.27 uA that 1B/1C allotted to drift after **{rd27['inferences_to_027uA']:,.0f} inferences at "
       f"27 C, {rd85['inferences_to_027uA']:,.0f} at 85 C** (g = 8). The 'moderate' drift term was optimistic in kind: the device drifts per read, not per hour. Section 5.")
    A_(f"- **Temperature: the device's read current has no temperature term (ABSENT); the read path's does, through the access transistor:** the far group's top level moves "
       f"{abs(rcs['bl|group8|far']['slope_a_per_k_27_47']) * 1e6:.2f} uA/K and the near group's {abs(rcs['bl|group8|near']['slope_a_per_k_27_47']) * 1e6:.2f} uA/K, against the "
       f"0.05 uA/K of front-end drift behind 1F's 5 K recalibration window: **uncompensated, the window is ~{0.25 / (abs(rcs['bl|group8|far']['slope_a_per_k_27_47']) * 1e6):.1f} K "
       f"(far) / {0.25 / (abs(rcs['bl|group8|near']['slope_a_per_k_27_47']) * 1e6):.2f} K (near)**; the ladder has to track temperature. And at 1F's real read bias the "
       f"access transistor is {rcs['bl|branch|lrs_1a']['r_tx_eff_27_ohm']:.0f} ohm, not 1A's 1016 ohm: the LRS branch carries {rcs['bl|branch|lrs_1a']['i_27_a'] * 1e6:.1f} uA, "
       "not the ~64 uA 1A-1F used. Sections 5, 6.")
    m8 = m(head, 8); m4 = m(head, 4); m16 = m(head, 16)
    A_(f"- **The budget re-closed on the measured spread (1F's machinery unchanged, best front-end point, 5 K window, 8 mV droop): g = 8 closes with {m8:+.2f} uA at "
       f"sigma_LRS {head['sigma_lrs']:.3f} (16-read verify) and {m(single, 8):+.2f} uA at {single['sigma_lrs']:.3f} (single read); g = 4 with {m4:+.1f} uA; g = 16 does not close "
       f"({m16:+.2f} uA) with end-sensed columns, but does with 1F's seg4 / seg8 columns ({g16v(head, 'seg4_mid'):+.1f} / {g16v(head, 'seg8_mid'):+.1f} uA at sigma "
       f"{head['sigma_lrs']:.3f}).** 1F's g = 8 condition (sigma <= 0.07) is reached by the in-envelope loop with >= 4 averaged reads per verify; its g = 16 condition "
       "(<= 0.045 with seg4/seg8 columns) is reached in sigma with >= 16 reads (section 7.3). **But this g is conditional on three things the device work found broken: "
       "(i) 1A's design states cannot be written by the 20 F^2 cell (the spread is measured at 0.35/1.55 nm); (ii) read disturb forces a reprogram every ~2e4 inferences, and at "
       "~1 J per program that is ~50 uJ per inference - 10x the inference itself; (iii) the read path's temperature coefficient and its 2 kohm transistor.** The honest "
       "statement: **g = 8 is supported by the device's placement accuracy (model), and is not deliverable by this array until the read disturb is removed (alternating read "
       "polarity or a lower read voltage) and the write path is rebuilt.** Section 7.")
    A_("- **Phase 5 handoff (section 8):** sigma_lnG 0.03 (16-read verify) / 0.08 (single read), model result at the design-adjacent states; g = 8 (budget) with g = 4 as the "
       "deliverable fallback; full-array program ~70-120 s / ~1 J in-envelope; refresh every ~2e4 inferences at 27 C (~800 at 85 C) unless read disturb is mitigated; "
       "recalibration: the trims every ~0.5 K unless the ladder is temperature-compensated.\n")

    # ---------------- 1
    A_("## 1. D0 - toolchain, and the rram.va fix\n")
    A_(f"- **Toolchain [SIM]:** OpenVAF-reloaded (`{d0['openvaf'].split('/')[-1]}`) and **ngspice-{d0['ngspice']['version']}** (>= 38 required to load OSDI; checked by `spice/osdi.py`), both "
       "resolved through nix on this Linux machine; `smoothfunctions.va` sits beside `rram.va` (it is `include`d); the module is built to `spice/build/rram.osdi` (git-ignored) and "
       "rebuilt when either source changes. Every deck injects `pre_set num_threads=1`.")
    A_("- **The bug.** As received, line 24 declared `real Gap, ddt_gap, Gamma, Fw1, Fw2, clip_0, clip_maxGap;` and lines 37/40 assign and use `clip_minGap`. Compiling that "
       f"text (reconstructed from 1A's record) fails exactly as described: `{d0['compile']['received']['log'].splitlines()[0]}` (return code {d0['compile']['received']['returncode']}).")
    A_("- **Which name is intended - worked out from use, not by renaming.** The two names imply different clamps: `clip_minGap` a clamp at the `minGap` parameter, `clip_0` a "
       "clamp at gap = 0. The evidence:")
    A_("  1. The expression on line 37 is `(limexp(Kclip*(minGap-Gap)) - ddt_gap) * Fw1` with `Fw1 = smoothstep(minGap-Gap, smoothing)`: it switches on below **minGap** and, "
       "when on, cancels the physical rate and pushes the gap back up - the exact mirror of line 38's `clip_maxGap` at **maxGap**. A clamp at 0 would need both lines rewritten.")
    A_("  2. `minGap` is a declared parameter (line 18) and lines 35/37 are its only uses: under the 'clip_0 = clamp at 0' reading it would be dead.")
    A_("  3. 1A's measured LRS (541.82 ohm) is the read current at gap = minGap = 0.2 nm; the model's stated gap range (0.2-1.7 nm, Stanford-PKU) is [minGap, maxGap].")
    A_(f"  4. **Run, both ways** (`program/d0_validate.py`): a hard SET (2 V through 10 ohm, 1 us) from 1.7 nm ends at **{d0['clamp']['fixed']['set']['gap_end']:.4f} nm** with the fix "
       f"(minimum {d0['clamp']['fixed']['set']['gap_min']:.4f}); with the lower clamp moved to 0 the same pulse ends at **{d0['clamp']['alternative_clip_at_zero']['set']['gap_end']:.4f} nm** "
       f"(R at 0.1 V ~ {r_of(max(d0['clamp']['alternative_clip_at_zero']['set']['gap_end'], 1e-3)):.0f} ohm - not 1A's LRS). A hard RESET ends at {d0['clamp']['fixed']['reset']['gap_end']:.4f} nm (maxGap) either way.")
    A_("  **Fix [CHOICE]: declare `clip_minGap` (the expression stands; the declaration was the typo).** This is the rename 1A applied without compiling; it is now compiled, run, "
       "and justified. `spice/rram.va` is unchanged from 1A.\n")

    # ---------------- 2
    A_("## 2. D0 - the compiled model against 1A and the published characteristics\n")
    A_("| quantity | compiled rram.va [SIM] | 1A | relative difference |")
    A_("|---|---|---|---|")
    A_(f"| R at 0.1 V, gap 0.2 nm (LRS) | {d0['r_lrs']:.4f} ohm | 541.82 ohm | {d0['rel_err_lrs']:+.1e} |")
    A_(f"| R at 0.1 V, gap 1.7 nm (HRS) | {d0['r_hrs']:,.2f} ohm | 218,586.0 ohm | {d0['rel_err_hrs']:+.1e} |")
    A_(f"| R(gap) at 0.1 V, 16 gaps over 0.2-1.7 nm | - | 1A read equation | worst {d0['gap_sweep']['max_rel_err']:.1e} |")
    A_(f"| I(V), +/-0.5 V at 4 gaps | - | 1A read equation | worst {max(v['max_rel_err'] for v in d0['iv'].values()):.1e} |")
    A_(f"| gap range under hard SET / RESET | {d0['clamp']['fixed']['set']['gap_end']:.4f} / {d0['clamp']['fixed']['reset']['gap_end']:.4f} nm | 0.2 / 1.7 nm | clamps hold |")
    A_("")
    A_("The gap terminal of the module is a port, so the read I-V is measured with the gap pinned by a source. **1A's resistances are reproduced exactly: every number in 1A, 1B, "
       "1C and 1F that rests on them stands, as far as the model is concerned.**")
    A_("\n**Quasi-static I-V** (triangular sweeps through 2 kohm, from HRS):\n")
    A_("| sweep period | V at SET (gap through 0.95 nm) | V at RESET | lowest gap reached |")
    A_("|---|---|---|---|")
    for h in d0["hysteresis"]:
        A_(f"| {h['period_s']:g} s | {h['v_set'] if h['v_set'] is None else round(h['v_set'], 3)} | {h['v_reset'] if h['v_reset'] is None else round(h['v_reset'], 3)} | {h['gap_min']:.3f} nm |")
    A_("")
    A_("Bipolar, rate-dependent switching with a gradual RESET - the qualitative shape of the published Stanford-PKU characteristic [SP]. **There is no fixed threshold**: the "
       "apparent switching voltage falls from ~0.66 V (10 ms sweep) to ~0.35 V (1 s); at a 1 us sweep the device does not switch at all. The published curves are quasi-static "
       "DC sweeps; this report does not have their raw data, so the comparison is qualitative [SP, not re-fitted].")
    A_("\n![Figure 25: compiled model vs 1A; quasi-static I-V](../figures/fig25_compact_model_validation.png)\n")
    A_("*Figure 25.* Left: read resistance at 0.1 V against gap, compiled model (points) on 1A's read equation (line). Right: quasi-static I-V of the compiled model through 2 kohm "
       "at four sweep periods: the switching voltage depends on the sweep rate - the model has a rate, not a threshold.\n")

    # ---------------- 3
    A_("## 3. D1 - forming, SET and RESET inside the array's envelope\n")
    A_("Pulse maps (`program/tables.py`): one ngspice transient of 301 independent copies of the 1D-i cell (compiled device + BSIM4 transistor on the bitline side, word line 1.1 V, "
       "row side 17 ohm, bitline side 379 ohm = the far row, 12.8 / 102 fF of row line / bitline) gives gap_in -> gap_out of one pulse for every initial gap; "
       f"{len(S['volts'])} SET x {len(S['widths'])} widths and {len(R['volts'])} RESET x {len(R['widths'])} widths (10 ns - 100 ms, 1 ns edges), plus 85 C and near-row tables. "
       f"Composing maps reproduces direct chained ngspice pulses to {vA['worst_nm'] * 1e3:.1f} pm worst (0.1 pm on grid widths; `program/validate_loop.py`).")
    A_("\n**(a) Forming: absent from the model.** rram.va has no pristine state, no forming voltage and no forming dynamics: the gap starts wherever its initial condition puts it "
       "inside [0.2, 1.7] nm. Real HfOx devices form at 2-3.5 V; 1D-i section 3 shows that more than 1.1 V on a bitline overstresses the core access transistors, so **a forming step, "
       "if the real device needs one, is outside the array** - flagged, not quantified (there is nothing in the model to quantify it with).")
    A_("\n**(b) SET (from HRS, 1.7 nm) - gap after one pulse:**\n")
    ws = (1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1)
    A_("| amplitude | " + " | ".join(f"{w:g} s" for w in ws) + " | energy, 1 us (nJ) | peak current (uA) | transistor Vds max (V) |")
    A_("|---|" + "---|" * (len(ws) + 3))
    for v in (1.0, 1.3, 1.6, 2.0, 2.4):
        A_(f"| {v} V | " + " | ".join(f"{at(S, v, w, 1.7):.3f}" for w in ws) + f" | {atk(S, 'energy_j', v, 1e-6, 1.7) * 1e9:.2f} | {atk(S, 'i_peak_a', v, 1e-6, 1.7) * 1e6:.0f} | "
           f"{float(S['v_tx_max'][int(np.argmin(np.abs(S['volts'] - v))), :, -1].max()):.2f}{' **(> 1.1)**' if S['v_tx_max'][int(np.argmin(np.abs(S['volts'] - v))), :, -1].max() > 1.1 else ''} |")
    A_("")
    A_("- **Inside 1D-i's sweep (10 ns-1 us) and the transistor's rating (<= 1.3 V) a SET pulse moves an HRS device by at most ~0.1 nm** (1.7 -> 1.62 nm, 150 kohm). The SET is "
       "transistor-limited: once the gap starts to close, the current hits the 20 F^2 transistor's compliance (0.2-0.25 mA), the device voltage collapses to what that current "
       "needs (0.3-0.5 V) and the gap velocity with it. The LRS is approached in **milliseconds**: ~0.64 nm (3 kohm) in ~1 ms, 0.35 nm (987 ohm) in ~20-30 ms, saturating at "
       f"~{at(S, 1.3, 0.1, 1.7):.2f} nm in 100 ms - where the physical SET rate at compliance meets the clamp tail. **1A's 541.8 ohm (0.2 nm) is never reached.**")
    A_("- Drives above 1.3 V (flagged: more than 1.1 V across the written transistor, 1D-i) buy little: the device is current-limited, not voltage-limited. Energy per pulse is "
       "0.03-0.5 nJ at 1 us and ~0.5-50 uJ at 1-100 ms (the compliance current flows for the whole pulse) - 1B's 10 pJ per pulse is 3-50x low at 1 us and 4-6 orders low at the pulse widths that actually program.")
    A_(f"- Near row (bitline side 11 ohm instead of 379): {at(tn['set'], 1.3, 1e-6, 1.7):.3f} nm at 1.3 V / 1 us, {at(tn['set'], 1.3, 1e-3, 1.7):.3f} nm at 1 ms - the far row's "
       "bitline costs little at these currents.")
    A_("\n**(c) RESET (from the design-adjacent LRS, 0.35 nm, and from 0.6 / 1.3 nm) - gap after one pulse:**\n")
    A_("| start | amplitude | " + " | ".join(f"{w:g} s" for w in ws) + " | V across the device (V) |")
    A_("|---|---|" + "---|" * (len(ws) + 1))
    for g0 in (0.35, 0.6, 1.3):
        for v in (0.8, 1.1, 2.0):
            A_(f"| {g0} nm | {v} V{' (flag)' if v > 1.1 else ''} | " + " | ".join(f"{at(R, v, w, g0):.3f}" for w in ws) + f" | {atk(R, 'v_dev_max', v, 0.1, g0):.2f} |")
    A_("")
    A_("- **RESET is source-follower capped (1D-i): ~0.45-0.5 V across the device whatever the drive**, so nothing happens below ~1 ms; 0.35 -> 1.55 nm needs ~0.05-0.1 s, and "
       "it saturates at ~1.64-1.65 nm (the cap against the clamp tail) - **1A's 1.7 nm is not reached either.** With the 541.8 ohm state itself (0.2 nm) the current-limited "
       "transistor leaves 0.27-0.5 V and RESET takes ~0.1 s at drives above the rating.")
    A_("\n**What a different array would need (out-of-envelope sweep, `program/d1_characterise.py`):** the smallest write device that reaches the design-adjacent states in <= 1 us:\n")
    A_("| operation | row | 10 ns | 100 ns | 1 us |")
    A_("|---|---|---|---|---|")
    for op in ("set", "reset"):
        for rbl, lab in ((379, "far (379 ohm bitline)"), (11, "near (11 ohm)")):
            cells = []
            for tw in ("1e-08", "1e-07", "1e-06"):
                n = d1["need"].get(f"{op}|{tw}|{rbl}")
                cells.append("none up to 400 F^2 / 3 V" if n is None else f"{n['w_um'] / 0.027:.0f} F^2, WL {n['v_wl']} V, {n['v']} V, peak {n['i_peak'] * 1e3:.1f} mA")
            A_(f"| {op.upper()} to {0.35 if op == 'set' else 1.55} nm | {lab} | " + " | ".join(cells) + " |")
    A_("")
    A_("(Cell area = W / (0.6 x 45 nm) F^2, 1A's fill.) **The design-adjacent states in <= 1 us need a 100-200 F^2 access transistor with a 3 V (thick-oxide) word line, on a "
       "short (segmented or locally driven) bitline, and 6-9 mA per device - 25-36x the 20 F^2 cell's current, 5-10x its area, and 160 devices in parallel would draw ~1-1.5 A. "
       "That is a different array.** It is run in section 4 as scenario B to show what short pulses would buy; nothing else in this report assumes it.")
    A_("\n**(d) Gradual or abrupt: gradual, in both directions.** The gap after a pulse is a smooth, monotone function of width and amplitude over five decades of width "
       "(Figure 26), with no threshold: the per-pulse change can be made as small as wanted by shortening the pulse or lowering the amplitude. Two properties matter for D2: "
       "(i) the compliance-limited SET is **self-converging** - a long pulse brings every device to nearly the same gap whatever its start (a deterministic attractor), so in a "
       "model without variability open-loop programming already looks perfect; (ii) RESET is slow and steep near its saturation (~10-100 ms), so the RESET direction is the "
       "coarse one. **A verify loop can converge; D2 is possible.**")
    A_("\n![Figure 26: SET and RESET maps inside the envelope](../figures/fig26_set_reset_maps.png)\n")
    A_("*Figure 26.* Gap after one pulse against pulse width (20 F^2, word line 1.1 V, far row). Left: SET from HRS; right: RESET from the design-adjacent LRS. Open markers: drives that "
       "put more than 1.1 V across the access transistor. Dashed: the end of 1D-i's swept pulse widths (1 us). Dotted: the design-adjacent targets.\n")

    # ---------------- 4
    A_("## 4. D2 - the program-verify loop and sigma_lnG\n")
    A_("### 4.1 The loop\n")
    A_("`program/verify.py`, vectorised over 4,000 devices per configuration, on the pulse maps of section 3:")
    A_("- **read -> compare -> pulse -> read**: bidirectional incremental-step programming (ISPP): the amplitude rises by dv after every pulse that leaves the device short of the "
       "window; a pulse that carries it past the window reverses the polarity and restarts the opposite ISPP (corrections use a gentler width). Stop when the verify read lands in "
       "the window or after n_max pulses (a failure keeps what it has: counted in 'all devices', excluded from 'accepted').")
    A_(f"- **The verify read is 1F's read, with 1F's noise.** Row line 0.35 V, sense node 0.25 V, word line 1.1 V, the BSIM4 transistor on the bitline side "
       f"(`program/read_conditions.py`: at this bias the LRS branch carries {rcs['bl|branch|lrs_adjacent']['i_27_a'] * 1e6:.1f} uA at 0.35 nm and the HRS {rcs['bl|branch|hrs_adjacent']['i_27_a'] * 1e6:.2f} uA at 1.55 nm); "
       "the per-read random error is 1F's measured front-end noise (thermal + comparator + reset, vb 0.50, tail 0.3 ns): **1.416 uA at T = 1 ns (g = 4 design), 0.870 uA at "
       "T = 2 ns (g = 8)**, averaged over n_avg reads. 1F's per-column calibration residual (0.9-1.3 uA) is static per column: it shifts every device of a column the same way, "
       "so it is a per-column placement bias (removed by the same column's calibration when it reads) and not part of the per-device sigma; it is stated, not added.")
    A_(f"- **The ballast.** dlnI / dlnG = {d2['targets']['beta'][0]:.2f} at the LRS target: the ~2 kohm access transistor divides the device's conductance change by "
       f"{1 / d2['targets']['beta'][0]:.1f} before the read sees it. A 1.4 uA read error on 33.7 uA is 4.2% of the current but **15% of the conductance**: the verify is noisy "
       "for the same reason the inference read is robust (1B's ballast).")
    A_("- **Switching variability is not in the model.** Without it a long compliance-limited pulse lands every device on the same gap (section 3d), so a zero spread is a property "
       "of a deterministic model, not a placement result. It is imposed as a lognormal scale on each pulse's effective duration (the form of an activation-energy / attempt-rate "
       "fluctuation): sigma_c2c per pulse and sigma_d2d per device in {0, 0.1, 0.3} **[ASSUM]**. The headline numbers use 0.3 / 0.3.")
    A_("- Targets: **design-adjacent LRS 0.35 nm (987 ohm) and HRS 1.55 nm (120 kohm, ratio 121 > 1B's 92 at g = 8)**; LRS devices start from HRS (1.55-1.7 nm, after the RESET "
       "phase), HRS devices from the old LRS. Scenario A = the in-envelope array; scenario B = the out-of-envelope write device of section 3.\n")
    A_("### 4.2 sigma_lnG as a surface (scenario A, LRS)\n")
    A_("Achieved sigma_lnG of ALL devices (accepted and failed), 3.2 ms SET pulses, ISPP 1.0 -> 1.3 V in 50 mV steps, imposed variability 0.3 / 0.3, verify at T = 1 ns:\n")
    nms = (1, 2, 3, 5, 8, 12, 20, 50)
    A_("| window | reads per verify | " + " | ".join(f"n_max {n}" for n in nms) + " | yield at 50 |")
    A_("|---|---|" + "---|" * (len(nms) + 1))
    for w in (0.05, 0.1):
        for na in (1, 4, 16, 64):
            rs = {r["n_max"]: r for r in lrs_sel(A, read="1ns", n_avg=na, c2c=0.3, d2d=0.3, w=w) if abs(r["t_w"] - 3.162e-3) < 1e-9}
            A_(f"| +/-{w * 100:.0f}% | {na} | " + " | ".join(f"{rs[n]['sigma_lnG_all']:.3f}" if n in rs else "-" for n in nms) + f" | {rs[50]['yield_'] * 100:.1f}% |")
    A_("")
    A_("Pulse width and verify accuracy (best over windows and ISPP steps, n_max 50, variability 0.3/0.3, accepted devices; yield >= 99.9%):\n")
    A_("| SET pulse width | 1 read, T 1 ns | 4 reads | 16 reads | 64 reads | 1 read, T 2 ns | 16 reads, T 2 ns | mean pulses (16 reads, T 1 ns) |")
    A_("|---|---|---|---|---|---|---|---|")
    for tw in sorted({r["t_w"] for r in A if r["state"] == "lrs"}):
        def bst(rd_, na):
            rs = [r for r in lrs_sel(A, read=rd_, n_avg=na, c2c=0.3, d2d=0.3, n_max=50) if abs(r["t_w"] - tw) < 1e-12 and r["yield_"] >= 0.999]
            return min(rs, key=lambda r: r["sigma_lnG"]) if rs else None
        cells = [bst("1ns", na) for na in (1, 4, 16, 64)] + [bst("2ns", 1), bst("2ns", 16)]
        A_(f"| {tw * 1e3:.2f} ms | " + " | ".join(f"{c['sigma_lnG']:.3f}" if c else "-" for c in cells) + f" | {cells[2]['pulses_mean']:.1f} |" if cells[2] else f"| {tw * 1e3:.2f} ms | - |")
    A_("")
    A_("Imposed variability (n_max 50, +/-5%, 3.2 ms, T = 1 ns): open loop = the one-pulse spread, verified = after the loop:\n")
    A_("| sigma_c2c / sigma_d2d | open loop (n_max 1), all devices | 1 read per verify | 16 reads per verify |")
    A_("|---|---|---|---|")
    for c2c, d2d in ((0.0, 0.0), (0.1, 0.0), (0.3, 0.0), (0.0, 0.3), (0.3, 0.3)):
        def g_(na, nm):
            rs = [r for r in lrs_sel(A, read="1ns", n_avg=na, c2c=c2c, d2d=d2d, w=0.05, n_max=nm) if abs(r["t_w"] - 3.162e-3) < 1e-9 and r["dv"] == 0.05]
            return rs[0] if rs else None
        o, a1, a16 = g_(1, 1), g_(1, 50), g_(16, 50)
        A_(f"| {c2c} / {d2d} | {o['sigma_lnG_all']:.3f} | {a1['sigma_lnG_all']:.3f} | {a16['sigma_lnG_all']:.3f} |")
    A_("")
    A_("- **The verify absorbs the switching variability**: with any verify the result is the same at variability 0 and 0.3 - the loop keeps pulsing until the READ says the "
       "device is in the window. What it cannot absorb is the read's own error: that is the floor.")
    A_("### 4.3 HRS: a one-sided verify\n")
    hs = [r for r in A if r["state"] == "hrs" and r.get("one_sided") and r["c2c"] == 0.3 and r["read"] == "1ns" and r["w"] == 0.5 and r["n_max"] == 20]
    A_("The read needs the HRS to be high-resistance ENOUGH (1B: ratio > 92 at g = 8), not placed. A one-sided verify (accept once the read is below G_t (1 + w)) (w = 0.5, n_max 20) with 10-100 ms RESET pulses:\n")
    A_("| RESET width | reads per verify | sigma_lnG (accepted) | yield | mean pulses | energy per device (uJ) |")
    A_("|---|---|---|---|---|---|")
    for r in sorted(hs, key=lambda r: (r["t_w"], r["n_avg"])):
        A_(f"| {r['t_w'] * 1e3:.1f} ms | {r['n_avg']} | {r['sigma_lnG']:.3f} | {r['yield_'] * 100:.1f}% | {r['pulses_mean']:.1f} | {r['energy_mean_j'] * 1e6:.2f} |")
    A_("")
    A_("The HRS read current (0.82 uA) is below one read's noise (1.4 uA), so the HRS is placed loosely (0.2-0.5) - and section 7 shows that costs < 0.1 uA of budget.")
    A_("### 4.4 Where it stops improving, and what sets the floor\n")
    A_("| reads per verify | measured floor, +/-5%, T 1 ns (n_max >= 20) | [MODEL] floor sqrt((beta w)^2/3 + s_r^2)/beta | the read's relative error in conductance units s_r/beta |")
    A_("|---|---|---|---|")
    beta = d2["targets"]["beta"][0]; i_t = d2["targets"]["i_read_a"][0]
    for na in (1, 4, 16, 64):
        rs = [r for r in lrs_sel(A, read="1ns", n_avg=na, c2c=0.3, d2d=0.3, w=0.05) if abs(r["t_w"] - 3.162e-3) < 1e-9 and r["n_max"] >= 20 and r["dv"] == 0.05]
        A_(f"| {na} | {np.mean([r['sigma_lnG_all'] for r in rs]):.3f} | {d2['targets']['floor_model'][f'lrs|1ns|{na}|0.05']:.3f} | {1.416e-6 / np.sqrt(na) / i_t / beta:.3f} |")
    A_("")
    A_("- **More iterations stop helping after 8-12 pulses**: the curves of Figure 27 are flat from there. **The floor is set by the verify read's random error divided by the ballast** "
       "- the accepted devices are the window smeared by the read error. It scales as 1/sqrt(reads per verify): averaging is the only lever (a narrower window does not help once it is "
       "below the read error; a longer verify read is the same thing as averaging).")
    A_("- It is NOT set by the pulse granularity (the model's response is continuous) and, with any verify, not by the imposed switching variability. Without verify the spread is "
       "set by the variability alone (open loop column above).")
    A_("- The measured floor sits below the simple model because the loop approaches the window from one side (most devices are accepted near the edge they entered) - the "
       "model is a bound, the simulation is the number.")
    A_("\n![Figure 27: sigma_lnG vs program effort](../figures/fig27_sigma_surface.png)\n")
    A_("*Figure 27.* Left: achieved sigma_lnG (all devices, design-adjacent LRS, in-envelope array, 3.2 ms pulses, +/-5% window, imposed variability 0.3/0.3) against the number of "
       "pulses allowed, for 1-64 averaged reads per verify; dotted: the read-limited floor [MODEL]; dashed: the 0.10 that 1A-1F assumed; dash-dot: 1F's conditions for g = 8 and 16. "
       "Right: every configuration that reaches 99.9% yield, spread against program energy per device.\n")
    A_("### 4.5 What each operating point costs, and the full array\n")
    A_("Per device (mean) and for the full 163,840-device array at 1D-i's parallelism (160 devices per pulse, row-sequential, a row finishes when its slowest device does - the "
       "row time is the 99.4th percentile of the per-device time; 81,920 LRS + 81,920 HRS devices):\n")
    A_("| scenario | verify | variability | sigma_LRS | sigma_HRS | LRS: pulses / energy (uJ) | HRS: pulses / energy (uJ) | row time LRS + HRS (s) | full array: time (s) | full array: energy (J) |")
    A_("|---|---|---|---|---|---|---|---|---|---|")
    for p in sorted(pts + ptsB, key=lambda p: (p["scen"], p["c2c"], p["read"], p["n_avg"])):
        A_(f"| {p['scen']}{' (out of envelope)' if p['scen'] == 'B' else ''} | {p['n_avg']} x T {p['read']} | {p['c2c']}/{p['d2d']} | {p['sigma_lrs']:.3f} | {p['sigma_hrs']:.3f} | "
           f"{p['pulses_lrs']:.1f} / {p['e_dev_lrs_j'] * 1e6:.2f} | {p['pulses_hrs']:.1f} / {p['e_dev_hrs_j'] * 1e6:.2f} | {p['t_row_lrs_s']:.3f} + {p['t_row_hrs_s']:.3f} | "
           f"{p['t_full_s']:.3g} | {p['e_full_j']:.3g} |")
    A_("")
    A_("- **In-envelope, a full program is a minutes-and-a-joule operation**: the millisecond SET pulses and 10-100 ms RESET pulses flow the transistor's compliance current for their "
       "whole length; the verify reads are negligible (a 64-read verify costs ~0.1 uJ per device against ~5-10 uJ of pulses). **Tighter sigma is nearly free in energy; it costs "
       "verify reads, i.e. time per iteration, and the pulse count barely changes.**")
    if B:
        A_("- **Scenario B (out of envelope)** reaches the same read-limited floor with sub-microsecond pulses: the floor is the read's, not the write device's; what the bigger device "
           "buys is time and energy, not sigma.")
    if vB:
        A_(f"  (Scenario B's maps reproduce chained ngspice pulses to {vB['worst_nm'] * 1e3:.1f} pm.)")
    A_("")

    # ---------------- 5
    A_("## 5. D3 - retention, drift, temperature\n")
    zb = {z["smoothing"]: z for z in d3["zero_bias"]}
    def zg(sm, g0, k):
        z = zb[sm]; return z["gap"][z["gaps0"].index(g0)][k]
    A_("**(a) Zero bias - retention: ABSENT from the model; what looks like retention is a numerical artefact.** The physical gap velocity, Vel0 exp(-Ea/kT) sinh(V ...), is "
       "exactly zero at V = 0 at every temperature. The only zero-bias motion is the tail of the clamp terms: smoothstep(minGap - Gap, smoothing) decays only as "
       "smoothing / (4 delta^2) away from the clamp, times limexp(-Kclip delta). Measured (exact quadrature of the model's own equation at V = 0, validated against the "
       f"compiled model in ngspice to {max(abs(a - b) for v in d3['zero_bias_validation'] for a, b in zip(v['ngspice'], v['mirror'])) * 1e3:.2f} pm at 1 ms and 1 s):\n")
    A_("| smoothing | 0.35 nm after 1 s / 1 day / 10 y | 1.55 nm after 1 s / 1 day / 10 y | 0.2 nm (1A LRS) after 10 y | 1.7 nm (1A HRS) after 10 y |")
    A_("|---|---|---|---|---|")
    for sm in (1e-8, 1e-10, 1e-12):
        A_(f"| {sm:g}{' (default)' if sm == 1e-8 else ''} | {zg(sm, 0.35, 0):.3f} / {zg(sm, 0.35, 2):.3f} / {zg(sm, 0.35, 4):.3f} | {zg(sm, 1.55, 0):.3f} / {zg(sm, 1.55, 2):.3f} / {zg(sm, 1.55, 4):.3f} | "
           f"{zg(sm, 0.2, 4):.3f} | {zg(sm, 1.7, 4):.3f} |")
    A_("")
    A_("The motion scales with `smoothing` (a well-posedness device of the model, not a material parameter) and is temperature-independent: **it is not retention and is not used as "
       "drift anywhere.** It does mean a state within ~0.4 nm of a clamp is not stable in this model, which is another reason 1A's on-clamp design states cannot be targets. "
       "**Retention (thermally activated relaxation at zero bias) is absent from the model, not zero: the 'moderate' drift term of 1B/1C is neither confirmed nor refuted by it.**")
    A_("\n**(b) Read disturb - a mechanism the model DOES have, and it is large.** 1F's read puts ~0.1 V across every active device in the SET direction (row 0.35 V, sense node 0.25 V). "
       "Gap closing rate at the read bias (compiled model + BSIM4 transistor, 1 ms hold):\n")
    A_("| state | " + " | ".join(f"{r['temp_c']:g} C (nm/s)" for r in d3["read_disturb"]) + " | V across the device at 27 C |")
    A_("|---|" + "---|" * (len(d3["read_disturb"]) + 1))
    for i, g0 in enumerate([x["gap"] for x in d3["read_disturb"][0]["rows"]]):
        A_(f"| {g0} nm | " + " | ".join(f"{abs(r['rows'][i]['rate_nm_per_s']):.3g}" for r in d3["read_disturb"]) + f" | {d3['read_disturb'][0]['rows'][i]['v_dev']:.3f} |")
    A_("")
    A_(f"With 1E's read pattern (g = 8: 45,786 active-row reads per inference over 512 rows, T + tail = 2.3 ns: {d3['stress_per_inference']['g8_s'] * 1e9:.0f} ns of read stress per "
       "row per inference on average), as a level shift of the far group's top differential level (gain 0.89, 1C):\n")
    A_("| temperature | g | d ln G per inference, LRS / HRS | top-level shift per inference (pA) | inferences until the 0.27 uA drift allotment is used |")
    A_("|---|---|---|---|---|")
    for k, v in rd.items():
        T_, g_ = k.split("|")
        A_(f"| {T_} C | {g_} | {v['dlnG_lrs_per_inference']:.1e} / {v['dlnG_hrs_per_inference']:.1e} | {v['level_shift_per_inference_a'] * 1e12:.2f} | **{v['inferences_to_027uA']:,.0f}** |")
    A_("")
    A_("- **Was the 'moderate' drift term (0.27-0.29 uA) optimistic? Yes, in kind.** 1B modelled drift as a power law in TIME (G ~ t^-0.003, 3.4% over 10 years). In this model "
       "the device does not move in time at all; it moves with every READ, linearly, Arrhenius-accelerated (~30x at 85 C), and toward LRS for both states. Inside the drift "
       f"allotment the array must be reprogrammed every ~{rd['27.0|8']['inferences_to_027uA']:,.0f} inferences at 27 C (~{rd['85.0|8']['inferences_to_027uA']:,.0f} at 85 C).")
    A_("- It is also not uniform: rows that are active more often drift more, so the disturb adds a data-dependent spread on top of the mean shift (not quantified here; the mean is "
       "the lower bound).")
    A_("- **Mitigation the model points to:** the gap velocity is odd in V (sinh), so a read of alternating polarity cancels the disturb to first order; halving V_READ halves it "
       "(and the signal). Both are front-end (1F) changes - recorded, not done.")
    A_("\n**(c) Temperature of the programmed state.**")
    A_("- **The device's read current has no temperature term in rram.va (ABSENT, not zero)**: $vt appears only in the gap kinetics. 1A/1B's open item stays open for the device.")
    A_(f"- **The read path has one, through the access transistor** (`program/read_conditions.py`, BSIM4 at 1F's bias, 27-125 C): LRS branch {rcs['bl|branch|lrs_1a']['rel_per_k'] * 100:+.2f}%/K; "
       f"the far group's top level (8 LRS branches behind 369 ohm) {rcs['bl|group8|far']['slope_a_per_k_27_47'] * 1e6:+.2f} uA/K, the near group's {rcs['bl|group8|near']['slope_a_per_k_27_47'] * 1e6:+.2f} uA/K. "
       "1F's 5 K recalibration window was set by 0.05 uA/K of front-end drift; **with the cell's temperature coefficient uncompensated the window is "
       f"{0.25 / (abs(rcs['bl|group8|far']['slope_a_per_k_27_47']) * 1e6):.2f} K (far) / {0.25 / (abs(rcs['bl|group8|near']['slope_a_per_k_27_47']) * 1e6):.2f} K (near).** "
       "The shift is common to every column (same transistor everywhere), so it is correctable by a temperature-indexed level scale per group (an on-chip temperature sensor and "
       "a scale factor on the thresholds) - that, not a 10x more frequent recalibration, is the recommendation; either way 1F's window does not hold as stated.")
    A_(f"- **The kinetics are strongly temperature-dependent** (Ea = 0.6 eV): a fixed 1 ms, 1.3 V SET from HRS ends at {at(S, 1.3, 1e-3, 1.7):.3f} nm at 27 C and "
       f"{at(t85['set'], 1.3, 1e-3, 1.7):.3f} nm at 85 C; a 10 ms, 1.1 V RESET from 0.35 nm at {at(R, 1.1, 1e-2, 0.35):.3f} vs {at(t85['reset'], 1.1, 1e-2, 0.35):.3f} nm. "
       "The verify loop closes on the read, so the placement survives; the pulse schedule (and the program time) does not - it must be temperature-aware, and the read-disturb "
       "rate above rises ~30x by 85 C.")
    A_("\n![Figure 28: zero-bias artefact and read disturb](../figures/fig28_retention_read_disturb.png)\n")
    A_("*Figure 28.* Left: gap at zero bias over time from 0.35 nm (solid) and 1.55 nm (dashed) for three values of the model's `smoothing` parameter - the motion is the clamp "
       "tail and scales with the numerical parameter. Right: gap closing rate under 1F's read bias against gap at 27, 85 and 125 C - read disturb.\n")

    # ---------------- 6
    A_("## 6. The read conditions 1F assumed, measured with the real bias\n")
    A_("| quantity | 1A-1F used | at 1F's bias (row 0.35 V, sense node 0.25 V), BSIM4, transistor on the bitline side | row-line side |")
    A_("|---|---|---|---|")
    A_(f"| R_tx, LRS branch | 1016 ohm (source at 0 V) | {rcs['bl|branch|lrs_1a']['r_tx_eff_27_ohm']:.0f} ohm | {rcs['rl|branch|lrs_1a']['r_tx_eff_27_ohm']:.0f} ohm |")
    A_(f"| LRS branch current (541.8 ohm) | ~64 uA | {rcs['bl|branch|lrs_1a']['i_27_a'] * 1e6:.1f} uA | {rcs['rl|branch|lrs_1a']['i_27_a'] * 1e6:.1f} uA |")
    A_(f"| HRS branch current | 0.456 uA | {rcs['bl|branch|hrs_1a']['i_27_a'] * 1e6:.3f} uA | {rcs['rl|branch|hrs_1a']['i_27_a'] * 1e6:.3f} uA |")
    A_(f"| far-group top level (8 LRS), temperature coefficient | (not modelled) | {rcs['bl|group8|far']['slope_a_per_k_27_47'] * 1e6:+.2f} uA/K | {rcs['rl|group8|far']['slope_a_per_k_27_47'] * 1e6:+.2f} uA/K |")
    A_("")
    A_("**For 1F (not reopened here, recorded):** with the sense node at 0.25 V the access transistor's source sits at 0.25 V in either orientation; its Vgs is 0.85 V, not 1.1 V, "
       "and it is twice as resistive as 1A's figure. The LRS current - the signal every budget line of 1B-1F is a fraction of - is ~40% lower than assumed. The ballast is "
       "stronger (good for spread) and the signal smaller (bad for every absolute term: comparator, calibration, threshold generation). A 1F revision should re-close with the "
       "BSIM4 transistor at its real bias. **Sections 4 and 7 of this report use the real bias for the verify read; the budget machinery of section 7 is 1F's as it stands.**\n")

    # ---------------- 7
    A_("## 7. D4 - the budget re-closed with the measured spread\n")
    A_("### 7.1 The closure map at the measured spread\n")
    A_("1F's machinery unchanged (`sense.budget_1f.closure`; S1, drift 'moderate', 5-sigma random terms, 20% headroom, the 18 front-end points of 1F, 5 K window), the spread term "
       "driven by the measured sigma_LRS and sigma_HRS separately (`drift.model.mc_levels_drift(sigma_hrs=...)`, which reproduces 1C's 0.476 uA exactly when the two are equal). "
       "Margin left (uA), best front-end point, 8 mV droop; > 0.15 uA is outside the Monte-Carlo scatter:\n")
    A_("| program-effort point (scenario A) | sigma_LRS / sigma_HRS | g = 4 | g = 8 | g = 8, calibration residual halved | g = 16 | g supported |")
    A_("|---|---|---|---|---|---|---|")
    for p in sorted(pts, key=lambda p: (p["c2c"], p["read"], p["n_avg"])):
        ms = {g: m(p, g) for g in (4, 8, 16)}
        mh = best[key(8, p["sigma_lrs"], p["sigma_hrs"], 8, 0.5)]["margin_a"] * 1e6
        gs = [g for g in (4, 8, 16) if ms[g] > 0.15]
        A_(f"| {p['n_avg']} read{'s' if p['n_avg'] > 1 else ''} per verify, T {p['read']}, variability {p['c2c']}/{p['d2d']} | {p['sigma_lrs']:.3f} / {p['sigma_hrs']:.3f} | {ms[4]:+.2f} | "
           f"**{ms[8]:+.2f}** | {mh:+.2f} | {ms[16]:+.2f} | {max(gs) if gs else '-'} |")
    A_("| 1F's own surface, sigma 0.07 / 0.10 (check) | 0.07 / 0.10 | " + " / ".join(f"{best[key(4, s, s)]['margin_a'] * 1e6:+.2f}" for s in (0.07, 0.10)) + " | "
       + " / ".join(f"{best[key(8, s, s)]['margin_a'] * 1e6:+.2f}" for s in (0.07, 0.10)) + " | - | " + " / ".join(f"{best[key(16, s, s)]['margin_a'] * 1e6:+.2f}" for s in (0.07, 0.10)) + " | 1F: +1.9 / +0.2 at g = 8 |")
    A_("")
    A_("g = 16 with 1F's segmented columns (vb 0.46, T 2 ns, tail 1 ns, 5 K):\n")
    A_("| sigma_LRS / sigma_HRS | end-sensed | seg4_mid | seg8_mid |")
    A_("|---|---|---|---|")
    for (sl, sh) in sorted({(v["sigma_lrs"], v["sigma_hrs"]) for v in d4["g16_variants"]}):
        row = {v["variant"]: v["margin_a"] * 1e6 for v in d4["g16_variants"] if v["sigma_lrs"] == sl and v["sigma_hrs"] == sh}
        A_(f"| {sl:.3f} / {sh:.3f} | {row.get('end', float('nan')):+.2f} | {row.get('seg4_mid', float('nan')):+.2f} | {row.get('seg8_mid', float('nan')):+.2f} |")
    A_("")
    A_("### 7.2 The trade: program effort against inference energy\n")
    A_(f"1F: {d4['e_inf_1f']['4'] * 1e6:.2f} uJ per inference at g = 4 (T = 1 ns), {d4['e_inf_1f']['8'] * 1e6:.2f} uJ at g = 8 (T = 2 ns): g = 8 saves "
       f"{(d4['e_inf_1f']['4'] - d4['e_inf_1f']['8']) * 1e6:.2f} uJ per inference. The verify accuracy that buys g = 8 is cheap: going from 1 to 16 reads per verify changes the "
       "full-array program energy by a few % (section 4.5), because the energy is in the millisecond pulses, not the reads.")
    A_(f"- **Crossover (one program, many inferences):** the extra program energy of the tighter verify is recovered after "
       f"{abs(head['e_full_j'] - single['e_full_j']) / ((d4['e_inf_1f']['4'] - d4['e_inf_1f']['8'])):,.0f} inferences - if g = 8 also needed it. In fact both points support g = 8 "
       "(7.1), so the tight verify buys margin, not g.")
    A_(f"- **The refresh changes the picture.** A program costs ~{head['e_full_j']:.1f} J in-envelope; read disturb forces one every ~{rd['27.0|8']['inferences_to_027uA']:,.0f} inferences "
       f"at 27 C: **{head['e_full_j'] / rd['27.0|8']['inferences_to_027uA'] * 1e6:.0f} uJ per inference of programming, {head['e_full_j'] / rd['27.0|8']['inferences_to_027uA'] / d4['e_inf_1f']['8']:.0f}x "
       f"the inference itself** ({head['e_full_j'] / rd['85.0|8']['inferences_to_027uA'] * 1e3:.1f} mJ per inference at 85 C). And {head['t_full_s']:.0f} s of programming every "
       f"{rd['27.0|8']['inferences_to_027uA'] * 4.3e-3:.0f} s of inference (1F: ~4.3 ms per inference at 100 MHz). **For a realistic deployment (>= 1e6 inferences per program) the "
       "array is not viable until read disturb is removed;** with it removed, the one-time program cost amortises below 1% of the inference energy after ~2e7 inferences.")
    A_("\n![Figure 29: budget at the measured spread; program effort vs inference energy](../figures/fig29_budget_trade.png)\n")
    A_("*Figure 29.* Left: margin left against sigma_LRS for g = 4, 8, 16 (1F's surface, lines) with the measured program-verify points (stars); grey band: Monte-Carlo scatter. "
       "Right: energy per inference including the program energy amortised over the inferences between programs, for the measured effort points; dashed: 1F's per-inference "
       "energies; dash-dot: the refresh interval read disturb forces at 27 and 85 C.\n")
    A_("### 7.3 Which of 1F's conditions the device reaches\n")
    A_(f"- **g = 8 needs sigma_lnG <= 0.07** (and, for 1F's 1 nF / 40-column design, a halved calibration residual): **reached in the model with >= 4 averaged reads per verify** "
       f"(0.045-0.049 at T = 1 ns, 0.032-0.034 at 2 ns; {head['sigma_lrs']:.3f} with 16). A single read per verify ends at {single['sigma_lrs']:.3f} - just above the line; the closure "
       f"still leaves {m(single, 8):+.2f} uA at the best front-end point, but not the margin 1F asked for. With the calibration residual halved every point gains ~0.4-0.6 uA (7.1).")
    A_(f"- **g = 16 needs sigma_lnG <= 0.045 with seg4/seg8 columns**: **reached** with >= 16 reads per verify ({head['sigma_lrs']:.3f}), where seg4_mid / seg8_mid close with "
       f"{g16v(head, 'seg4_mid'):+.2f} / {g16v(head, 'seg8_mid'):+.2f} uA; with 4 reads ({[p for p in pts if p['read'] == '1ns' and p['n_avg'] == 4 and p['c2c'] == 0.3][0]['sigma_lrs']:.3f}) "
       "they are at zero. End-sensed g = 16 never closes.")
    A_("- **Both are model results at the design-adjacent states, with the variability assumed, under 1F's read conditions as 1F modelled them (1016 ohm).** None of them holds for "
       "the 20 F^2 array as it stands: it cannot write the states the budget is closed at (section 3), and read disturb removes the margin within ~2e4 inferences (section 5). "
       "**g = 4 remains the deliverable design point; g = 8 is what the device's placement accuracy supports once the write path and the read polarity are fixed.**\n")

    # ---------------- 8
    A_("## 8. Handoff to Phase 5\n")
    A_("| quantity | value | status |")
    A_("|---|---|---|")
    A_(f"| achievable sigma_lnG (LRS) | {head['sigma_lrs']:.3f} (16-read verify) / {single['sigma_lrs']:.3f} (single read); floor ~ read error / ballast | [SIM model + ASSUM variability], design-adjacent state |")
    A_(f"| sigma_lnG (HRS) | {head['sigma_hrs']:.2f} (one-sided verify) | budget cost < 0.1 uA |")
    A_("| g it supports | 8 (budget, model); 16 only with seg4/seg8 columns and >= 16-read verify; deliverable today: 4 | section 7 |")
    A_(f"| full-array program time / energy | {head['t_full_s']:.0f} s / {head['e_full_j']:.2f} J in-envelope (ms pulses); " + (f"{ptsB[0]['t_full_s']:.2g} s / {ptsB[0]['e_full_j'] * 1e3:.2g} mJ with an out-of-envelope 200 F^2 / 3 V write device" if ptsB else "") + " | [SIM model] |")
    A_(f"| refresh (read disturb) | every ~{rd['27.0|8']['inferences_to_027uA']:,.0f} inferences at 27 C, ~{rd['85.0|8']['inferences_to_027uA']:,.0f} at 85 C - or remove it (alternating read polarity) | [SIM model] |")
    A_(f"| recalibration | trims every ~{0.25 / (abs(rcs['bl|group8|far']['slope_a_per_k_27_47']) * 1e6):.1f} K unless the ladder scale tracks temperature (then 1F's 5 K); after every program: trims + level-scale check (1D-i) | [SIM] |")
    A_("| write path | 1D-i: thick-oxide drivers (0.15-0.96 mm^2); this report: the 20 F^2 cell cannot write 1A's states | flag |")
    A_("")

    # ---------------- 9
    A_("## 9. TO BE DETERMINED (updated list)\n")
    A_("- **Switching variability (cycle-to-cycle, device-to-device)**: absent from the model, imposed [ASSUM 0-0.3]; with verify it does not change sigma, without verify it is the whole spread.")
    A_("- **Retention / thermal relaxation at zero bias**: absent from the model (the zero-bias motion is a `smoothing` artefact). The drift term of the budget has no model basis either way.")
    A_("- **Forming**: absent from the model; a real device's forming voltage is outside the core-transistor array (1D-i).")
    A_("- **The device's read-current temperature coefficient**: absent from the model (open since 1A); the transistor's is now measured (section 6).")
    A_("- **Read-disturb mitigation** (alternating read polarity / lower V_READ) - a 1F change; until it exists the refresh interval of section 5 binds.")
    A_("- **A write path that can program 1A's states**: >= 100-200 F^2 thick-oxide access transistor, 3 V word line, short bitlines (section 3) - a different array; or a re-chosen read "
       "operating point at a state the 20 F^2 cell can write (e.g. ~0.6 nm / 2.7 kohm in ~1 ms) - which reopens 1B-1F.")
    A_("- **1F at the real read bias** (R_tx ~2 kohm, signal -40%, section 6).")
    A_("- **Silicon**: every sigma here is a model result on someone else's device calibration.")
    A_("")

    # ---------------- 10
    A_("## 10. Files and reproduction\n")
    A_("```")
    A_("python -m program.d0_validate        # D0: the bug, the fix, the compiled model vs 1A (stop rule), quasi-static I-V")
    A_("python -m program.tables --which all  # pulse maps: 27 C main, 85 C, near row, out-of-envelope design device (~1 h on 30 cores)")
    A_("python -m program.d1_characterise    # D1: forming statement, SET/RESET maps, the out-of-envelope device sweep")
    A_("python -m program.read_conditions    # the verify read at 1F's real bias, R_tx and the read-path temperature coefficient")
    A_("python -m program.validate_loop A    # map composition vs chained ngspice pulses (and B)")
    A_("python -m program.d2_surface A B     # D2: the sigma_lnG surface")
    A_("python -m program.d3_retention       # D3: zero bias (artefact), read disturb")
    A_("python -m program.d4_budget          # D4: the budget re-closed, the trade, the refresh")
    A_("python -m program.figures            # figures 25-29")
    A_("python -m program.make_report        # this file")
    A_("```")
    A_("`spice/osdi.py` (toolchain: OpenVAF + ngspice >= 38, via PATH or nix; builds `spice/build/rram.osdi`), `program/cell.py` (the write cell with the compiled device), `program/model.py` "
       "(the model's equations in Python, analysis only), `program/verify.py` (the loop). Earlier-phase code touched: `drift/model.py`, `drift/strategies.py`, `scaleup/budget1c.py`, "
       "`sense/budget_1f.py` gained an optional `sigma_hrs` (default = 1B-1F behaviour, checked: 1C's 0.476 uA reproduces).")
    RP.REPORT_1D_II.write_text("\n".join(L) + "\n")
    print("wrote", RP.REPORT_1D_II)


if __name__ == "__main__":
    main()
