#!/usr/bin/env python3
"""D2(a) / D5: NeuroSim area and read energy of ONE macro of this design (512 rows x 32 weight columns, 2T2R differential = 64 physical columns, 45 nm, g = 4, T = 1 ns), at
  A  the cell 1A-1C assumed          : 20 F^2 (5 F x 4 F). NeuroSim REFUSES it: its own transistor model needs a 39.8 F wide select transistor for a 541.8 ohm LRS
                                       (access resistance = Ron x IR_DROP_TOLERANCE in NeuroSim, so the width follows from Ron, not from a number we pass in) - recorded as infeasible
  A2 the smallest cell NeuroSim accepts: 40 F wide x 4 F high (160 F^2)
  B  the cell the write path needs   : 128 F wide x 4 F high (512 F^2; 1D: a 541.8 ohm LRS needs a ~128 F select transistor for the SET current)
  C  B at NeuroSim's own '45 nm' feature size (its 45 nm node uses an 80 nm wire width / F)       [reference only]
NeuroSim (DNN_NeuroSim_V1.4, CC BY-NC 4.0) is cloned and built OUTSIDE the repository (--work); nothing of it is copied here. Its Param.cpp defaults are patched in the build copy only:
technode 45, RRAM, HP roadmap, 1T1R cell width. Everything else goes through ns_driver.cpp (this directory). Writes design/rtl/synth/results/neurosim.json.

  python design/rtl/synth/neurosim/run_neurosim.py [--work ~/.cache/cim_neurohdc/neurosim]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "results" / "neurosim.json"
REPO_URL = "https://github.com/neurosim/DNN_NeuroSim_V1.4"
RON, ROFF = 541.8, 218586.0                      # constants.py: GAP_LRS / GAP_HRS at 0.1 V
RTX_PER_UM = 546.3                               # ohm.um, constants.py R_TX x TX_W_UM at 40 F^2
VARIANTS = {
    "A_20F2": dict(w=5, h=4, F=45, racc=1016.0459, label="1T1R 20 F^2 (1A-1C's assumption), F = 45 nm"),
    "A2_40F": dict(w=40, h=4, F=45, racc=0.0, label="smallest cell NeuroSim accepts at Ron = 541.8 ohm: 40 F x 4 F = 160 F^2, F = 45 nm"),
    "B_128F": dict(w=128, h=4, F=45, racc=RTX_PER_UM / (128 * 0.045), label="1T1R 128 F wide (select transistor the write path needs), F = 45 nm"),
    "C_128F_F80": dict(w=128, h=4, F=80, racc=RTX_PER_UM / (128 * 0.080), label="as B at NeuroSim's own 45 nm node feature size (80 nm) - reference only"),
}
GEOM = dict(rows=512, cols=64, g=4, pulse_ns=1.0, mux=8, levels=8)


def sh(cmd, cwd=None, check=True):
    cmd = [str(c) for c in cmd]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"failed: {' '.join(map(str, cmd))}\n{(r.stdout + r.stderr)[-1500:]}")
    return r


def build(work: Path) -> Path:
    src, bld = work / "src", work / "build"
    if not src.exists():
        sh(["git", "clone", "--depth", "1", REPO_URL, str(src)])
    ns = src / "Inference_pytorch" / "NeuroSIM"
    bld.mkdir(parents=True, exist_ok=True)
    for f in list(ns.glob("*.cpp")) + list(ns.glob("*.h")):
        (bld / f.name).write_bytes(f.read_bytes())
    (bld / "ns_driver.cpp").write_bytes((HERE / "ns_driver.cpp").read_bytes())
    orig = (ns / "Param.cpp").read_text()
    (bld / "Param.orig.cpp").write_text(orig)
    srcs = [p for p in sorted(bld.glob("*.cpp")) if p.name not in ("main.cpp", "Param.cpp", "Param.orig.cpp")]

    def cc(p: Path):
        o = p.with_suffix(".o")
        if not o.exists() or o.stat().st_mtime < p.stat().st_mtime:
            sh(["g++", "-c", "-O2", "-std=c++11", "-w", "-Wno-parentheses", str(p), "-o", str(o)])
        return o

    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        list(ex.map(cc, srcs))
    return bld


def run_variant(bld: Path, tag: str, v: dict) -> dict:
    t = (bld / "Param.orig.cpp").read_text()
    for a, b in ((r"\bmemcelltype = 1;", "memcelltype = 2;"), (r"\bdeviceroadmap = 2;", "deviceroadmap = 1;"), (r"\btechnode = 22;", "technode = 45;"),
                 (r"\bwidthInFeatureSize1T1R = 12;", f"widthInFeatureSize1T1R = {v['w']};"), (r"\bheightInFeatureSize1T1R = 4;", f"heightInFeatureSize1T1R = {v['h']};"),
                 (r"\bwriteVoltage = 2;", "writeVoltage = 1.2;")):
        t, n = re.subn(a, b, t, count=1)
        assert n == 1, a
    (bld / f"Param_{tag}.cpp").write_text(t)
    sh(["g++", "-c", "-O2", "-std=c++11", "-w", str(bld / f"Param_{tag}.cpp"), "-o", str(bld / f"Param_{tag}.o")])
    objs = [str(o) for o in sorted(bld.glob("*.o")) if o.name not in ("main.o", "Param.o") and not o.name.startswith("Param_")] + [str(bld / f"Param_{tag}.o")]
    sh(["g++", "-O2", *objs, "-o", str(bld / f"ns_driver_{tag}")])
    g = GEOM
    r = sh([str(bld / f"ns_driver_{tag}"), g["rows"], g["cols"], g["g"], v["F"], g["pulse_ns"], RON, ROFF, v["racc"], g["mux"], g["levels"]], check=False)
    if r.returncode != 0 or "area_total_um2" not in r.stdout:
        return dict(tag=tag, label=v["label"], cell_w_F=v["w"], cell_h_F=v["h"], F_nm=v["F"], feasible=False, message=(r.stdout + r.stderr).strip())
    d: dict = dict(tag=tag, feasible=True, label=v["label"], cell_w_F=v["w"], cell_h_F=v["h"], F_nm=v["F"], raw=r.stdout)
    pair = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\s+(-?[0-9]+\.?[0-9]*(?:[eE][-+]?[0-9]+)?)")
    for line in r.stdout.splitlines():
        kv = {k: float(x) for k, x in pair.findall(line)}
        if line.startswith("area_total_um2"):
            d["area_macro_um2"] = kv["area_total_um2"]
        elif line.startswith("height_um"):
            d["height_um"], d["width_um"] = kv["height_um"], kv["width_um"]
        elif line.startswith("area_array_um2"):
            d["area_array_um2"] = kv["area_array_um2"]
        elif line.startswith("area_ADC_um2"):
            d["area_ADC_um2"], d["area_accum_um2"], d["area_other_um2"] = kv["area_ADC_um2"], kv["area_accum_um2"], kv["area_other_um2"]
        elif line.startswith("area_modules_um2"):
            d["area_modules_um2"] = {k: x for k, x in kv.items() if k != "area_modules_um2"}
        elif line.startswith("read_energy_pJ"):
            d["read_energy_pJ"] = dict(total=kv["read_energy_pJ"], array=kv["array"], adc=kv["ADC"], accum=kv["accum"], other=kv["other"])
        elif line.startswith("leakage_uW"):
            d["leakage_uW"] = kv["leakage_uW"]
        elif line.startswith("cap_row_fF"):
            d["cap_row_fF"], d["cap_col_fF"], d["res_row_ohm"], d["res_col_ohm"] = kv["cap_row_fF"], kv["cap_col_fF"], kv["res_row_ohm"], kv["res_col_ohm"]
        elif line.startswith("read_latency_ns"):
            d["read_latency_ns_NOT_USED"] = kv["read_latency_ns"]
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(Path.home() / ".cache" / "cim_neurohdc" / "neurosim"))
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    bld = build(work)
    res = dict(geometry=GEOM, Ron=RON, Roff=ROFF, source=REPO_URL, variants={t: run_variant(bld, t, v) for t, v in VARIANTS.items()})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    for t, d in res["variants"].items():
        if not d.get("feasible"):
            print(f"{t:12s} INFEASIBLE in NeuroSim: {d['message']}")
            continue
        print(f"{t:12s} macro {d['area_macro_um2']:>10,.0f} um^2 (array {d['area_array_um2']:>9,.0f})  x5 = {5 * d['area_macro_um2'] * 1e-6:.3f} mm^2   read {d['read_energy_pJ']['total']:.1f} pJ/macro "
              f"(array {d['read_energy_pJ']['array']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
