#!/usr/bin/env python3
"""Clock-gate profile of a laid-out netlist: for every clock-gating cell, how many flops it clocks (through the clock buffers the layout inserted), how often its gated clock runs in a
SAIF window (toggle count of the gated clock / 2 / cycles) and the summed power of those flops (instance report of the same window, from power_prof.py). Flops that hang on a clock
with no gate of their own are listed per clock root. Needs `power_prof.py` to have run on the tag (an/<name>.saif, an/inst_<name>_fast.rpt).
  python opt/icg_prof.py --tag p5 --name prof1 [--stage groute] [--cycles 4000]"""
import argparse, collections, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True); ap.add_argument("--name", default="prof1"); ap.add_argument("--stage", default="groute"); ap.add_argument("--cycles", type=int, default=4000)
ap.add_argument("--top", type=int, default=60)
a = ap.parse_args()
run = HERE.parent / "work" / "opt" / a.tag
txt = (run / f"{a.stage}.v").read_text()
inst = {}
for m in re.finditer(r"^\s*([A-Za-z]\w*)\s+(\\\S+\s|\w+)\s*\((.*?)\);", txt, re.M | re.S):
    cell, name, body = m.group(1), m.group(2).strip().lstrip("\\"), m.group(3)
    if cell in ("module", "input", "output", "wire", "assign"):
        continue
    pins = {p: n.strip().lstrip("\\").replace(" ", "") for p, n in re.findall(r"\.(\w+)\(\s*([^)]*?)\s*\)", body)}
    inst[name] = (cell, pins)
sinks = collections.defaultdict(list)
for n, (c, p) in inst.items():
    for pin, net in p.items():
        if pin in ("CK", "A", "CLK", "clk_i"):
            sinks[net].append((n, pin))
tc = {}
for m in re.finditer(r"^\((\S+) \(T0 \d+\) \(T1 \d+\) \(TX \d+\) \(TC (\d+)\)", (run / "an" / f"{a.name}.saif").read_text(), re.M):
    tc[m.group(1).replace("\\", "")] = int(m.group(2))
pw = {}
for l in open(run / "an" / f"inst_{a.name}_fast.rpt"):
    f = l.split()
    if len(f) == 5 and re.match(r"[\d.e+-]+$", f[3]):
        pw[f[4].replace("\\", "")] = float(f[3]) * 1e6


def is_ckbuf(c):
    return c.startswith(("CLKBUF", "CLKINV", "BUF", "INV"))


def fan(net, seen=None):
    """flops, clock buffers and gates below a clock net (stops at clock gates)"""
    fl, bufs, gates = [], [], []
    stack = [net]
    while stack:
        x = stack.pop()
        for n, pin in sinks.get(x, ()):
            c, p = inst[n]
            if c.startswith("TLATNCA") and pin == "CK":
                gates.append(n)
            elif is_ckbuf(c) and pin == "A":
                bufs.append(n); stack.append(p.get("Y", "?"))
            elif pin in ("CK", "CLK", "clk_i"):
                fl.append(n)
    return fl, bufs, gates


rows = []
def visit(net, label, depth):
    fl, bufs, gates = fan(net)
    duty = tc.get(net, 0) / 2 / a.cycles
    rows.append((depth, label, len(fl), duty, sum(pw.get(x, 0) for x in fl), sum(pw.get(x, 0) for x in bufs), net))
    for g in gates:
        visit(inst[g][1]["ECK"], g, depth + 1)
visit("clk_i", "clk_i (root)", 0)
print(f"{'gate':70s} {'flops':>6s} {'duty':>6s} {'flop uW':>8s} {'ckbuf uW':>8s}")
for d, lab, n, duty, p, pb, net in rows:
    if n or pb > 0.5:
        print(f"{'  ' * d + lab:70.70s} {n:6d} {duty:6.2f} {p:8.1f} {pb:8.1f}")
