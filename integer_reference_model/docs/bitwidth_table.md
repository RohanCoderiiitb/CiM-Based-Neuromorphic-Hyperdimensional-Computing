# Bit-width table (Phase 0)

Sized from **measured maxima**, never from NeuroHDC's 22-bit V. Regenerate with `model/fixedpoint/make_report.py`.

## Frozen widths

NOT FROZEN — pending measurement. Worst-case bounds (upper limits, not the frozen values) are in the previous section.

## Worst-case ceilings (data-free, from the checkpoints' int8 weights and recorded event counts)

| Dataset / seed | max c[addr] | X range | Vp range | W_COUNT | W_X | W_V |
|---|---|---|---|---|---|---|
| dvsgesture_seed0 | 13860 | [-1760220, 1760220] | [-176022000, 1771393] | 14 | 22 | 29 |
| dvsgesture_seed1 | 13860 | [-1760220, 1760220] | [-176022000, 1771650] | 14 | 22 | 29 |
| dvsgesture_seed2 | 13860 | [-1760220, 1760220] | [-176022000, 1769536] | 14 | 22 | 29 |
| nmnist_seed0 | 79 | [-10033, 10033] | [-1003300, 10686] | 7 | 15 | 21 |

Bounds assume the worst case allowed by the data format: every event of a timestep at one address (`c_max = ceil(n_events/T)` of the
largest recorded sample) hitting the most positive / most negative weight, and up to T consecutive non-firing steps for the negative V bound.
They are ceilings, not the frozen widths. Note the largest DVS-Gesture sample has 1.39 M events, so the worst-case chunk is 13,860, far above the
mean N_e = 4,071 used for the sizing estimate in IMPLEMENTATION_README 0.4 (which gave W_X = 20).

## Conventions
- `V` datapath width covers the **adder output** `Vp = V + X` (before compare/reset); the stored register is always `< thresh` (or 0 after a spike) on the high side, but has no lower clamp.
- No saturation anywhere: widths must make overflow impossible for inputs like those measured. Measured on the *test* splits (and train split if `--dvs-train-root` was given) — see report for scope.
- `thresh_int` is an integer (ceil, exact); there are no fractional bits.
