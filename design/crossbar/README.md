# The ReRAM crossbar - design sheet

The analog half of the design is a set of decisions, each made and measured in one of the Phase 1 sub-phases. This page collects them in one place, with the report section that justifies each. The simulation code and raw results behind them are in [`../../studies/crossbar/`](../../studies/crossbar/); the device model itself is [`studies/crossbar/spice/rram.va`](../../studies/crossbar/spice/rram.va) (+ `smoothfunctions.va`) and the transistor card is [`studies/crossbar/device/ptm/`](../../studies/crossbar/device/ptm/).

Status words: **design** = the current design point; **requirement** = something a later phase must provide; **open** = not settled; **broken** = a measured contradiction that has not been resolved.

## Array

| item | value | status | where |
|---|---|---|---|
| organisation | 512 rows x 160 weight columns = five 512 x 32 macros; 2T2R cell (two 1T1R devices on two bitlines, shared word line and row line) | design | [1C §0, §5](../../reports/phase1c_report.md) |
| cell | 20 F^2 per 1T1R (2T2R = 40 F^2), pitch 0.201 um, PTM 45 nm LP access transistor W = 0.54 um | design | [1A §3](../../reports/phase1a_report.md), [1B §0](../../reports/phase1b_report.md) |
| device states | LRS 541.8 ohm (gap 0.2 nm), HRS 218,586 ohm (gap 1.7 nm), at 0.1 V | design - **broken by 1D-ii**: the 20 F^2 cell cannot write them, and they sit on the model's clamps | [1A §10](../../reports/phase1a_report.md), [1D-ii §3](../../reports/phase1d_ii_report.md) |
| group size g | 8 contiguous rows supported by the device's placement accuracy (model); **g = 4 is the deliverable design point** | design | [1F §8](../../reports/phase1f_report.md), [1D-ii §7](../../reports/phase1d_ii_report.md) |
| row drivers | both ends of every 32-cell macro row, <= 10-20 ohm each | design | [1C §4.1](../../reports/phase1c_report.md) |
| supply / ground rails | <= 0.0072 ohm/pitch, fed from both ends | design | [1C §4.2](../../reports/phase1c_report.md) |
| per-group threshold ladder + rank-3 row-gain correction | 16,140 + 19,584 bits | design | [1C §3.3](../../reports/phase1c_report.md) |

## Read path

| item | value | status | where |
|---|---|---|---|
| sense front-end | regulated current conveyor + 1:4 copy into a charge integrator (topology b); virtual ground 0.25 V, row supply 0.35 V | design | [1F §2](../../reports/phase1f_report.md) |
| pulse | T = 1 ns (g = 4) / 2 ns (g = 8), tail 0.3 ns | design | [1F §4](../../reports/phase1f_report.md) |
| columns per pass, decoupling | 40 columns per pass, 1 nF | design | [1F §5](../../reports/phase1f_report.md) |
| calibration | 2 x 2 x 10-bit trims per column, re-fit with 162 full-array reads | design | [1F §3.3](../../reports/phase1f_report.md), [1D-i §5](../../reports/phase1d_i_report.md) |
| recalibration window | 5 K (front end) - **~0.5 K once the access transistor's temperature coefficient is included**, unless the ladder scale tracks temperature | **broken by 1D-ii** | [1D-ii §5c, §6](../../reports/phase1d_ii_report.md) |
| access transistor at the read bias | ~2 kohm (source at 0.25 V), not the 1016 ohm used through 1F | **open: 1F to re-close** | [1D-ii §6](../../reports/phase1d_ii_report.md) |
| read disturb | ~0.1 V SET-direction stress per read: refresh every ~2e4 inferences at 27 C unless the read polarity alternates | **open: 1F change** | [1D-ii §5b](../../reports/phase1d_ii_report.md) |
| energy / area | 5.29 uJ per inference (g = 4), 0.43 mm^2 | design | [1F §4, §7](../../reports/phase1f_report.md) |

## Write path

| item | value | status | where |
|---|---|---|---|
| cell orientation | access transistor on the BITLINE side (SET gets the full voltage; RESET is source-follower capped at ~0.5 V) | design | [1D-i §1.3](../../reports/phase1d_i_report.md) |
| parallelism | 160 devices per pulse (one row), two row-parallel phases (RESET, then SET) | design | [1D-i §1.5, §3](../../reports/phase1d_i_report.md) |
| non-target bitlines | V/2 in the SET phase, 0 V in the RESET phase | design | [1D-i §2](../../reports/phase1d_i_report.md) |
| drivers | thick-oxide row-end drivers with a 0.35 V / V_write supply mux; three-level bitline drivers; isolation switch to the sense front-end | requirement (0.15-0.96 mm^2) | [1D-i §1.4](../../reports/phase1d_i_report.md) |
| program-verify | bidirectional ISPP, millisecond pulses inside the envelope, verify = 1F's read averaged over 4-16 reads; sigma_lnG 0.03-0.06 (model) | design | [1D-ii §4](../../reports/phase1d_ii_report.md) |
| full-array program | ~1-2 minutes, ~1 J (in-envelope) | design | [1D-ii §4.5](../../reports/phase1d_ii_report.md) |
| the write sequence for the RTL | row-sequential, two phases, 160-bit weight row -> both target masks, 320-bit retired mask, three bitline levels | requirement (RTL) | [1D-i §4](../../reports/phase1d_i_report.md) |
| a write path that can program the design states in <= 1 us | 100-200 F^2 thick-oxide access transistor, 3 V word line, short bitlines | **open: a different array** | [1D-ii §3](../../reports/phase1d_ii_report.md) |
