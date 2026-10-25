#!/usr/bin/env python3
"""Every comparison of two regression runs the Phase 2-4 claims rest on (per timestep, canonical logs):
  fu_s<k>      factorized RTL (a, b, bias) vs UNFACTORIZED RTL fed the expanded class hypervector: identical scores and everything else (Phase 2: 'identical, or say which')
  dis_base_s<k> / dis_r1_s<k>   early exit BUILT with the threshold at its 'never' value vs early exit NOT built (Phase 3): bit-identical (Phase 4 requirement ii)
  sim_<tag>    Icarus vs Verilator on identical stimulus (the ic_ runs against their vt_ twins)
Writes results/hdc/compare_*.json and results/hdc/compare_summary.json; exit status 1 on any disagreement."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compare_hdc_runs import compare  # noqa: E402

HDC = ROOT / "results" / os.environ.get("CIM_RESULTS_SUBDIR", "hdc")


def main() -> int:
    out = []
    RELOAD = {13}                    # the weight / class image shift-in is not the same length for the two class-HV storages: not part of the inference
    for s in (0, 1, 2):
        for tag, a, b, skip in ((f"fu_s{s}", f"p3_r1fact_s{s}", f"p3_r1unfact_s{s}", RELOAD), (f"dis_base_s{s}", f"dis_base_s{s}", f"p3_base_s{s}", set()),
                                (f"dis_r1_s{s}", f"dis_r1fact_s{s}", f"p3_r1fact_s{s}", set())):
            fa, fb = HDC / f"{a}.out.txt.gz", HDC / f"{b}.out.txt.gz"
            if fa.exists() and fb.exists():
                out.append(compare(str(fa), str(fb), tag, skip))
    # E3: the abort modes against the ordinary reset + reload runs of the same configuration (sample for sample, every timestep; the reload cycles differ by construction)
    for s in (0, 1, 2):
        for mode in ("abortmode", "abortstress"):
            fa, fb = HDC / f"{mode}_full_g4_s{s}.out.txt.gz", HDC / f"ab_full_g4_s{s}.out.txt.gz"
            if fa.exists() and fb.exists():
                out.append(compare(str(fa), str(fb), f"{mode}_vs_reload_s{s}", RELOAD))
    for f in sorted(HDC.glob("ic_*.out.txt.gz")):
        t = f.name[: -len(".out.txt.gz")]
        twin = HDC / f"vt_{t[3:]}.out.txt.gz"
        if twin.exists():
            # END field 13 (reload_cycles) is the weight / class image reload that follows an early exit in a STREAM of samples: it depends on how the samples were split into simulator processes
            # (the Icarus runs are chunked, their Verilator twins are not), not on the simulator, and it is not part of the inference. Every other field and every timestep is compared.
            out.append(compare(str(f), str(twin), f"sim_{t[3:]}", RELOAD))
    for r in out:
        print(f"[{r['verdict']}] {r['tag']}: {r['timesteps_compared']} timesteps, {r['disagreements']} disagreements")
    (HDC / "compare_summary.json").write_text(json.dumps([{k: v for k, v in r.items() if k not in ("a", "b")} for r in out], indent=1))
    return 0 if all(r["verdict"] == "AGREE" for r in out) and out else 1


if __name__ == "__main__":
    raise SystemExit(main())
