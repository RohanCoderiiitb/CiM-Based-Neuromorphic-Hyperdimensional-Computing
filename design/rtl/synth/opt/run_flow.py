#!/usr/bin/env python3
"""One run of the optimised flow: Yosys (slow library) -> netlist for P&R -> floorplan params -> OpenROAD stages. Everything lands in synth/work/opt/<tag>/.
  python run_flow.py --tag c0 --build full --g 4 --util 0.6 [--stages 'floorplan place cts groute route'] [--macro-dir <dir with cim_macro.lef/.lib ...>] [--skip-synth]"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
REPO = SYNTH.parents[2]
sys.path.insert(0, str(HERE))
import synth_opt as SO  # noqa: E402

OPENROAD = os.environ.get("OPENROAD", os.path.expanduser("~/.cache/cim_neurohdc/openroad_src/build/bin/openroad"))
ap = argparse.ArgumentParser()
ap.add_argument("--tag", required=True)
ap.add_argument("--build", default="full")
ap.add_argument("--g", type=int, default=4)
ap.add_argument("--util", type=float, default=0.6)
ap.add_argument("--density", type=float, default=0.6)
ap.add_argument("--stages", default="floorplan place cts groute route")
ap.add_argument("--macro-dir", default=str(SYNTH / "work" / "full"))
ap.add_argument("--skip-synth", action="store_true")
ap.add_argument("--syn-from", default=None, help="reuse the synthesis of another run tag (copies its syn/ directory)")
ap.add_argument("--dont-use", nargs="*", default=["*XL"])
ap.add_argument("--extra-macros", nargs="*", default=[])
ap.add_argument("--gate-min", type=int, default=4, help="Yosys clockgate -min_net_size: flip-flops sharing one enable before a clock gate is inserted")
ap.add_argument("--cols", type=int, default=40, help="N_PARALLEL_COLS (columns sensed per pass: 160 = one pass, 40 = four passes)")
ap.add_argument("--margin", type=float, default=10.0)
ap.add_argument("--gen-macros", action="store_true", help="generate the macros of the optimised design (opt/gen_macros.py) instead of copying --macro-dir")
ap.add_argument("--cim-area", type=float, default=None)
ap.add_argument("--core-w", type=float, default=None)
ap.add_argument("--pitch", type=float, default=0.8, help="macro pin pitch, um")
ap.add_argument("--rtl-root", default=None, help="RTL tree to synthesise (a snapshot); default the repository")
ap.add_argument("--set", default="", help="extra chparam settings, e.g. '-set A0_SKIP_EN 0'")
ap.add_argument("--hdc-store", default=None, choices=["analog", "sram"], help="gen_macros --hdc-store")
ap.add_argument("--hier-names", action="store_true", help="map every module on its own and flatten afterwards: cell names keep the module path (per-module power attribution)")
a = ap.parse_args()
run = SYNTH / "work" / "opt" / a.tag
run.mkdir(parents=True, exist_ok=True)
t0 = time.time()
if a.syn_from:
    shutil.rmtree(run / "syn", ignore_errors=True)
    shutil.copytree(SYNTH / "work" / "opt" / a.syn_from / "syn", run / "syn")
    a.skip_synth = True
if not a.skip_synth:
    if a.rtl_root:
        SO.set_rtl_root(Path(a.rtl_root))
    d = SO.synth(a.build, run / "syn", a.g, "slow", 10.0, a.dont_use, (a.set + f" -set N_PARALLEL_COLS {a.cols}").strip(), hier="names" if a.hier_names else False, gate_min=a.gate_min)
    print("synth:", {k: v for k, v in d.items() if k != "stub"}, flush=True)
mac = run / "macro"
if a.gen_macros:
    shutil.rmtree(mac, ignore_errors=True)
    r = subprocess.run([sys.executable, str(HERE / "gen_macros.py"), "--out", str(mac), "--g", str(a.g), "--cols", str(a.cols), "--build", a.build, "--pitch", str(a.pitch), *(["--cim-area-um2", str(a.cim_area)] if a.cim_area else []), *(["--rtl-root", a.rtl_root] if a.rtl_root else []), *(["--hdc-store", a.hdc_store] if a.hdc_store else [])], capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip()[-500:], flush=True)
    if r.returncode:
        sys.exit("gen_macros failed")
    import json as _json
    mj = _json.loads((mac / "macros.json").read_text())
    if "count_sram" in mj and not a.extra_macros:
        def blk(n):          # the 8 counter banks (two ping-pong sets of 4) form a compact block: one column per bank, one row per set, 5 um apart; other macros are single
            k = mj[n].get("n_instances", 1)
            rows = 6 if k == 24 else (2 if k >= 8 else 1)      # lane-private counters: 2 sets x 3 lanes rows of 4 banks
            cols = k // rows
            h = mj[n]['height_um'] * rows + 5.0 * (rows - 1)
            return f"{n}:{mj[n]['width_um'] * cols + 5.0 * (cols - 1)}:{h}"
        a.extra_macros = [blk(n) for n in ("count_sram", "sign_sram") if n in mj]
elif not mac.exists() or not a.skip_synth:
    shutil.rmtree(mac, ignore_errors=True)
    mac.mkdir()
    for f in Path(a.macro_dir).glob("*"):
        if f.suffix == ".lef":
            shutil.copy(f, mac / f.name)
        elif f.suffix == ".lib":
            nm = f.stem
            (mac / f.name).write_text(re.sub(r"library \(\w+\)", f"library ({nm}_lib)", f.read_text(), count=1))
libs = [str(p) for p in mac.glob("*.lib")]
r = subprocess.run([sys.executable, str(HERE / "pnr_netlist.py"), "--net", str(run / "syn" / "netlist.v"), "--macro-lib", *libs, "--out", str(run / "netlist_pnr.v")], capture_output=True, text=True)
print(r.stdout.strip(), flush=True)
if r.returncode:
    sys.exit(r.stderr)
cells = max(float(x) for x in re.findall(r"Chip area for (?:top )?module\s+'?\\?[^':\n]+'?\s*:\s*([\d.eE+\-]+)", (run / "syn" / "stat.txt").read_text()))
macros = [m for m in (mac.glob("*.lef"))]
r = subprocess.run([sys.executable, str(HERE / "fp.py"), "--cells", str(cells), "--util", str(a.util), "--margin", str(a.margin), *(["--core-w", str(a.core_w)] if a.core_w else []), "--macro-dir", str(mac), "--out", str(run), *(["--extra-macros", *a.extra_macros] if a.extra_macros else [])], capture_output=True, text=True)
print(r.stdout.strip(), r.stderr.strip(), flush=True)
env = dict(os.environ, RUN=str(run), REPO=str(REPO), STAGES=a.stages, PLACE_DENSITY=str(a.density))
# cim_macro.lef / hdc_class_array.lef are looked up by their MACRO names; the _fact/_unfact suffix files carry the MACRO name hdc_class_array
groups = []
for s_ in a.stages.split():
    if s_ == "route" and groups and groups[-1] == ["groute"]:
        groups[-1].append("route")          # detailed routing in the SAME session as the global route, so its parasitics are those of the routes in memory
    else:
        groups.append([s_])
for st in [" ".join(g_) for g_ in groups]:
    t1 = time.time()
    log = run / f"{st}.log"
    env["STAGES"] = st
    rr = subprocess.run([OPENROAD, "-no_init", "-exit", str(HERE / "flow.tcl")], env=env, capture_output=True, text=True)
    log.write_text(rr.stdout + rr.stderr)
    ok = "STAGES DONE" in rr.stdout
    err = next((l for l in (rr.stdout + rr.stderr).splitlines() if "ERROR" in l), "")
    print(f"[{st}] {'ok' if ok else 'FAILED ' + err} {time.time() - t1:.0f}s", flush=True)
    if not ok:
        sys.exit(1)
print(f"flow done in {time.time() - t0:.0f}s: {run}")
