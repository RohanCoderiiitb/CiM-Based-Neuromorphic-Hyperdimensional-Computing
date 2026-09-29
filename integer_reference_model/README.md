# integer_reference_model — NeuroHDC exact integer reference (Phase 0)

Integer-domain golden model that all later RTL is verified against. Algorithm is unchanged; this
adds an integer inference path *beside* the float one. Full write-up: [phase0_report.md](phase0_report.md).
Bit widths: [docs/bitwidth_table.md](docs/bitwidth_table.md). Vector format: [model/export/formats.md](model/export/formats.md).

```
model/neurohdc/     byte-identical COPIES of phase2_firing_characterization/src (originals untouched)
model/fixedpoint/   quantize.py (int8 + exact ceil thresholds)  int_model.py (THE golden model)
                    data.py / pipeline.py (reuse original data pipeline; compare, measure)
                    run_phase0.py (on-data driver + hard gate)  check_stored_rasters.py (data-free checks)
                    make_report.py (renders phase0_report.md + docs/bitwidth_table.md)
model/export/       export_weights.py (bit-plane image, .mem)  export_vectors.py  load_vectors.py  formats.md
tests/              test_int_model.py (data-free, synthetic events + real weights)
tb/vectors/         golden vectors + weight images (written by run_phase0.py)
artifacts/          checkpoints/ reference_rasters/ (copies)   phase0/ (JSON results)
reference_docs/     copies of the audit, accuracy report, experiment spec, firing-rate results
```

## Run
```
pip install torch numpy
python tests/test_int_model.py                      # data-free, seconds
python model/fixedpoint/check_stored_rasters.py     # data-free, real recorded rasters
python model/fixedpoint/run_phase0.py --data-root /path/to/data [--dvs-train-root .../ibmGestureTrain] [--nmnist-per-class 100]
python model/fixedpoint/make_report.py              # refresh report + bitwidth table from results.json
```
`--data-root` must contain `DVSGesture/ibmGestureTest`, `NMNIST/Test` (same layout as the original scripts).
`run_phase0.py` stops (exit non-zero, no export) if any seed's integer pipeline fails to reproduce its recorded accuracy.
