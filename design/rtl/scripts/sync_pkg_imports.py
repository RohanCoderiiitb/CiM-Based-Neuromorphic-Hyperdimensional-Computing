#!/usr/bin/env python3
"""Rewrite the package import line of every RTL module as an EXPLICIT list of the cim_neurohdc_pkg symbols that file uses.

Why: Yosys' read_verilog cannot parse `module m import pkg::*; (...)`, and Verilator warns (IMPORTSTAR) about `import pkg::*;` at
compilation-unit scope. Explicit one-per-line `import pkg::NAME;` statements before the module satisfies both. Run after editing a module or the package.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pkg = (ROOT / "rtl/pkg/cim_neurohdc_pkg.sv").read_text()
names = set(re.findall(r"localparam\s+(?:int|bit|logic\s*\[[^\]]*\])\s+(\w+)\s*=", pkg))
names |= set(re.findall(r"typedef\s+enum[^{]*\{([^}]*)\}\s*(\w+)\s*;", pkg) and
             [m for grp in re.findall(r"typedef\s+enum[^{]*\{([^}]*)\}", pkg) for m in re.findall(r"(\w+)\s*=", grp)])
names |= set(re.findall(r"\}\s*(\w+_e)\s*;", pkg))
for f in sorted((ROOT / "rtl/phase1_snn").glob("*.sv")):
    s = f.read_text()
    body = re.sub(r"^import [^;]*;\n", "", s, flags=re.M)          # drop old import lines
    code = re.sub(r"//.*", "", body)
    used = sorted(n for n in names if re.search(r"\b%s\b" % re.escape(n), code))
    line = "".join(f"import cim_neurohdc_pkg::{n};\n" for n in used) + ("\n" if used else "")
    # insert before the first `ifdef SYNTHESIS (cim_macro) or the first `module`
    m = re.search(r"^(`ifdef SYNTHESIS\n\(\* blackbox \*\)\n|module )", body, flags=re.M)
    new = body[:m.start()] + line + body[m.start():]
    if new != s:
        f.write_text(new)
        print("updated", f.name, len(used), "symbols")
