"""Transistor-level building blocks (PTM 45 nm LP n/p, L in metres): sizes are arguments so F2(b) can sweep them."""
from __future__ import annotations

from sense.ngs import f

NM, PM = "ptm45n_lp", "ptm45p_lp"


def ota_p(name: str = "ota", wi: float = 8e-6, li: float = 90e-9, wt: float = 8e-6, lt: float = 90e-9, wm: float = 4e-6, lm: float = 180e-9) -> list[str]:
    """PMOS-input single-stage OTA (5T): ports inp inn out vdd vb  (vb = tail gate bias). Output rises with inp. PMOS pair so the inputs can sit at ~0 V (the virtual ground of the array)."""
    return [f".subckt {name} inp inn out vdd vb",
            f"Mt nt vb vdd vdd {PM} W={f(wt)} L={f(lt)}",
            f"M1 n1 inp nt vdd {PM} W={f(wi)} L={f(li)}",
            f"M2 out inn nt vdd {PM} W={f(wi)} L={f(li)}",
            f"M3 n1 n1 0 0 {NM} W={f(wm)} L={f(lm)}",
            f"M4 out n1 0 0 {NM} W={f(wm)} L={f(lm)}",
            ".ends"]


def tgate(name: str, a: str, b: str, ph: str, phb: str, w: float = 1e-6, l: float = 45e-9) -> list[str]:
    """Transmission gate between a and b (n and p passgate in parallel); clock ph high = closed."""
    return [f"M{name}n {a} {ph} {b} 0 {NM} W={f(w)} L={f(l)}", f"M{name}p {a} {phb} {b} vdd {PM} W={f(2 * w)} L={f(l)}"]


def ota2s(name: str = "ota2s", wi: float = 16e-6, li: float = 90e-9, wt: float = 16e-6, lt: float = 90e-9, wm: float = 8e-6, lm: float = 180e-9, w5: float = 16e-6, l5: float = 90e-9,
          w6: float = 32e-6, l6: float = 180e-9, cc: float = 100e-15, rc: float = 0.0, dv: dict | None = None) -> list[str]:
    """Two-stage Miller OTA (PMOS-input first stage as ota_p, NMOS common-source second stage M5 with PMOS current-source load M6): ports inp inn out vdd vb vbp. Output FALLS when inp rises (inverting
    second stage), so use inp = the node to be held, inn = the reference: negative feedback from `out` to inp. dv: optional delvto (V) per device name M1..M6/Mt."""
    dv = dv or {}
    g = lambda n: f" delvto={dv.get(n, 0.0):.6g}" if n in dv else ""
    L = [f".subckt {name} inp inn out vdd vb vbp",
         f"Mt nt vb vdd vdd {PM} W={f(wt)} L={f(lt)}",
         f"M1 n1 inp nt vdd {PM} W={f(wi)} L={f(li)}" + g("M1"), f"M2 n2 inn nt vdd {PM} W={f(wi)} L={f(li)}" + g("M2"),
         f"M3 n1 n1 0 0 {NM} W={f(wm)} L={f(lm)}" + g("M3"), f"M4 n2 n1 0 0 {NM} W={f(wm)} L={f(lm)}" + g("M4"),
         f"M5 out n2 0 0 {NM} W={f(w5)} L={f(l5)}", f"M6 out vbp vdd vdd {PM} W={f(w6)} L={f(l6)}"]
    L += [f"Cc n2 ccm {f(cc)}", f"Rc ccm out {max(rc, 1e-3)}"]
    return L + [".ends"]
