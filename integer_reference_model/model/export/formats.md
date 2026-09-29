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
| `thresh_int` | int32 | [S,20] | `ceil(v_thresh/s_j)`; for N-MNIST `ceil(v_thresh*N_e/s_j)` (sample dependent), for DVS-Gesture the same row for every sample |
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

## `manifest.json`
format version, dataset, seed list, sample counts, sha256 of every `.npz`, frozen widths, provenance.

## `tb/vectors/weights/`
See docstring of `model/export/export_weights.py`. Summary: row = address, 160-bit word,
bit `j*8+k` = plane `k` (0 = LSB, 7 = sign) of neuron `j`; `$readmemh` files list address 0 first,
hex MSB-first. `weights_seed<k>_macro<m>_32b.mem`: neurons `4m..4m+3`, bit `(j%4)*8+k`.
`thresh_seed<k>.mem`: 20 lines, two's-complement hex at the frozen threshold width.
