"""1D: the compiled compact model. Builds spice/rram.va with OpenVAF into an OSDI module and runs ngspice decks that load it.

Toolchain (Linux only: OpenVAF does not build on macOS):
  - ngspice >= 38 is required (older builds cannot load OSDI modules, and fail with an unhelpful 'unknown device' message). Checked by `check_ngspice()`.
  - OpenVAF-reloaded (`openvaf-r`) or OpenVAF (`openvaf`). If neither is on PATH the binaries are resolved once through `nix-shell -p openvaf ngspice` and cached
    in spice/build/tools.json, so a plain `python -m ...` works on a machine that has nix but no global install.
  - ngspice from nix hard-sets num_threads; every deck run here injects `pre_set num_threads=1` (the harness parallelises over processes instead).
The compiled module lives in spice/build/ (git-ignored) and is rebuilt when rram.va or smoothfunctions.va is newer than it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
VA = HERE / "rram.va"
VA_INCLUDE = HERE / "smoothfunctions.va"
BUILD = HERE / "build"
OSDI = BUILD / "rram.osdi"
TOOLS_JSON = BUILD / "tools.json"
MIN_NGSPICE = 38


class ToolchainError(RuntimeError):
    pass


def _nix_resolve() -> dict:
    if shutil.which("nix-shell") is None:
        raise ToolchainError("neither ngspice/openvaf on PATH nor nix-shell available: install ngspice >= 38 and OpenVAF")
    cmd = 'echo NGSPICE=$(readlink -f $(which ngspice)); echo OPENVAF=$(readlink -f $(which openvaf-r || which openvaf))'
    r = subprocess.run(["nix-shell", "-p", "openvaf", "ngspice", "--run", cmd], capture_output=True, text=True, timeout=1800, cwd="/tmp")
    out = dict(ln.split("=", 1) for ln in r.stdout.splitlines() if "=" in ln)
    if not out.get("NGSPICE") or not out.get("OPENVAF"):
        raise ToolchainError("nix-shell could not provide ngspice/openvaf:\n" + r.stderr[-2000:])
    return dict(ngspice=out["NGSPICE"], openvaf=out["OPENVAF"])


@lru_cache(maxsize=None)
def tools() -> dict:
    ng, va = shutil.which("ngspice"), shutil.which("openvaf-r") or shutil.which("openvaf")
    if ng and va:
        return dict(ngspice=ng, openvaf=va)
    if TOOLS_JSON.exists():
        t = json.loads(TOOLS_JSON.read_text())
        if Path(t["ngspice"]).exists() and Path(t["openvaf"]).exists():
            return t
    t = _nix_resolve()
    BUILD.mkdir(parents=True, exist_ok=True)
    TOOLS_JSON.write_text(json.dumps(t, indent=1))
    return t


def put_ngspice_on_path() -> None:
    """Earlier phases call `ngspice` by name; make the resolved binary visible to them in this process."""
    d = str(Path(tools()["ngspice"]).parent)
    if d not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


@lru_cache(maxsize=None)
def check_ngspice() -> dict:
    r = subprocess.run([tools()["ngspice"], "--version"], capture_output=True, text=True, timeout=60)
    m = re.search(r"ngspice-(\d+)", r.stdout + r.stderr)
    ver = int(m.group(1)) if m else -1
    if ver < MIN_NGSPICE:
        raise ToolchainError(f"ngspice version {ver} < {MIN_NGSPICE}: cannot load OSDI modules")
    return dict(version=ver, path=tools()["ngspice"])


def build_osdi(force: bool = False) -> Path:
    """Compile rram.va -> build/rram.osdi (rebuild if a source is newer). Returns the module path."""
    BUILD.mkdir(parents=True, exist_ok=True)
    newest = max(VA.stat().st_mtime, VA_INCLUDE.stat().st_mtime)
    if force or not OSDI.exists() or OSDI.stat().st_mtime < newest:
        r = subprocess.run([tools()["openvaf"], str(VA), "-o", str(OSDI)], capture_output=True, text=True, timeout=600, cwd=str(HERE))
        if r.returncode != 0 or not OSDI.exists():
            raise ToolchainError("OpenVAF failed:\n" + (r.stdout + r.stderr)[-3000:])
    return OSDI


def compile_source(va_text: str) -> tuple[int, str]:
    """Compile an arbitrary variant of the model text (used to show the original declaration bug fails). Returns (returncode, compiler output)."""
    with tempfile.TemporaryDirectory() as td:
        shutil.copy(VA_INCLUDE, Path(td) / VA_INCLUDE.name)
        src = Path(td) / "variant.va"
        src.write_text(va_text)
        r = subprocess.run([tools()["openvaf"], str(src), "-o", str(Path(td) / "v.osdi")], capture_output=True, text=True, timeout=600, cwd=td)
        return r.returncode, (r.stdout + r.stderr).replace(td, "<tmp>")


def control_preamble(osdi: Path | None = None) -> list[str]:
    return ["pre_set num_threads=1", f"pre_osdi {osdi or build_osdi()}"]


def run(deck: str, timeout: float = 3600.0) -> str:
    """Run a complete deck (must contain its own .control block, whose first lines should be control_preamble()). Returns stdout+stderr."""
    check_ngspice()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "d.cir"
        p.write_text(deck)
        r = subprocess.run([tools()["ngspice"], "-b", str(p)], capture_output=True, text=True, timeout=timeout, cwd=td)
    return r.stdout + r.stderr


_SCALAR = re.compile(r"^\s*([A-Za-z_@][\w\.\[\]\(\),@:-]*)\s*=\s*([-+0-9.eE]+)(?:\s+(?:at|from|to)=.*)?\s*$")


def scalars(out: str) -> dict[str, float]:
    d = {}
    for ln in out.splitlines():
        m = _SCALAR.match(ln)
        if m:
            try:
                d[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    return d


def run_wrdata(body: list[str], vectors: list[str], commands: list[str] | None = None, timeout: float = 3600.0) -> dict:
    """body: netlist lines (no .control, no .end). Runs the analysis given in `commands` (default: 'run') and writes `vectors` with wrdata.
    Returns {vector: array} (single scale)."""
    import numpy as np
    check_ngspice()
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.dat"
        ctl = [".control", *control_preamble(), "set noaskquit", "set wr_singlescale", "set wr_vecnames", "set numdgt=15",
               *(commands or ["run"]), f"wrdata {out} {' '.join(vectors)}", ".endc", ".end"]
        p = Path(td) / "d.cir"
        p.write_text("\n".join(body + ctl) + "\n")
        r = subprocess.run([tools()["ngspice"], "-b", str(p)], capture_output=True, text=True, timeout=timeout, cwd=td)
        if not out.exists():
            raise ToolchainError("ngspice produced no data:\n" + (r.stdout + r.stderr)[-3000:])
        lines = out.read_text().splitlines()
    hdr = lines[0].split()
    data = np.array([[float(x) for x in ln.split()] for ln in lines[1:] if ln.strip()])
    return {h.lower(): data[:, i] for i, h in enumerate(hdr)}
