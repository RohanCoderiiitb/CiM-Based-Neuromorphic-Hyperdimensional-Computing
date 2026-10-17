"""Small-signal (AC) and noise analysis helpers: input impedance and the input-referred current noise spectrum referred to the sense node, with per-device attribution (ngspice .noise, BSIM4 thermal + 1/f
+ gate/bulk resistance noise)."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np


def _run(lines: list[str], timeout: float = 600.0) -> str:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "d.cir"
        p.write_text("\n".join(lines) + "\n")
        r = subprocess.run(["ngspice", "-b", str(p)], capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def noise_spectrum(deck: list[str], out: str, src: str, fmin: float = 1e5, fmax: float = 5e10, pts_dec: int = 10, timeout: float = 600.0) -> dict:
    """deck: netlist lines (no .end). out: output node name; src: AC source (current) at the sense node whose value is 1 A. Returns f, inoise PSD (A^2/Hz) and the per-device contribution table (A^2/Hz integrated
    over [fmin, fmax] by ngspice) plus the transfer magnitude."""
    with tempfile.TemporaryDirectory() as td:
        dat = Path(td) / "n.dat"
        lines = deck + [f".noise v({out}) {src} dec {pts_dec} {fmin:g} {fmax:g} 1", ".control", "set noaskquit", "set wr_singlescale", "set wr_vecnames", "run",
                        "setplot noise1", f"wrdata {dat} inoise_spectrum onoise_spectrum", "setplot noise2", "print all", ".endc", ".end"]
        p = Path(td) / "d.cir"
        p.write_text("\n".join(lines) + "\n")
        r = subprocess.run(["ngspice", "-b", str(p)], capture_output=True, text=True, timeout=timeout)
        txt = r.stdout + r.stderr
        if not dat.exists():
            raise RuntimeError("noise run produced no data:\n" + txt[-1500:])
        rows = [ln.split() for ln in dat.read_text().splitlines()[1:] if ln.strip()]
    arr = np.array([[float(x) for x in r_] for r_ in rows])
    f, inoise, onoise = arr[:, 0], arr[:, 1], arr[:, 3] if arr.shape[1] > 3 else arr[:, 2]
    contrib = {}
    for ln in txt.splitlines():
        m = re.match(r"^\s*(inoise_total\.[\w\.\[\]]+)\s*=\s*([-+0-9.eE]+)\s*$", ln)
        if m:
            contrib[m.group(1)] = float(m.group(2))
    return dict(f=f, s_in=inoise ** 2, s_out=onoise ** 2, contrib=contrib, raw=txt)
