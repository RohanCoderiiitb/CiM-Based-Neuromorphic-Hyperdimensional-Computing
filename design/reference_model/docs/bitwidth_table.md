# Bit-width table (Phase 0)

Sized from **measured maxima**, never from NeuroHDC's 22-bit V. Regenerate with `model/fixedpoint/make_report.py`.

## Frozen widths

| Signal | Frozen width | Format | Measured extreme | Representable limit | Headroom | IMPLEMENTATION_README 0.4 estimate |
|---|---|---|---|---|---|---|
| address | 9 | unsigned | 511 | 511 | — | 9 |
| weight | 8 | signed, range [-127, 127] (-128 never occurs) | ±127 | [-128, 127] | — | 8 |
| `W_COUNT` (c[addr]) | **11** | unsigned | 1208 | 2047 | 1.69x | 12 (worst case) |
| `W_X` (X_j) | **21** | signed | -593,774 | -1,048,576 | 1.77x | 20 (mean N_e; too small: see note) |
| `W_V` (V_j and adder Vp_j) | **26** | signed | -18,804,676 | -33,554,432 | 1.78x | 27 (worst case) |
| `W_THRESH` (thresh_int_j) | **15** | signed (always > 0) | 11,431 | 16,383 | 1.43x | — (was fixed-point with F bits) |

The widths are the smallest that hold every measured value (DVS test + train, 3 seeds; N-MNIST full test). Headroom is 1.7-1.8x on every datapath
signal. They are **not** proofs of no overflow for arbitrary inputs; the data-free worst-case ceilings are below (W_X 22, W_V 29).
Whether to add a guard bit, or a saturation or overflow flag on V, is a Phase 1 design decision. Note: `W_X` = 21, not the plan's 20, because the largest DVS samples have
far more than the mean 4,071 events per timestep (max Σc per step = 15,946), even though the measured |X| is well below the worst case.

## Measured maxima

| Scope | max c | X min | X max | Vp min | Vp max | V(stored) max | max Σc per step |
|---|---|---|---|---|---|---|---|
| DVS test, seed 0 | 1208 | -552,974 | 494,847 | -14,091,019 | 494,847 | 11,155 | 13,860 |
| DVS test, seed 1 | 1208 | -483,379 | 590,700 | -14,995,219 | 590,700 | 11,428 | 13,860 |
| DVS test, seed 2 | 1208 | -504,616 | 551,226 | -15,286,755 | 551,226 | 9,285 | 13,860 |
| DVS train, seed 0 | 1110 | -435,694 | 486,432 | -16,977,465 | 486,432 | 11,170 | 15,946 |
| DVS train, seed 1 | 1110 | -551,528 | 557,761 | -16,323,572 | 509,758 | 11,430 | 15,946 |
| DVS train, seed 2 | 1110 | -593,774 | 490,852 | -18,804,676 | 490,852 | 9,312 | 15,946 |
| N-MNIST test (full), seed 0 | 10 | -1,353 | 2,142 | -24,911 | 2,142 | 391 | 79 |
| **All (frozen from this)** | 1208 | -593,774 | 590,700 | -18,804,676 | 590,700 | 11,430 | 15,946 |

The negative side of V is the binding constraint: a neuron driven negative keeps integrating with no leak and no lower clamp (the algorithm has none).
The N-MNIST train split was not measured: every N-MNIST quantity is 2-3 orders of magnitude inside the DVS-derived widths (thresholds 36–392).

## Worst-case ceilings (data-free, from the checkpoints' int8 weights and recorded event counts)

| Dataset / seed | max c[addr] | X range | Vp range | W_COUNT | W_X | W_V |
|---|---|---|---|---|---|---|
| dvsgesture_seed0 | 13860 | [-1760220, 1760220] | [-176022000, 1771393] | 14 | 22 | 29 |
| dvsgesture_seed1 | 13860 | [-1760220, 1760220] | [-176022000, 1771650] | 14 | 22 | 29 |
| dvsgesture_seed2 | 13860 | [-1760220, 1760220] | [-176022000, 1769536] | 14 | 22 | 29 |
| nmnist_seed0 | 79 | [-9717, 10033] | [-971700, 10424] | 7 | 15 | 21 |

Bounds assume the worst case allowed by the data format: every event of a timestep at one address (`c_max = ceil(n_events/T)` of the
largest recorded sample) hitting the most positive / most negative weight, and up to T consecutive non-firing steps for the negative V bound.

## Conventions
- `V` datapath width covers the **adder output** `Vp = V + X` (before compare/reset); the stored register is always `< thresh` (or 0 after a spike) on the high side, but has no lower clamp.
- `thresh_int` is an integer (exact ceil); there are no fractional bits.
- A timestep holds `N_e` or `N_e+1` events (see phase0_report.md section 5), so `Σ_addr c[addr] <= N_e+1`.
