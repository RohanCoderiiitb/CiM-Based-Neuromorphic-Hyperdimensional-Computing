# Golden-vector and weight-image formats (FORMAT_VERSION 1.0)

All integers are plain two's complement. No floats anywhere. `S` = samples, `T` = 100.
Timestep index `t` = 0..99. Neuron index `j` = 0..19. Address `a` = 0..511,
`a = p*256 + row*16 + col` (NeuroHDC eq. 19). NumPy `.npz` files (`np.load`).

## `tb/vectors/<dataset>/counts.npz`   (seed-independent)
| key | dtype | shape | meaning |
|---|---|---|---|
| `counts` | uint16 | [S,100,512] | `c[t,a]` — events at address `a` in timestep `t` (output of the original `events_to_frames`) |
| `labels` | int16 | [S] | ground truth |
| `n_events` | int32 | [S] | total events in sample |
| `N_e` | int32 | [S] | `floor(n_events/T)` |
| `sample_id` | str | [S] | source file path (provenance) |

## `tb/vectors/<dataset>/seed<k>.npz`
| key | dtype | shape | meaning |
|---|---|---|---|
| `thresh_int` | int32 | [S,20] | `ceil(v_thresh/s_j)`; for N-MNIST `ceil(v_thresh*N_e/s)` (sample dependent; per-tensor quantizer, so all 20 equal), for DVS-Gesture the same row for every sample |
| `X` | int32 | [S,100,20] | `X_j(t)=sum_a c[t,a]*W[j,a]` |
| `Vp` | int32 | [S,100,20] | adder output `V_j(t-1)+X_j(t)`, before compare/reset |
| `V` | int32 | [S,100,20] | stored register after reset (`0` if spike else `Vp`) |
| `spikes` | uint8 | [S,100,20] | `Vp >= thresh_int` |
| `pred` | int8 | [S] | argmax of final XNOR score (ties -> lowest index) |
| `score_xnor_prefix` | int16 | [S,100,10] | `sum_{t'<=t} sum_j XNOR(S[t',j], C_i[t',j])`; row 99 is the eq. (21) score |
| `float_pred` | int8 | [S] | prediction of the float model, fresh CPU run |
| `float_raster_identical` | uint8 | [S] | 1 if that sample's float raster equals `spikes` |

Class hypervectors `C_i[t,j]` (needed to recompute scores) are in
`artifacts/phase0/class_hv_seed<k>.npy`, uint8 [10,100,20], 1 = +1, 0 = -1.
Update order per timestep: `Vp = V + X; spike = Vp >= thresh; V = spike ? 0 : Vp`; `V(-1)=0`.

## `tb/vectors/<dataset>/events.npz`   (raw AER streams, seed-independent)
Streams of selected samples, concatenated. Stream `i` is `[offset[i], offset[i+1])` and is counts row `sample_row[i]`.
| key | dtype | shape | meaning |
|---|---|---|---|
| `aer` | uint16 | [E] | input event word in stream order. DVS-Gesture: `p<<14 \| y<<7 \| x` (x,y in 0..127); N-MNIST: `p<<12 \| y<<6 \| x` (x,y in 0..33) |
| `addr` | uint16 | [E] | expected address-generator output, eq. (19) (`model/fixedpoint/events.py: address`) |
| `offset` | int64 | [n+1] | stream boundaries |
| `sample_row` | int32 | [n] | row in `counts.npz` |
| `n_events`, `N_e`, `remainder` | int | [n] | `n`, `n//T`, `n mod T` |
| `label` | int16 | [n] | ground truth |

Timestep of event `k` in an `n`-event stream: `floor(k*T/n)`, so a timestep holds `N_e` or `N_e+1` events. Hardware form: `acc += T` per event,
`while acc >= n: acc -= n; boundary` (`events.boundary_counter_bins`). DVS-Gesture exports 20 streams (per class, fewest and most events);
N-MNIST exports all 1,000 subsample streams. Any other sample: `events.read_stream(dataset, sample_id)`.
Timestamps are not exported; only the order matters (stable sort by t, as in the original datasets).

## `manifest.json`
format version, dataset, seed list, sample counts, sha256 of every `.npz`, frozen widths, provenance.

## `tb/vectors/weights/`
See docstring of `model/export/export_weights.py`. Summary: row = address, 160-bit word,
bit `j*8+k` = plane `k` (0 = LSB, 7 = sign) of neuron `j`; `$readmemh` files list address 0 first,
hex MSB-first. `weights_seed<k>_macro<m>_32b.mem`: neurons `4m..4m+3`, bit `(j%4)*8+k`.
`thresh_seed<k>.mem`: 20 lines, two's-complement hex at the frozen threshold width.

## Phase 2-4 additions (the R=1 networks)  - FORMAT_VERSION 1.1, additive
`tb/vectors/dvsgesture/r1_seed<k>.npz` (k = 0,1,2; the jointly trained R=1 factorized checkpoints `artifacts/checkpoints/r1_binary_svd_seed<k>.pt`), same keys as `seed<k>.npz` plus
| key | dtype | shape | meaning |
|---|---|---|---|
| `a_bits` | uint8 | [10,20] | stationary array: `a_i[j] = 1` means +1 (sign of A) |
| `b_bits` | uint8 | [100,...] -> [10,100] | sign table: `b_i[t] = 1` means +1 (sign of B) |
| `class_hv` | uint8 | [10,100,20] | the expansion `C_i[t,j] = XNOR(a_i[j], b_i[t])` (`hdc_query.expand_r1`), what the unfactorized RTL is loaded with in the identity test |
`score_xnor_prefix` is the XNOR prefix score of the expanded class hypervector (equal, integer for integer, to the factorized AND-popcount form). Weight image tag `r1s<k>`: `weights/weights_seedr1s<k>_*.mem`, `thresh_seedr1s<k>.mem`.
The gate (`artifacts/phase0/r1_gate.json`): the integer pipeline reproduces each checkpoint's recorded float test accuracy exactly (194/240, 196/240, 189/240).

Class image for the RTL (`hdc_pkg.sv`): unfactorized `cmain.mem` = 100 words of 200 bits (class i slice of timestep t at bits [20 i +: 20], address t); factorized `cmain.mem` = 1 word (`a_i` at [20 i +: 20]), `csign.mem` = 100 words of 10 bits (`b_i[t]` at bit i), `cbias.mem` = 1 word of 50 bits (`||a_i||_1` at [5 i +: 5]).
