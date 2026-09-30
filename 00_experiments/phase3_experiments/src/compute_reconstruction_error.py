"""
Reconstruction error mean(C_factored != C_baseline), per the task's required
report field: for a completed (R, mode, seed) checkpoint, compare its
reconstructed class HV C = sign(Wc_hat) against the SEED-MATCHED baseline's
actual trained class HV C = sign(Wc), bit for bit.
"""
import sys
import os
import json
import torch
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
P1_ROOT = os.path.join(os.path.dirname(os.path.dirname(ROOT)), "phase1_firing_characterization")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(P1_ROOT, "src"))
from factorized_model import NeuroHDCFactorized  # noqa: E402
from neurohdc import sign_ste  # noqa: E402

ART = os.path.join(os.path.dirname(ROOT), "artifacts")


def reconstruction_error(run_name, rank, factor_mode, baseline_seed):
    ckpt = torch.load(f"{ART}/checkpoints/{run_name}.pt", map_location="cpu")
    model = NeuroHDCFactorized(n=20, T=100, n_input=512, n_classes=10, rank=rank, factor_mode=factor_mode)
    model.load_state_dict(ckpt)
    model.eval()
    with torch.no_grad():
        C_factored = (model._reconstruct_C() > 0).numpy()  # [N, T*n]

    base_ckpt = torch.load(f"{P1_ROOT}/artifacts/dvs_accuracy/frozen_seed{baseline_seed}.pt", map_location="cpu")
    Wc_base = base_ckpt["Wc"]
    C_base = (torch.sign(Wc_base) > 0).numpy()  # [N, T*n]

    mismatch = (C_factored != C_base).mean()
    return float(mismatch)


def main():
    import glob
    results = {}
    for path in sorted(glob.glob(f"{ART}/tables/*.json")):
        name = os.path.basename(path)[:-5]
        if name.startswith("exp") or name.startswith("smoke"):
            continue
        d = json.load(open(path))
        if "rank" not in d or "factor_mode" not in d:
            continue
        rank, mode, bseed = d["rank"], d["factor_mode"], d.get("baseline_seed")
        if bseed is None:
            continue
        err = reconstruction_error(name, rank, mode, bseed)
        results[name] = dict(rank=rank, factor_mode=mode, baseline_seed=bseed,
                              reconstruction_error=err)
        print(f"{name}: rank={rank} mode={mode} baseline_seed={bseed} "
              f"reconstruction_error={err:.4f}")

    with open(f"{ART}/tables/reconstruction_errors.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {ART}/tables/reconstruction_errors.json")


if __name__ == "__main__":
    main()
