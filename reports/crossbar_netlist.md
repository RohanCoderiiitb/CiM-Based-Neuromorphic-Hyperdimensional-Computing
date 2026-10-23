# The crossbar netlist generator and its validation

Tags: **[SIM]** an ngspice result, **[MODEL]** the mesh solver (`studies/crossbar/wire/mesh.py`, the reference of Phase 1), **[CHOICE]** a decision taken here. Every number is read from `design/crossbar/results/netlist_validation.json` and `refactor_equivalence.json` by `design/crossbar/make_report.py`; commands in section 7. The generator is `design/crossbar/crossbar_netlist/`; this report is the Step 0 deliverable of Phases 2-5.

## 0. The answer

- **There is now one artefact that IS the circuit.** `design/crossbar/crossbar_netlist/` emits the array hierarchically - cell, group, macro, array - from `ArraySpec`, whose every default is a name in `studies/crossbar/device/constants.py`. A committed example, [`design/crossbar/examples/macro_512x32_g8.sp`](../design/crossbar/examples/macro_512x32_g8.sp) (one 512 x 32-cell macro at g = 8, fixed-resistor devices, parasitic capacitance included, one group of 8 rows selected; 2.0 MB, 27842 lines), opens without running anything and is a valid ngspice deck.
- **It agrees with the mesh solver.** On 1C's own 300-case suite (odd block widths, rails, ground pads, spread), now simulated from the generated hierarchical netlist, the worst column-current disagreement is **1.65e-10** against the 1.30e-10 1C recorded (the other metrics: row-supply current 9.30e-13 against 4.85e-12, rail voltage 9.80e-15 V, ground rail 3.94e-14 V against 2.56e-14). **That is 27 % above 1C's 1.3e-10 on the column current, not below it**: 2 of 300 cases exceed 1C's worst (case 17: 2 active rows, blocks 12-12); section 3.1 says why and what it is not.
- **On the real geometry** (512 rows x 32-cell macro, g = 8, the 1C rails and drivers): worst column-current disagreement **1.40e-10** over 52 reads (group position x active rows x random weights, sigma_lnG = 0.10; absolute 1.97e-15 A); the five-macro 512 x 160 array: **1.15e-10** over 3 reads.
- **'Fixed resistors at the read bias' is exact for what it models and costs 0.65 % (median, 0.79 % worst) of column current against the nonlinear device law.** The resistor flavour agrees with the mesh solver run on a linear device to 1.20e-10; the difference to the sinh law is the I-V curvature at the 50 mV the device sees (a series R_tx of ~1 kohm takes half of the 0.1 V), so a design that must be exact to a few tenths of a percent should use the `sinh` flavour (the default for all validation).
- **The study code now calls the generator and no deck-building text remains in `wire/validate_mesh_ext.py`, `wire/netlist.py` or `scaleup/transient.py`.** No existing result changed: the 60-case DC validation metrics agree with the old decks' to 2.33e-14 V (rails) and the ten 1C transient jobs (149 numbers) to 4.13e-08 relative on every physical quantity (energies, currents, settling times, rail voltages); 50 are bit-identical.

## 1. What it emits

| level | subcircuit | contents |
|---|---|---|
| half | `half rl wl bl (a)` | one device (a = gap in nm for the `sinh` flavour, R in ohm for `resistor`) in series with its access transistor, the transistor on the **bit-line side** (the orientation 1D adopted): row line - device - x - transistor - bit line. Transistor: `switch` (R_tx from constants, gated by the word line; default), `linear` (always on), `bsim` (the PTM 45 nm LP NMOS) |
| cell | `cell2t2r rlp rlm wl blp blm` | the differential 2T2R cell: two halves on BL+ / BL-, one word line |
| group | `grp2_<n> ...` | n contiguous cells on one bit-line pair with the bit-line wire segment (r_bl per pitch) in front of every cell and a tap pin per row node; n = g (the last group of a non-multiple is shorter). A single-bitline variant `grp1_<n>` exists for odd block widths (validation only) |
| row line | `rowline<w>` | the macro row line (r_wl per pitch, broken per macro) with a row driver at **both ends**; the driver is a behavioural switch of R_DRV to the supply tap when the word line is high, pulled to 0 V when it is low |
| macro | `macro<b>` | rows x block-width cells: the groups stacked on each bit-line pair, one row line per row, the sense resistors to a ground rail (r_gnd per pitch) with a pad; parasitic capacitance (ground + neighbour coupling, 1C's convention) when requested |
| array | `array` | the macros side by side, the **shared supply rail** through every row (r_rail per pitch, fed from one or both ends), per-macro ground pads, optional decoupling at every tap |

Every dimension and resistance comes from `device/constants.py` (new names added there: `BL_R_PER_PITCH_1C`, `WL_R_PER_PITCH_1C`, `C_SENSE_F`, `R_OFF_OHM`; the values are the literals the 1C scripts used). `ArraySpec` fields: rows, macro widths, g, device parameters, wire resistances, rail layout, device/transistor/driver flavours, capacitance. Two **views** of the same circuit: `full_deck` (the hierarchy above, every row and every cell present - the artefact) and `reduced_deck` (only the active rows instantiated and the bit line lumped in pi-sections, for transients: an inactive row carries no current, so its omission is exact in DC; its capacitance convention is 1C's, which with lump = 1 and every row active is the hierarchical netlist's per-pitch capacitance).

```
venv/bin/python design/crossbar/generate.py --macros 1 --g 8 --device resistor --caps --active-group 3 -o design/crossbar/examples/macro_512x32_g8.sp
venv/bin/python design/crossbar/generate.py --macros 5 --g 4 -o array_512x160_g4.sp          # the whole array (large)
```

## 2. Decisions and what they cost

- **The transistor is a switch, not a resistor** so that the word line is real and one netlist serves any selection pattern. `sw` with the linear-equivalent R_tx (1A) as R_on: identical to a resistor to 1e-12 when on.
- **The OFF resistance had to be chosen** ([CHOICE] `R_OFF_OHM = 1e16`). 1e18 left the floating nodes of unselected rows so weakly tied that ngspice's DC operating point needed dynamic gmin stepping (6.7 s against 0.1 s on a 24-bit-line case); 1e12 converges as fast but leaks 1.6e-9 of the column current; 1e16 solves in 0.16 s and agrees with 1e18 to 1e-12.
- **The row driver is a smooth behavioural switch, not an `sw`.** With `sw` drivers one case of the 300 needed 24 s (source stepping), another hung for minutes; the same conductance as a B-source, `V/R_DRV * 0.5 (1 + tanh((V(en) - v_wl/2)/10 mV))`, is exactly 1 or 1e-48 at the two word-line levels and converges in 0.08 s. Unselected row lines are pulled to 0 V (a real driver is push-pull); without the pull-down they float and the matrix is near singular.
- **'Fixed resistors at the read bias'** is the `resistor` device flavour: R = V_read / I(V_read) of the Stanford-PKU law (R_LRS 541.8 ohm, R_HRS 218,586 ohm at the programmed gaps, and the same secant for any spread gap). The `sinh` flavour (default for validation) carries the device law itself.

## 3. Validation against the mesh solver

The solver is the reference. Each case: build the netlist, solve it with ngspice (`.op`), solve the same array with `solve_mesh_ext`, compare the column currents (relative), the row-supply currents, the supply-rail voltage at the active rows and the ground-rail voltage.

| suite | cases | worst |dI_col|/I_col | worst |dI_row|/I_row | worst rail V (V) | worst ground V (V) |
|---|---|---|---|---|---|
| A. 1C's 300 random small arrays (odd widths, rails, pads, sigma 0.10) | 300 | 1.65e-10 | 9.30e-13 | 9.80e-15 | 3.94e-14 |
| B. one macro, 512 rows x 32 cells, g = 8: 6 group positions x 4 active counts x 2 weight patterns + 4 scattered reads | 52 | 1.40e-10 | 1.26e-11 | 2.16e-13 | 2.57e-14 |
| C. five macros, 512 x 160 cells | 3 | 1.15e-10 | 6.39e-12 | 1.88e-13 | 2.54e-14 |
| D. resistor flavour vs the solver on a linear device (4 reads) | 4 | 1.20e-10 | 5.83e-12 | - | - |

1C's recorded worst on suite A: column current 1.30e-10, row current 4.85e-12, ground 2.6e-14 V. 

### 3.1 Why suite A's column-current worst is 1.65e-10 and what that means

The two cases above 1C's worst are reads of only 2 active rows in which one column carries ~6e-7 A while the shared ground rail sits ~10 mV above ground: the metric is |(v_s - v_g)/R_s| of a node pair 4 orders of magnitude larger than the difference. The *absolute* disagreement there is ~1e-16 A, the size of ngspice's `abstol`, and tightening `abstol`, `vntol` or `reltol` does not change it (identical to the bit): it is round-off of the LU solve of a system with 18 decades of conductance (1e-16 S open switches next to 1e4 S driver ties), and the dense netlist has ~15x more nodes than the old reduced decks. The solver's own tolerances are not the cause either (tightening them to 1e-15 changes nothing). Everything else is better than 1C's: the row-supply current 5x, the rail voltage ~2x. The 1C acceptance threshold of `wire/validate_mesh_ext.py` is 1e-6; 1.3e-10 was the *observed* worst, not a tolerance, and every case here is four orders of magnitude inside the threshold.

## 4. The reduced (transient) view against the full hierarchy

| bit-line lump | settled node voltages, reduced vs full | supply current, reduced vs full | worst transient difference / final value (0.05-0.6 ns) |
|---|---|---|---|
| 1 | 8.29e-13 | 2.65e-13 | 5.70e-13 |
| 16 | 8.29e-13 | 2.65e-13 | 2.85e-13 |

A 64-row, 16-bit-line array, one group selected, ideal supply and ground. The DC solutions agree to round-off (the reduction is exact). With lump = 1 the reduced view's per-pitch capacitance is the hierarchical netlist's; with 1C's lump = 16 the transient differs by the second number - the cost of 1C's lumping, not of the generator.

## 5. The refactor changed no result

`design/crossbar/refactor_check.py` re-runs, with the generator, the cases whose outputs were recorded from the OLD decks immediately before the old deck-building code was removed (`design/crossbar/results/baseline_old_decks/`).

|  | cases / numbers | worst difference |
|---|---|---|
| DC: first 60 cases of `wire/validate_mesh_ext.py` | 60 | validation metrics: column current 1.24e-10 (old max 4.56e-11, new max 1.65e-10), row current 4.50e-12, rail 2.24e-14 V, ground 2.33e-14 V |
| transient: 10 jobs of `run_energy_latency`, `run_supply_dynamics`, `run_crosstalk`, `run_crosstalk_bitplane`, `run_array_transient` | 149 numbers, 50 bit-identical | 4.13e-08 relative on every physical quantity; the noise-floor residuals (settled error ~1e-16 A, a 6e-13 flatness ratio) are not results |

Files changed in `studies/crossbar/`: `wire/netlist.py` (now only `run_mesh_ngspice` -> `ArraySpec`), `wire/validate_mesh_ext.py` (calls `run_full_op`), `scaleup/transient.py` (`build_tran_deck` -> `reduced_deck`; `TranConfig`, `run_tran`, `currents`, `energy_to` unchanged), `device/constants.py` (4 named constants), new `spice/xbar.py` (import shim). `wire/validate_mesh.py` (1B, 1792 cases) and `tests/test_wire_drift.py` reach the generator through `wire.netlist.run_mesh_ngspice` unchanged. Not touched, because they are not the array: `spice/netlist.py` (1A's independent single-column decks), `write/` (1D), `sense/` (1F) and the other single-purpose decks of closed phases - listed here so that nobody reads 'no duplicate deck-building code' as covering them.

## 6. The access transistor as a transistor

`tx='bsim'` puts the PTM 45 nm LP BSIM4 NMOS (W, L from the constants) in the cell, gate on the word line: on a 16 x 8 array the column currents differ from the linear R_tx by 3.41 % (median), 3.50 % worst - 1A's bound for one branch was 0.07 %; a column sees many branches with different source voltages. Informational: the validation above uses the linear equivalent, as the solver does.

## 7. Reproduce

```
venv/bin/python design/crossbar/validate_netlist.py          # suites A-F, ~1-2 h (the 512-row dense solves take ~2 min each, the five-macro array ~30 min)
venv/bin/python design/crossbar/refactor_check.py            # old decks vs generated decks
venv/bin/python design/crossbar/make_report.py               # this file
```

## 8. TO BE DETERMINED / not done

- **The 1.3e-10 -> 1.65e-10 on suite A** is explained as solver round-off, not proven: a long-double or multi-precision reference solve of cases 17 and 85 would settle whether the netlist or the mesh solver is the less accurate one.
- **The dense 512 x 160 transient** is not simulated (the reduced view exists for that); a hierarchical transient of the whole array is hours of ngspice. Macro-boundary coupling: the hierarchical netlist couples bit lines only inside a macro; the reduced view keeps 1C's coupling across the macro boundary (2 of 320 columns).
- **No spread, drift or temperature in the netlist file itself**: states are the programmed gaps (or resistances) per cell; Monte-Carlo is in the callers.
- **The write path** (forming/SET/RESET, three-level bit-line drivers) is not in the netlist: Phase 1D is closed; the cell has the right orientation for it (transistor on the bit-line side) but no write pins.
- **Sense front-end**: the macro ends at the sense node and `R_s` to the ground rail (+ `C_sense`); 1F's conveyor/integrator/comparator are separate decks (`studies/crossbar/sense/`).
- **Verible / lint** do not apply (SPICE).
