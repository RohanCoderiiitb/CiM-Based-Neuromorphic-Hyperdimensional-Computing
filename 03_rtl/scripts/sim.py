"""Build and run the SV regression testbench under Verilator or Icarus. Builds are cached in build/ keyed by the design parameters."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
RTL = [ROOT / "rtl/pkg/cim_neurohdc_pkg.sv"] + sorted((ROOT / "rtl/phase1_snn").glob("*.sv"))
TB = ROOT / "tb/sv/snn_regress_tb.sv"
TOP = "snn_regress_tb"


def _src_hash() -> str:
    h = hashlib.sha1()
    for f in RTL + [TB]:
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


def tool_versions() -> dict:
    out = {}
    for name, cmd in (("verilator", ["verilator", "--version"]), ("iverilog", ["iverilog", "-V"]), ("yosys", ["yosys", "-V"])):
        try:
            out[name] = subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines()[0].strip()
        except Exception:  # noqa: BLE001
            out[name] = "unavailable"
    return out


def build(sim: str, g: int = 8, cols: int = 160, skip: int = 1) -> Path:
    tag = f"{sim}_g{g}_c{cols}_s{skip}_{_src_hash()}"
    d = BUILD / tag
    if sim == "verilator":
        exe = d / "obj" / f"V{TOP}"
        if exe.exists():
            return exe
        d.mkdir(parents=True, exist_ok=True)
        cmd = ["verilator", "--binary", "--timing", "-sv", "-O3", "--Mdir", str(d / "obj"), "--top-module", TOP,
               f"-GROWS_PER_GROUP_P={g}", f"-GN_PARALLEL_COLS_P={cols}", f"-GPLANE_SKIP_EN_P={skip}",
               "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-TIMESCALEMOD", "-Wno-WIDTH", "-Wno-STMTDLY", "-Wno-INITIALDLY", "-Wno-BLKSEQ",
               "-j", "0", *map(str, RTL), str(TB)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            raise RuntimeError("verilator build failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
        return exe
    if sim == "icarus":
        exe = d / "snn.vvp"
        if exe.exists():
            return exe
        d.mkdir(parents=True, exist_ok=True)
        cmd = ["iverilog", "-g2012", "-o", str(exe), "-s", TOP, f"-P{TOP}.ROWS_PER_GROUP_P={g}", f"-P{TOP}.N_PARALLEL_COLS_P={cols}",
               f"-P{TOP}.PLANE_SKIP_EN_P={skip}", *map(str, RTL), str(TB)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            raise RuntimeError("iverilog build failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
        return exe
    raise ValueError(sim)


def run(sim: str, exe: Path, job_dir: Path, out: Path) -> dict:
    t0 = time.time()
    if sim == "verilator":
        cmd = [str(exe), f"+job={job_dir}", f"+out={out}"]
    else:
        cmd = ["vvp", "-n", str(exe), f"+job={job_dir}", f"+out={out}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log = r.stdout + r.stderr
    return dict(returncode=r.returncode, wall_s=time.time() - t0, log=log, assert_fails=log.count("[ASSERT FAIL]"), fatal="FATAL" in log)
