"""ngspice harness for 1F: decks with the PTM 45 nm LP n/p models, batch runs, wrdata parsing, .noise spectra. Transistor-level only (no behavioural stand-ins for noise)."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
PTM_N = HERE / "device" / "ptm" / "ptm45n_lp.lib"       # NMOS block of the PTM 45 nm LP card (1A)
PTM_P = HERE / "device" / "ptm" / "ptm45p_lp.lib"       # PMOS block of the same card file (added in 1F)
OPTIONS = ".options reltol=1e-6 abstol=1e-13 vntol=1e-9 gmin=1e-15 itl1=300 itl4=100 method=gear"
VDD = 1.1                                               # V, PTM 45 nm LP nominal supply (same as V_WL in 1A)


def header(title: str, temp: float = 27.0, options: str = OPTIONS) -> list[str]:
    return [title, options, f".include {PTM_N}", f".include {PTM_P}", f".temp {temp}"]


def f(x: float) -> str:
    return f"{x:.9g}"


def run(deck: str, timeout: float = 600.0) -> str:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "d.cir"
        p.write_text(deck)
        r = subprocess.run(["ngspice", "-b", str(p)], capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def scalars(out: str) -> dict[str, float]:
    d = {}
    for ln in out.splitlines():
        m = re.match(r"^\s*([A-Za-z_@][\w\.\[\]\(\),@-]*)\s*=\s*([-+0-9.eE]+)\s*$", ln)
        if m:
            d[m.group(1).lower()] = float(m.group(2))
    return d


def run_wrdata(deck_body: list[str], vectors: list[str], plot_cmd: str = "", timeout: float = 600.0) -> dict[str, np.ndarray]:
    """deck_body: lines up to (not including) '.end'; a .control block is appended that runs and writes `vectors` (single scale) to a temp file."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.dat"
        deck = "\n".join(deck_body + [".control", "set noaskquit", "set wr_singlescale", "set wr_vecnames", "set numdgt=12", "run", plot_cmd,
                                       f"wrdata {out} {' '.join(vectors)}", ".endc", ".end"]) + "\n"
        p = Path(td) / "d.cir"
        p.write_text(deck)
        r = subprocess.run(["ngspice", "-b", str(p)], capture_output=True, text=True, timeout=timeout)
        if not out.exists():
            raise RuntimeError("ngspice produced no data:\n" + (r.stdout + r.stderr)[-2000:])
        lines = out.read_text().splitlines()
    hdr = lines[0].split()
    data = np.array([[float(x) for x in ln.split()] for ln in lines[1:] if ln.strip()])
    return {h.lower(): data[:, i] for i, h in enumerate(hdr)}
