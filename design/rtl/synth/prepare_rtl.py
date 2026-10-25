#!/usr/bin/env python3
"""Prepares the RTL for the owner's Genus run - without changing the repository's RTL. For one build it writes synth/work/<build>/ with
  rtl/            a copy of the RTL in which
                    * the package defaults are the build's (FACTORIZED, EARLY_EXIT_EN) with INSTRUMENT_EN = 0 and CHECK_UNIPOLAR = 0 (the synthesized configuration of every number in the reports),
                    * rtl/common/clk_gate.sv is replaced by synth/rtl/clk_gate_icg.v (the structural TLATNCAX2),
                    * the behavioural cim_macro.sv / hdc_class_array.sv are NOT copied: the analog macros come from their Liberty / LEF (synth/macro/), as library cells,
                    * the `#(...)` parameter lists are stripped from their two instantiations (a library cell has no parameters; the macro is not parameterised by the digital g);
  filelist.f      the files in compile order;
  macro.lib/.lef  the Liberty and LEF of the right class-array macro (factorized or not) and of the crossbar macro.
It then elaborates the prepared RTL with Yosys (the macros and the ICG as black boxes) as a check that the preparation is complete: `hierarchy -check`.
Same configuration as the pre-route numbers: ROWS_PER_GROUP = 8 (the package default) for the digital netlist; the g = 4 cycle counts come from the RTL regression, as in Phase 5.

  python design/rtl/synth/prepare_rtl.py --build full|ee_off|fact_off|both_off
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
import synth_ppa as S  # noqa: E402

PDK_LIB = ROOT.parents[1] / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lib"
ORDER = ["pkg", "common", "phase1_snn", "phase2_hdc", "phase4_exit", "phase3_top"]
SKIP = {"cim_macro.sv", "hdc_class_array.sv", "clk_gate.sv"}


def strip_params(txt: str, module: str) -> str:
    """cim_macro #( ... ) u_name (  ->  cim_macro u_name (   (balanced parentheses)"""
    out, i = [], 0
    pat = re.compile(rf"\b{module}\s*#\s*\(")
    while True:
        m = pat.search(txt, i)
        if not m:
            out.append(txt[i:])
            break
        out.append(txt[i:m.start()] + module)
        j, depth = m.end(), 1
        while depth:
            depth += {"(": 1, ")": -1}.get(txt[j], 0)
            j += 1
        i = j
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True, choices=list(S.BUILDS))
    a = ap.parse_args()
    f, e = S.BUILDS[a.build]
    work = HERE / "work" / a.build
    if work.exists():
        shutil.rmtree(work)
    (work / "rtl").mkdir(parents=True)
    files: list[Path] = []
    for d in ORDER:
        for src in sorted((ROOT / "rtl" / d).glob("*.sv")):
            if src.name in SKIP:
                continue
            txt = src.read_text()
            if src.name == "hdc_pkg.sv":
                txt = re.sub(r"(FACTORIZED_DEFAULT\s*=\s*)1'b\d", rf"\g<1>1'b{f}", txt)
                txt = re.sub(r"(EARLY_EXIT_EN_DEFAULT\s*=\s*)1'b\d", rf"\g<1>1'b{e}", txt)
                txt = re.sub(r"(CHECK_UNIPOLAR_DEFAULT\s*=\s*)1'b\d", r"\g<1>1'b0", txt)
            if src.name == "cim_neurohdc_pkg.sv":
                txt = re.sub(r"(INSTRUMENT_EN_DEFAULT\s*=\s*)1'b\d", r"\g<1>1'b0", txt)
            txt = strip_params(strip_params(txt, "cim_macro"), "hdc_class_array")
            dst = work / "rtl" / f"{d}__{src.name}"
            dst.write_text(txt)
            files.append(dst)
    icg = work / "rtl" / "common__clk_gate_icg.v"
    shutil.copy(HERE / "rtl" / "clk_gate_icg.v", icg)
    files.insert(1 + len(list((ROOT / "rtl" / "pkg").glob("*.sv"))), icg)
    macro = HERE / "macro"
    hdc = "hdc_class_array_fact" if f else "hdc_class_array_unfact"
    for n, dst in (("cim_macro", "cim_macro"), (hdc, "hdc_class_array")):
        for ext in ("lib", "lef"):
            if (macro / f"{n}.{ext}").exists():
                shutil.copy(macro / f"{n}.{ext}", work / f"{dst}.{ext}")
    (work / "filelist.f").write_text("\n".join(str(p) for p in files) + "\n")
    # check: elaborate with the macros and the ICG as black boxes
    ys = work / "check.ys"
    ys.write_text("\n".join([f"read_liberty -lib {PDK_LIB / S.LIBS['fast']}", f"read_liberty -lib {work / 'cim_macro.lib'}", f"read_liberty -lib {work / 'hdc_class_array.lib'}",
                             *(f"read_verilog -sv {p}" for p in files), "hierarchy -check -top cim_neurohdc_top", "stat"]))
    r = subprocess.run(["yosys", "-q", "-l", str(work / "check.log"), str(ys)], capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"[{a.build}] prepared {len(files)} files in {work}; yosys hierarchy -check on the prepared RTL: {'OK' if ok else 'FAILED'}")
    if not ok:
        print((r.stdout + r.stderr)[-1500:])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
