#!/usr/bin/env python3
"""Aggregate an OpenSTA per-instance power report (opt/power.py --instances: work/opt/<tag>/an/inst_<window>_fast.rpt) by what the instance is:
 logic (unnamed synthesised cells), wire-repair / load-slew / fanout / input-output / hold buffers (names given by the repair steps), clock tree (clkbuf*, clkload), macros.
   python opt/instagg.py <tag> [ing mvm]"""
import re
import sys
from collections import defaultdict
from pathlib import Path

GROUPS = [("logic cells", ("",)), ("wire-repair buffers", ("wire",)), ("load-slew buffers", ("loadslew",)), ("fanout buffers", ("fanout",)), ("hold buffers", ("hold",)),
          ("port buffers", ("input", "output")), ("clock tree", ("clkbuf", "clkbuff", "clkbufclki", "clkbuffclki", "clkbufleaf", "clkload", "clkbufroot", "clkinv")), ("macros", ("usnn", "uquery"))]


def agg(path: Path) -> dict:
    d = defaultdict(lambda: [0, 0.0])
    tot = 0.0
    for ln in path.read_text().splitlines():
        p = ln.split()
        if len(p) < 5:
            continue
        try:
            t = float(p[3])
        except ValueError:
            continue
        key = re.sub(r"[^a-zA-Z]", "", p[4].split(".")[0])
        d[key][0] += 1
        d[key][1] += t
        tot += t
    out = {}
    used = set()
    for lab, keys in GROUPS:
        n = sum(d[k][0] for k in keys if k in d)
        w = sum(d[k][1] for k in keys if k in d)
        used.update(keys)
        out[lab] = (n, w)
    rest = [(k, v) for k, v in d.items() if k not in used]
    out["other"] = (sum(v[0] for _, v in rest), sum(v[1] for _, v in rest))
    return dict(groups=out, total=tot)


def main() -> None:
    tag = sys.argv[1]
    wins = sys.argv[2:] or ["ing", "mvm"]
    base = Path(__file__).resolve().parents[1] / "work" / "opt" / tag / "an"
    for w in wins:
        r = agg(base / f"inst_{w}_fast.rpt")
        print(f"-- {tag} {w}: total {r['total'] * 1e3:.3f} mW")
        for lab, (n, p) in r["groups"].items():
            print(f"   {lab:22s} {n:6d}  {p * 1e6:8.1f} uW  {100 * p / r['total']:5.1f} %")


if __name__ == "__main__":
    main()
