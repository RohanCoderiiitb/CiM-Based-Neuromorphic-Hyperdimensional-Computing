# CiM-Based Neuromorphic Hyperdimensional Computing

A compute-in-memory implementation of NeuroHDC (SNN feature extraction + hyperdimensional classification of event-camera data): the SNN's binary weights sit in a 512 x 160 ReRAM 2T2R crossbar read with current-mode sensing, the integer pipeline around it is RTL.

## Where things are

| folder | what is in it |
|---|---|
| [`reports/`](reports/) | **Every phase report, in one place** - start here. [`reports/README.md`](reports/README.md) is the index. |
| [`figures/`](figures/) | **The paper figures** (fig1-fig29, PNG / PDF / SVG with source CSVs and captions). [`figures/README.md`](figures/README.md) lists them by phase. |
| [`design/`](design/) | **What is implemented**: the RTL ([`design/rtl/`](design/rtl/)), the fixed-point golden reference model and its test vectors ([`design/reference_model/`](design/reference_model/)), and the crossbar's design sheet ([`design/crossbar/`](design/crossbar/README.md)). |
| [`studies/`](studies/) | **How it was decided**: the algorithm experiments ([`studies/algorithm/`](studies/algorithm/)) and the crossbar circuit simulations behind phases 1A-1D and 1F ([`studies/crossbar/`](studies/crossbar/), one Python project with its raw results). |
| `data/` | the DVS-Gesture and N-MNIST datasets (not in git) |

## Phases

| phase | what it settles | report | implementation / code |
|---|---|---|---|
| 0 | fixed-point reference model, golden vectors | [phase0](reports/phase0_report.md) | [design/reference_model](design/reference_model/) |
| 1A | device values, access transistor, validated solver | [phase1a](reports/phase1a_report.md) | [studies/crossbar](studies/crossbar/) `validate/` |
| 1B | margin budget, wire IR, drift, g | [phase1b](reports/phase1b_report.md) ([1B-i](reports/phase1b_provisional_report.md)) | `margin/`, `wire/`, `drift/` |
| 1C | the full 512 x 160 array | [phase1c](reports/phase1c_report.md) | `scaleup/` |
| 1D-i | the array-level write path | [phase1d_i](reports/phase1d_i_report.md) | `write/` |
| 1D-ii | the device-level write path, compiled compact model, sigma_lnG | [phase1d_ii](reports/phase1d_ii_report.md) | `program/` |
| 1E | the SNN RTL | [phase1e](reports/phase1e_report.md) | [design/rtl](design/rtl/) |
| 1F | the sense front-end and read timing | [phase1f](reports/phase1f_report.md) | `sense/` |

The plan the phases follow is `IMPLEMENTATION_README.md` (kept locally, not in git).

## Environment

- Python: the repo venv (`myenv/`, not in git); `pip install numpy scipy matplotlib pytest` covers `studies/crossbar`; `design/rtl/requirements.txt` the RTL flow.
- Circuit simulation: ngspice (>= 38 for the compact model) and, for 1D-ii, OpenVAF - `studies/crossbar/spice/osdi.py` finds both on PATH or through `nix-shell -p openvaf ngspice`.
- RTL: Verilator, Icarus, Yosys, Verible (see [`design/rtl/README.md`](design/rtl/README.md)).
