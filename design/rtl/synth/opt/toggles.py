#!/usr/bin/env python3
"""Toggle count per module scope of a hierarchy-preserving gate-level run (pre-layout): who switches. python opt/toggles.py <vcd>"""
import collections, sys
vcd = sys.argv[1]
ids = {}; scope = []; tog = collections.Counter(); last = {}
with open(vcd) as f:
    for line in f:
        if line.startswith('$scope'): scope.append(line.split()[2])
        elif line.startswith('$upscope'): scope.pop()
        elif line.startswith('$var'):
            p = line.split(); ids.setdefault(p[3], []).append(('/'.join(scope), p[4], int(p[2])))
        elif line.startswith('$enddefinitions'): break
    for line in f:
        c = line[0]
        if c in '01xz':
            i = line[1:].strip()
            if i in ids:
                if last.get(i, c) != c: tog[i] += 1
                last[i] = c
        elif c == 'b':
            v, i = line[1:].split()
            if i in ids:
                o = last.get(i)
                if o is not None and len(o) == len(v): tog[i] += sum(a != b for a, b in zip(o, v))
                last[i] = v
mod = collections.Counter(); nb = collections.Counter()
for i, n in tog.items():
    sc, name, w = ids[i][0]
    mod[sc.replace('hdc_gate_tb/dut', '')] += n; nb[sc.replace('hdc_gate_tb/dut', '')] += w
for k, n in mod.most_common(8): print(f"{k:50s} bits {nb[k]:6d} toggles {n:9d}")
