# Studies - how the design was decided

| folder | contents |
|---|---|
| [`algorithm/`](algorithm/) | the algorithm-side experiments that preceded the hardware: the literature analysis and NeuroHDC audit (`phase1_literature_analyses_and_documentation/`), firing-rate characterisation of the trained SNN (`phase2_firing_characterization/`), and the factorised-model / early-exit / input-sparsity experiments (`phase3_experiments/`). Their scripts expect the datasets under `data/` (see each folder's README). |
| [`crossbar/`](crossbar/) | the circuit simulations behind phases 1A, 1B, 1C, 1D-i, 1D-ii and 1F: one Python project (run every command from inside this folder) with its device model, solvers, ngspice / OpenVAF harness, and every raw result. Its README lists each phase's commands; `results/README.md` indexes the raw results. Reports go to [`../reports/`](../reports/), figures to [`../figures/`](../figures/). |

Package map of `crossbar/` by phase: `device/`, `spice/`, `solver/` (shared) - `validate/` (1A) - `margin/`, `wire/`, `drift/` (1B) - `scaleup/` (1C) - `write/` (1D-i) - `program/` (1D-ii) - `sense/` (1F) - `tests/`.

Since Phase 2-5 the ngspice decks of `crossbar/` (the mesh validation `wire/validate_mesh*.py`, the 1C transients `scaleup/`) are no longer built by code in this folder: `crossbar/spice/xbar.py` imports the netlist generator in [`../design/crossbar/crossbar_netlist/`](../design/crossbar/crossbar_netlist/), which is the single artefact that IS the circuit. `wire/netlist.py` and `scaleup/transient.py` only translate their arguments into an `ArraySpec`.
