#!/usr/bin/env python3
"""Which signals do the layout's repair / port / hold buffers drive? Needs a `--hier-names` layout and an instance power report of power_prof.py (an/inst_<name>_fast.rpt).
Every buffer the layout inserted is traced back to the net it repeats (its root driver) and forward to the modules it finally feeds; the buffer powers are summed per root net.
  python opt/buf_trace.py --tag p3 --name prof1 [--top 30]"""
import argparse, collections, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True); ap.add_argument("--name", default="prof1"); ap.add_argument("--stage", default="groute"); ap.add_argument("--top", type=int, default=30)
a = ap.parse_args()
run = HERE.parent / "work" / "opt" / a.tag
t = re.sub(r"/\*.*?\*/", "", (run / f"{a.stage}.v").read_text(), flags=re.S)
cells = {}
for m in re.finditer(r"\n\s*([A-Za-z]\w*)\s+(\\?\S+)\s*\((.*?)\);", t, re.S):
    typ, name, body = m.groups()
    if typ in ("module", "input", "output", "wire", "assign", "endmodule"):
        continue
    cells[name.lstrip("\\")] = (typ, {pm.group(1): pm.group(2).strip().lstrip("\\").strip() for pm in re.finditer(r"\.(\w+)\(\s*([^)]*?)\s*\)", body)})
MAC = ("cim_macro", "count_sram", "hdc_class_array", "sign_sram")
OUT = {"Q", "QN", "Y", "S", "CO", "Z", "ECK"}
drv, loads = {}, collections.defaultdict(list)
for n, (typ, pins) in cells.items():
    for p, net in pins.items():
        if p in OUT or (typ in MAC and p.endswith("_o")):
            drv[net] = (n, p)
        else:
            loads[net].append((n, p))
REP = re.compile(r"^(wire|fanout|rebuffer|max_cap|load_slew|split|place|hold|input|output)\d")


def mod(n):
    typ = cells[n][0]
    if typ in MAC:
        return "MACRO " + typ
    parts = [q for q in n.split(".")[:-1] if not q.startswith("$") and not q.startswith("_")]
    return ".".join(parts[:2]) if parts else "(top)"


def root(n, depth=0):
    a_ = cells[n][1].get("A")
    if a_ is None:
        return "?"
    d = drv.get(a_)
    if d is None:
        return "PORT " + re.sub(r"\[\d+\]", "[*]", a_)
    if REP.match(d[0]) and depth < 60:
        return root(d[0], depth + 1)
    nm = re.sub(r"\[\d+\]", "[*]", a_)
    return nm if not re.match(r"^(net\d+|_\d+_)$", nm) and not re.search(r"\._\d+_$", nm) else mod(d[0]) + " <logic> " + (cells[d[0]][0] if cells[d[0]][0] in MAC else "")


def sinks(n, depth=0):
    out = collections.Counter()
    for (l, p) in loads.get(cells[n][1].get("Y"), []):
        if REP.match(l) and depth < 60:
            out += sinks(l, depth + 1)
        else:
            out[mod(l) + ("/" + p if cells[l][0] in MAC else "")] += 1
    return out


P = {}
for l in open(run / "an" / f"inst_{a.name}_fast.rpt"):
    f = l.split()
    if len(f) == 5 and re.match(r"[\d.e+-]+$", f[3]):
        P[f[4].replace("\\", "")] = float(f[3])
agg, sk, nb = collections.defaultdict(float), collections.defaultdict(collections.Counter), collections.Counter()
for n in cells:
    if REP.match(n) and n in P:
        r = root(n)
        agg[r] += P[n]; sk[r] += sinks(n); nb[r] += 1
print(f"buffers inserted by the layout: {sum(agg.values()) * 1e6:.0f} uW in {sum(nb.values())} cells")
for k, v in sorted(agg.items(), key=lambda kv: -kv[1])[:a.top]:
    print(f"{v * 1e6:7.1f} uW {nb[k]:5d} bufs  {k[:52]:52s} -> {', '.join(x for x, _ in sk[k].most_common(3))[:70]}")
