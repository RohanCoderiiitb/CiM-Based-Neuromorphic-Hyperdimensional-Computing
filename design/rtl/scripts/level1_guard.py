#!/usr/bin/env python3
"""Level 1 guard. If Phase 0's int_model.py (or its event/address helpers) ever changes behaviour, the golden vectors the RTL is compared
against stop being a true reference. This re-checks, with the CURRENT Phase 0 code, that
  (a) the Phase 0 pytest suite passes,
  (b) int_model.snn_forward on every exported count vector reproduces the stored X / Vp / V / spikes / pred-independent traces
      (DVS-Gesture 240 samples x 3 seeds, N-MNIST 1000 samples),
  (c) every exported AER stream -> address generator (eq. 19) -> counts reproduces the stored addresses and count vectors, and the
      event-by-event boundary counter equals the closed-form timestep rule.
(The score/prediction check of load_vectors.verify needs the trained class hypervectors, which are not part of the exported vectors; the RTL
regression checks the raster exactly, which is stronger for what 1E consumes.)  Writes results/regression/level1_guard.json."""
import json, pathlib, subprocess, sys, time
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tb" / "common"))
import golden as G  # noqa: E402  (sets up the Phase 0 import paths)
import load_vectors as LV  # noqa: E402
import int_model as IM  # noqa: E402

P0 = G.P0
t0 = time.time()
res = dict(pytest=None, traces={}, events={})
p = subprocess.run([sys.executable, "-m", "pytest", str(P0 / "tests"), "-q"], capture_output=True, text=True)
res["pytest"] = dict(returncode=p.returncode, summary=p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-200:])
for ds, seeds in (("dvsgesture", (0, 1, 2)), ("nmnist", (0,))):
    for s in seeds:
        man, c, sd, W = G.load_dataset(ds, s)
        n = len(c["labels"]); bad = 0
        for i in range(n):
            tr = IM.snn_forward(c["counts"][i], W, sd["thresh_int"][i])
            ok = (np.array_equal(tr.X, sd["X"][i]) and np.array_equal(tr.Vp, sd["Vp"][i]) and np.array_equal(tr.V, sd["V"][i]) and np.array_equal(tr.S, sd["spikes"][i]))
            bad += not ok
        res["traces"][f"{ds}_seed{s}"] = dict(samples=n, mismatching=bad)
    try:
        res["events"][ds] = dict(streams=int(LV.verify_events(str(G.VEC), ds)), error=None)
    except AssertionError as e:
        res["events"][ds] = dict(streams=0, error=str(e))
res["pass"] = (res["pytest"]["returncode"] == 0 and all(v["mismatching"] == 0 for v in res["traces"].values()) and all(v["error"] is None for v in res["events"].values()))
res["wall_s"] = round(time.time() - t0, 1)
json.dump(res, open(HERE.parent / "results" / "regression" / "level1_guard.json", "w"), indent=1)
print(("[PASS]" if res["pass"] else "[FAIL]"), "level1_guard:", res["pytest"]["summary"], "|", {k: v["mismatching"] for k, v in res["traces"].items()}, "| streams", {k: v["streams"] for k, v in res["events"].items()}, f"| {res['wall_s']}s")
sys.exit(0 if res["pass"] else 1)
