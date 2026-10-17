# Design - what is implemented

| folder | contents | entry point |
|---|---|---|
| [`rtl/`](rtl/) | the Phase 1 SNN in SystemVerilog (`rtl/phase1_snn/`, `rtl/pkg/`), its cocotb / SystemVerilog testbenches, lint / regression / synthesis scripts and their results | [`rtl/README.md`](rtl/README.md), report [`../reports/phase1e_report.md`](../reports/phase1e_report.md) |
| [`reference_model/`](reference_model/) | the bit-exact fixed-point reference of NeuroHDC (Phase 0): the integer model, the frozen trained weights, and the golden test vectors the RTL is checked against (`tb/vectors/`) | [`reference_model/README.md`](reference_model/README.md), report [`../reports/phase0_report.md`](../reports/phase0_report.md) |
| [`crossbar/`](crossbar/README.md) | the ReRAM crossbar as designed: cell, array, read path, write path - every decision with the report section behind it. The device model (`rram.va`) and the PTM transistor card live with the simulations in [`../studies/crossbar/`](../studies/crossbar/) | [`crossbar/README.md`](crossbar/README.md) |
