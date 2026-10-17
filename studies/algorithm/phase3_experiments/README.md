# Phase 3 — CIM-NeuroHDC candidate-idea experiments

Four experiments testing the candidate CIM ideas in `novelty_review_and_proposals.md`
against the frozen, accuracy-matched DVS-Gesture NeuroHDC model
(`../phase1_firing_characterization/`, `../dvs_accuracy_report.md`). Results:
**`../phase3_results.md`**.

**Hard rule, honored throughout:** the core NeuroHDC algorithm and the frozen
training configuration are never modified. Experiment 1 changes exactly one
thing — the parameterization of the class hypervector — and reuses every
other frozen hyperparameter verbatim (see `src/train_factorized.py`
`FROZEN` dict). Experiments 2–4 make no model changes at all.

## Layout

```
phase3_experiments/
├── README.md                          this file
├── novelty_review_and_proposals.md    the idea review this phase tests
├── src/
│   ├── factorized_model.py            Experiment 1: NeuroHDCFactorized (subclasses the frozen NeuroHDC)
│   ├── train_factorized.py            Experiment 1: training driver, frozen config reused exactly
│   ├── exp2_early_exit.py             Experiment 2: margin-based early exit, replayed on existing rasters
│   ├── exp3_input_sparsity.py         Experiment 3: input-frame (SNN-side) sparsity
│   ├── energy_model.py                Experiment 4: layout-vs-alpha sweep (unchanged from input; alpha could not be measured, see phase3_results.md)
│   ├── feasibility.py                 supporting: leak budget, array shapes, row utilization (unchanged from input)
│   └── traffic.py                     supporting: where NeuroHDC's memory traffic goes (unchanged from input)
└── artifacts/
    ├── checkpoints/   *.pt for every Experiment 1 run
    ├── tables/        *.json sidecar per run (full config + per-epoch history), exp2/exp3 result JSONs
    ├── figures/       accuracy-vs-R, exit-timestep, input-sparsity histograms
    └── logs/          stdout of every training run
```

## Re-running

All commands assume `cd phase3_experiments && source ../myenv/bin/activate`.

**Reproduce the baseline first** (required before anything else; done once,
confirmed exact match to `dvs_accuracy_report.md`):
```bash
# see phase3_results.md section 0 for the exact snippet used
```

**Experiment 1** — one run is one `(rank, factor_mode, init, seed)` config:
```bash
python3 src/train_factorized.py <run_name> --rank 4 --factor_mode binary \
    --init svd --baseline_seed <seed> --seed <seed> --final_test
```
`--baseline_seed` selects which frozen baseline checkpoint
(`../phase1_firing_characterization/artifacts/dvs_accuracy/frozen_seed{N}.pt`)
supplies the SVD-init source; it is matched to `--seed` throughout this phase
(seed-matched init, per the task spec). `--init random` skips SVD entirely
(random-init control). Sidecar JSON: `artifacts/tables/<run_name>.json`.

**Experiment 2** (no training, ~seconds):
```bash
python3 src/exp2_early_exit.py
```
Reads the existing captures at
`../phase1_firing_characterization/artifacts/rasters/dvsgesture_frozen_n20_T100_seed{0,1,2}.npz`
and the N-MNIST capture; writes `artifacts/tables/exp2_early_exit.json`.

**Experiment 3** (no training, ~1-2 min, dominated by N-MNIST's 10,000 samples):
```bash
python3 src/exp3_input_sparsity.py
```
Re-parses the raw event files through the exact existing
`events_to_frames`/`_read_nmnist_bin`/`DVSGestureDataset` pipeline in
`../phase1_firing_characterization/src/neurohdc.py` — no changes to that
pipeline. Writes `artifacts/tables/exp3_input_sparsity.json`.

**Experiment 4**: could not produce a defensible measured `alpha` in this
environment (no CACTI, no sudo to install it, no sourced published number for
the exact array shapes at NeuroHDC's node) — see `phase3_results.md` section 4
for what was tried and why it stopped there. `energy_model.py` is left as the
alpha-swept comparison it was given as; `feasibility.py`/`traffic.py` are
unchanged supporting scripts, re-run to confirm they still execute against
this repo's actual `firing_rate_summary.json` path (which differs from the
`cim-neurohdc/` path baked into the original `traffic.py` — fixed here, noted
inline in that file).

## Validation protocol (Experiment 1)

- Model selection: best **validation**-epoch only (`user19`–`user23` held out
  from the 23 official DVS-Gesture training users — identical split to
  `../phase1_firing_characterization/src/train_dvs.py`). The 240-sample
  official test set is evaluated exactly once per `(rank, mode, seed)` run,
  after that run's own configuration is frozen by validation selection —
  never used to choose `rank`, `factor_mode`, or `init`.
- 3 seeds (0, 1, 2) for every reported configuration.
- Every run's exact config, seed, per-epoch history and wall time is in its
  `artifacts/tables/<run_name>.json` sidecar.
