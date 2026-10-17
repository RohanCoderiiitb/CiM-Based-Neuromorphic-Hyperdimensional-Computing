"""1D-i D4 + D5: full-array program time, energy and peak current at the MEASURED parallelism (D1), the write sequence as an RTL requirement, and what reprogramming
costs the rest of the design in recalibration.

D4 inputs: parallelism 160 devices per pulse (one row; the shared word line and bitlines forbid two rows at once, D1/D3), two phases per row (RESET then SET), 512 rows;
pulses per device and energy per pulse are 1B's [ASSUM] (3 pulses, 10 pJ) until 1D-ii; the array-level energy of a pulse at the measured row current (behavioural device,
post-switch current for the rest of the pulse) is computed alongside as a check of the 10 pJ assumption.
D5: per stored item, what it depends on, whether it survives a reprogram, and the cost of regenerating it (reads at the 1F read cycle).
Usage: python -m write.d4_d5"""
from __future__ import annotations

import json

import numpy as np

import paths as RP

ROWS, CELLS, DEVICES = 512, 160, 163_840
PAR = 160                         # [SIM, D1/D3] devices per pulse
PHASES = 2                        # [CHOICE] RESET phase then SET phase per row
PULSES = 3.0                      # [ASSUM, 1B] mean pulses per device
E_PULSE_J = 10e-12                # [ASSUM, 1B]
WIDTHS = (10e-9, 30e-9, 100e-9, 300e-9, 1e-6)
T_EDGE = 1e-9                     # [CHOICE] driver edge
T_MODE_S = 5e-9                   # [ASSUM] write <-> verify mode switch (isolation switches, bitline drivers, row supply 1-2 V -> 0.35 V); 1F front-end power-up is 1.8-3.2 ns
T_READ_S = 10e-9                  # [1F] one read cycle (power-up + T + tail + comparisons fit in the 10 ns cycle)
E_READ_J = 228e-12                # [1F] energy per non-zero read of the whole array (g = 8, T = 2 ns); a verify read of one row costs the same front-end bias
I_READ_PEAK_A = 69e-3             # [1C/1F] the read PDN's design current


def program_cost(width: float, pulses: float = PULSES, e_pulse: float = E_PULSE_J, i_row_a: float = 34e-3, v_write: float = 1.2, verify: bool = True) -> dict:
    n_pulse_slots = ROWS * PHASES * pulses           # every slot writes up to 160 devices at once
    t_pulse = width + 2 * T_EDGE
    t = n_pulse_slots * (t_pulse + ((2 * T_MODE_S + T_READ_S) if verify else 0.0))
    e_assumed = DEVICES * pulses * e_pulse
    e_array = n_pulse_slots * v_write * i_row_a * width / 2       # [MODEL] half the slots' devices conduct the post-switch current for ~half the pulse
    e_verify = n_pulse_slots * E_READ_J if verify else 0.0
    return dict(width_s=width, time_s=t, energy_assumed_j=e_assumed, energy_array_estimate_j=e_array, energy_verify_j=e_verify, pulse_slots=n_pulse_slots)


def main() -> None:
    d1 = json.loads((RP.WRITE / "d1_transient.json").read_text())
    i_row = max(r["i_peak_a"] for r in d1 if r["case"]["unselected"] == "inhibit")
    rows = [program_cost(w, i_row_a=i_row) for w in WIDTHS]
    rows_noverify = [program_cost(w, i_row_a=i_row, verify=False) for w in WIDTHS]
    seq = [
        "for each row r = 0..511 (any order; rows are independent):",
        "  phase R (RESET): selected row line 0 V; word line r at V_WL; bitlines of the devices that must be HRS driven to V_RESET; all other bitlines at 0 V (= row level);",
        "                   unselected row lines 0 / V/2, unselected word lines 0 V; apply pulse; switch to verify; read row r (160 columns, 1F read path);",
        "                   retire the devices that verified; repeat with the 1D-ii amplitude/width schedule until all retired or N_max",
        "  phase S (SET):   selected row line V_SET; bitlines of the devices that must be LRS at 0 V; non-target bitlines at V_SET/2; unselected row lines 0 V,",
        "                   unselected word lines 0 V; pulse; verify; retire; repeat",
        "state the controller holds: the 160-bit weight row (gives both target masks: + device of a 1-cell / - device of a 0-cell), a 320-bit retired mask, the phase,",
        "  the iteration count (<= N_max, 1D-ii), the current pulse amplitude/width code (per row, or per device if the 1D-ii schedule is per device: 320 x a few bits),",
        "  the bias-level selects of the five line classes, and the mode (write / verify) with its switch-over timing",
        "the a = 0 skip and group sequencing of the read path are not involved; programming is row-sequential",
    ]
    d5 = [
        dict(item="per-group ladder thresholds (1C, 16,140 bits half table)", depends_on="geometry + the POPULATION MEAN of the programmed LRS/HRS conductances (not individual cells)",
             survives_reprogram="yes if the verify targets and their mean placement are unchanged; no if the targets or the program-verify bias move",
             regenerate="measure the level of every (group, a, m) on reference patterns: 64 groups x 44 levels x 16 reads = 45,056 full-array reads", reads=45_056),
        dict(item="rank-3 row-gain correction (1C, 19,584 bits)", depends_on="geometry (row line, rails) and the active-row count a; weights only through the data-dependent terms already in the budget",
             survives_reprogram="yes", regenerate="not needed; re-fit only if the rails/drivers change", reads=0),
        dict(item="per-column front-end trims (1F, 2 x 2 x 10 bits per column = 6.4 kbit)", depends_on="the sense front-end's own mismatch and temperature; NOT the cells",
             survives_reprogram="yes (front-end property) - but it is FITTED through known cells, so it can only be re-fitted once the array holds known data",
             regenerate="18 known configurations (2 groups x m = 0..8) x 9 reads = 162 full-array reads per fit", reads=162),
        dict(item="1F thermal recalibration (every ~5 K)", depends_on="front-end gain/offset drift 0.05 uA/K (1F) [+ the cell read-current TC if any: 1D-ii D3]",
             survives_reprogram="n/a", regenerate="the same 162-read trim fit", reads=162),
    ]
    out = dict(parallelism=PAR, phases=PHASES, pulses_per_device=PULSES, e_pulse_assumed_j=E_PULSE_J, i_row_peak_a=i_row, i_read_pdn_a=I_READ_PEAK_A,
               program=rows, program_no_verify=rows_noverify, sequence=seq, recal=d5,
               recal_time_s=dict(full=(45_056 + 162) * T_READ_S, trims_only=162 * T_READ_S), recal_energy_j=dict(full=(45_056 + 162) * E_READ_J, trims_only=162 * E_READ_J),
               b1_placeholder=dict(energy_j=DEVICES * 3 * 10e-12, time_s=DEVICES * 3 * 100e-9 / 320 * 2 / 2))
    (RP.WRITE / "d4_d5.json").write_text(json.dumps(out, indent=1))
    for r in rows:
        print(f"width {r['width_s'] * 1e9:7.0f} ns: program {r['time_s'] * 1e3:8.3f} ms, energy assumed {r['energy_assumed_j'] * 1e6:.2f} uJ, array estimate {r['energy_array_estimate_j'] * 1e6:.2f} uJ, verify {r['energy_verify_j'] * 1e6:.2f} uJ")
    print("peak write current", i_row, "A")


if __name__ == "__main__":
    main()
