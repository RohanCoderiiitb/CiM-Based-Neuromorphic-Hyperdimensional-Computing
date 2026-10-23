"""Build and run the Phase 2-4 SV regression testbench (hdc_regress_tb) under Verilator or Icarus. Builds are cached in build/ keyed by the design parameters and the source hash."""
from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
RTL = ([ROOT / "rtl/pkg/cim_neurohdc_pkg.sv", ROOT / "rtl/pkg/hdc_pkg.sv"] + sorted((ROOT / "rtl/phase1_snn").glob("*.sv")) + sorted((ROOT / "rtl/phase2_hdc").glob("*.sv"))
       + sorted((ROOT / "rtl/phase4_exit").glob("*.sv")) + sorted((ROOT / "rtl/phase3_top").glob("*.sv")))
TB = ROOT / "tb/sv/hdc_regress_tb.sv"
TOP = "hdc_regress_tb"


def _src_hash() -> str:
    h = hashlib.sha1()
    for f in RTL + [TB]:
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


def build(sim: str, factorized: int = 1, early_exit: int = 1, g: int = 8, cols: int = 160, skip: int = 1, instr: int = 1, vcd: bool = False) -> Path:
    tag = f"{sim}_f{factorized}_e{early_exit}_g{g}_c{cols}_s{skip}_i{instr}{'_vcd' if vcd else ''}_{_src_hash()}"
    d = BUILD / "hdc" / tag
    params = dict(ROWS_PER_GROUP_P=g, N_PARALLEL_COLS_P=cols, PLANE_SKIP_EN_P=skip, INSTRUMENT_EN_P=instr, FACTORIZED_P=factorized, EARLY_EXIT_EN_P=early_exit)
    if sim == "verilator":
        exe = d / "obj" / f"V{TOP}"
        if exe.exists():
            return exe
        d.mkdir(parents=True, exist_ok=True)
        cmd = ["verilator", "--binary", "--timing", "-sv", "-O3", "--Mdir", str(d / "obj"), "--top-module", TOP, *[f"-G{k}={v}" for k, v in params.items()],
               "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-TIMESCALEMOD", "-Wno-WIDTH", "-Wno-STMTDLY", "-Wno-INITIALDLY", "-Wno-BLKSEQ", "-j", "0", *map(str, RTL), str(TB)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            raise RuntimeError("verilator build failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
        return exe
    if sim == "icarus":
        exe = d / "hdc.vvp"
        if exe.exists():
            return exe
        d.mkdir(parents=True, exist_ok=True)
        cmd = ["iverilog", "-g2012", *(["-DVCD_DUMP"] if vcd else []), "-o", str(exe), "-s", TOP, *[f"-P{TOP}.{k}={v}" for k, v in params.items()], *map(str, RTL), str(TB)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            raise RuntimeError("iverilog build failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
        return exe
    raise ValueError(sim)


def tool_versions() -> dict:
    out = {}
    for name, cmd in (("verilator", ["verilator", "--version"]), ("iverilog", ["iverilog", "-V"]), ("yosys", ["yosys", "-V"])):
        try:
            out[name] = subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines()[0].strip()
        except Exception:  # noqa: BLE001
            out[name] = "unavailable"
    return out


def run(sim: str, exe: Path, job_dir: Path, out: Path, extra: list[str] | None = None) -> dict:
    t0 = time.time()
    extra = extra or []
    cmd = [str(exe), f"+job={job_dir}", f"+out={out}", *extra] if sim == "verilator" else ["vvp", "-n", str(exe), f"+job={job_dir}", f"+out={out}", *extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log = r.stdout + r.stderr
    return dict(returncode=r.returncode, wall_s=time.time() - t0, log=log, assert_fails=log.count("[ASSERT FAIL]"), fatal="FATAL" in log)
