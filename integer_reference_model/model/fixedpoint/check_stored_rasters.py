"""
Data-free consistency checks against the artifacts of the verified float pipeline
(reference rasters recorded by capture_dvs_frozen.py / train_and_capture.py).

Needs no event data. Establishes, on the REAL recorded rasters:
  (a) class HVs re-derived from the checkpoint == class HVs recorded next to the raster;
  (b) the integer scoring path (XNOR-popcount + argmax) applied to the recorded spike
      raster reproduces the recorded prediction for every sample, and the recorded
      accuracy (seed 0 = 84.58% = 203/240);
  (c) the checkpoint <-> raster file pairing is right (v_thresh matches sidecar);
  (d) worst-case width bounds from the checkpoint's int8 weights and the recorded
      per-sample event counts.
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths as P
from quantize import load_int_params, near_integer_margin, thresholds
from int_model import predict
from bounds import worst_case


def check(name, ckpt, raster_npz, sidecar_json, recorded_acc, normalised=False):
    prm = load_int_params(ckpt)
    r = np.load(raster_npz)
    side = json.load(open(sidecar_json))
    out = dict(name=name)
    out["class_hv_match_checkpoint"] = bool(np.array_equal(prm.class_hv, r["class_hv"]))
    preds = np.array([predict(r["raster"][i], prm.class_hv)[0] for i in range(len(r["labels"]))])
    out["n_samples"] = int(len(preds))
    out["int_pred_equals_recorded_pred"] = int((preds == r["pred"]).sum())
    out["int_accuracy"] = float((preds == r["labels"]).mean())
    out["recorded_accuracy"] = float(recorded_acc)
    out["accuracy_matches"] = bool(abs(out["int_accuracy"] - recorded_acc) < 1e-9)
    vt_side = side.get("v_thresh_final")
    out["v_thresh_ckpt"] = prm.v_thresh
    out["v_thresh_sidecar"] = vt_side
    out["v_thresh_match"] = None if vt_side is None else bool(abs(vt_side - prm.v_thresh) < 1e-6)
    thr = prm.thresh_int
    if normalised:  # input-normalised model: threshold is per-sample ceil(v_thresh*N_e/s_j); bound with the largest N_e
        thr = thresholds(prm.v_thresh, prm.scale, int(r["N_e"].max()))
    out["thresh_int" + ("_at_max_Ne" if normalised else "")] = thr.tolist()
    out["thresh_min_dist_to_integer"] = float(min(near_integer_margin(prm.v_thresh, float(s)) for s in prm.scale))
    out["worst_case_bounds"] = worst_case(prm.W, thr, r["n_events"])
    out["raster_firing_rate"] = float(r["raster"].mean())
    return out


if __name__ == "__main__":
    res = []
    for s in (0, 1, 2):
        side = json.load(open(f"{P.CKPT_DIR}/frozen_seed{s}.json"))
        res.append(check(f"dvsgesture_seed{s}", f"{P.CKPT_DIR}/frozen_seed{s}.pt",
                         f"{P.REF_RASTER_DIR}/dvsgesture_frozen_n20_T100_seed{s}.npz",
                         f"{P.REF_RASTER_DIR}/dvsgesture_frozen_n20_T100_seed{s}.json", side["test_acc"]))
    side = json.load(open(f"{P.CKPT_DIR}/nmnist_seed0.json"))
    res.append(check("nmnist_seed0", f"{P.CKPT_DIR}/nmnist_seed0.pt",
                     f"{P.REF_RASTER_DIR}/nmnist_n20_T100_seed0.npz",
                     f"{P.CKPT_DIR}/nmnist_seed0.json", side["test_accuracy"], normalised=True))
    os.makedirs(P.OUT_DIR, exist_ok=True)
    json.dump(res, open(f"{P.OUT_DIR}/stored_raster_consistency.json", "w"), indent=1)
    for r in res:
        print(f"{r['name']:18s} hv_match={r['class_hv_match_checkpoint']} "
              f"pred==rec {r['int_pred_equals_recorded_pred']}/{r['n_samples']} "
              f"acc={r['int_accuracy']:.4f} (rec {r['recorded_accuracy']:.4f}) vth_match={r['v_thresh_match']} "
              f"min|thr-int|={r['thresh_min_dist_to_integer']:.4f}")
