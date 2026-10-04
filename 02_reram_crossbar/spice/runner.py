"""Run ngspice in batch mode and parse node voltages. Numbers in, numbers out."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from device.constants import DEFAULT, Params
from spice.netlist import build_deck

_LINE = re.compile(r"^\s*v\(bl(\d+)\)\s*=\s*([-+0-9.eE]+)\s*$")


class SpiceError(RuntimeError):
    pass


def ngspice_available() -> bool:
    return shutil.which("ngspice") is not None


MAX_BSIM_BRANCHES_PER_DECK = 600   # BSIM4 decks slow down superlinearly past this (observed); split into chunks


def run_columns(gaps, active, p: Params = DEFAULT, r_s=None, r_tx=None, timeout: float = 600.0,
                tx: str = "linear", temp: float = 27.0) -> np.ndarray:
    if tx == "bsim":
        act = np.asarray(active, dtype=bool)
        per = max(1, MAX_BSIM_BRANCHES_PER_DECK // max(1, int(act.sum(axis=1).max())))
        if act.shape[0] > per:
            gaps = np.asarray(gaps, dtype=float)
            rs = np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), (act.shape[0],))
            return np.concatenate([
                run_columns(gaps[i:i + per], act[i:i + per], p, rs[i:i + per], r_tx, timeout, tx, temp)
                for i in range(0, act.shape[0], per)])
    return _run_columns(gaps, active, p, r_s, r_tx, timeout, tx, temp)


def _run_columns(gaps, active, p: Params = DEFAULT, r_s=None, r_tx=None, timeout: float = 600.0,
                 tx: str = "linear", temp: float = 27.0) -> np.ndarray:
    """Solve a batch of independent columns in ONE ngspice process. Returns column currents (A), shape (ncol,).

    Current is the sense-resistor current V(bl)/R_s.
    """
    gaps = np.asarray(gaps, dtype=float)
    ncol = gaps.shape[0]
    rs = np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), (ncol,))
    deck, _ = build_deck(gaps, active, p, r_s, r_tx, tx=tx, temp=temp)
    with tempfile.TemporaryDirectory() as td:
        cir = Path(td) / "deck.cir"
        cir.write_text(deck)
        proc = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True, timeout=timeout)
    out = proc.stdout + proc.stderr
    volts = np.full(ncol, np.nan)
    for line in out.splitlines():
        m = _LINE.match(line)
        if m:
            volts[int(m.group(1))] = float(m.group(2))
    if np.isnan(volts).any():
        tail = "\n".join(out.splitlines()[-15:])
        raise SpiceError(f"ngspice produced no value for {int(np.isnan(volts).sum())}/{ncol} columns "
                         f"(rc={proc.returncode}); tail:\n{tail}")
    if re.search(r"singular matrix|no convergence|Timestep too small|doAnalyses: .*failed", out, re.I):
        raise SpiceError("ngspice reported a convergence problem:\n" + "\n".join(out.splitlines()[-15:]))
    return volts / rs


def run_differential(gaps_plus, gaps_minus, active, p: Params = DEFAULT, r_s=None, r_tx=None,
                     tx: str = "linear", temp: float = 27.0):
    """One 2T2R group per row of the inputs (ncase, n). Returns (i_plus, i_minus, i_diff)."""
    gp = np.asarray(gaps_plus, dtype=float)
    ncase = gp.shape[0]
    act = np.asarray(active, dtype=bool)
    cols = run_columns(np.vstack([gp, np.asarray(gaps_minus, dtype=float)]), np.vstack([act, act]), p,
                       None if r_s is None else np.resize(r_s, 2 * ncase),
                       None if r_tx is None else np.resize(r_tx, 2 * ncase), tx=tx, temp=temp)
    ip, im = cols[:ncase], cols[ncase:]
    return ip, im, ip - im


_PRINT = re.compile(r"^\s*(\S+)\s*=\s*([-+0-9.eE]+)\s*$")


def run_deck_prints(deck: str, timeout: float = 600.0) -> dict[str, float]:
    """Run an arbitrary deck whose .control block prints scalars; return {name: value}."""
    with tempfile.TemporaryDirectory() as td:
        cir = Path(td) / "deck.cir"
        cir.write_text(deck)
        proc = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True, timeout=timeout)
    out = proc.stdout + proc.stderr
    vals = {}
    for line in out.splitlines():
        m = _PRINT.match(line)
        if m:
            try:
                vals[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    if not vals:
        raise SpiceError("ngspice returned no printed values; tail:\n" + "\n".join(out.splitlines()[-15:]))
    return vals
