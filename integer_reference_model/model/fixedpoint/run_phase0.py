"""
Phase-0 driver: extraction check -> integer vs float raster comparison (bit for bit) ->
true-maximum measurement -> width freeze -> weight image + golden vector export.

  python run_phase0.py --data-root /path/to/data [--nmnist-per-class 100] [--dvs-train-root ...]

Expected layout under --data-root (same as the original training scripts):
  DVSGesture/ibmGestureTest/  [DVSGesture/ibmGestureTrain/]     NMNIST/Test/
Hard gate: the integer pipeline must reproduce each checkpoint's recorded test accuracy exactly
(seed 0 = 84.58%); otherwise the run stops before exporting anything.
"""
import argparse, json, os, platform, subprocess, sys, time
import numpy as np
import torch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths as P
from neurohdc import fake_quant_int8
from quantize import load_int_params
from int_model import xnor_scores_prefix, event_serial_X, bitplane_X
import data as D
import pipeline as PL
from bounds import bits_signed, worst_case

sys.path.insert(0, os.path.join(P.MODEL_DIR, "export"))
from export_weights import export_weight_image, verify_image, weight_planes  # noqa: E402
import export_vectors as EV  # noqa: E402
import load_vectors as LV  # noqa: E402


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=P.ROOT, text=True).strip()
    except Exception:
        return "unknown"


def extraction_check(prm):
    """Extracted q*s must equal, bit for bit, what the float model's quantizer produces."""
    sd = torch.load(prm.ckpt, map_location="cpu")
    wq = fake_quant_int8(sd["Ws"].float(), per_channel=True).numpy()
    return bool(np.array_equal(wq, prm.Wq_float)) and bool(np.abs(prm.W).max() <= 127)


def identities(prm, counts, planes, n_samples=3, n_steps=10):
    """Batching identity (P1.1.3) and bit-plane dataflow, on real count vectors."""
    for i in range(min(n_samples, len(counts))):
        for t in range(0, 100, 100 // n_steps):
            ct = counts[i, t].astype(np.int64)
            X = ct @ prm.W.astype(np.int64).T
            assert np.array_equal(event_serial_X(ct, prm.W), X), "batching identity violated"
            assert np.array_equal(bitplane_X(ct, planes, 16), X), "bit-plane dataflow mismatch"
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=os.path.join(os.path.dirname(P.ROOT), "data"))
    ap.add_argument("--nmnist-per-class", type=int, default=100)
    ap.add_argument("--dvs-train-root", default=None, help="optional: also MEASURE maxima on the train split")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    a = ap.parse_args()
    os.makedirs(P.OUT_DIR, exist_ok=True)
    res = dict(git_sha=git_sha(), torch=torch.__version__, numpy=np.__version__, python=platform.python_version(),
               date=time.strftime("%Y-%m-%d %H:%M:%S"), dvs={}, nmnist={}, measured={}, gates={})
    meas_all = []

    # ---------------- DVS-Gesture ----------------
    print("loading DVS-Gesture test ...")
    dvs = D.load_dvs(f"{a.data_root}/DVSGesture/ibmGestureTest")
    S = len(dvs["labels"]); assert S == 240, f"expected 240 test samples, got {S}"
    frames = D.float_frames(dvs["counts"], dvs["N_e"], normalise=False)
    dvs_out = {}
    for s in a.seeds:
        ck = f"{P.CKPT_DIR}/frozen_seed{s}.pt"
        prm = load_int_params(ck)
        rec = json.load(open(f"{P.CKPT_DIR}/frozen_seed{s}.json"))["test_acc"]
        ref = np.load(f"{P.REF_RASTER_DIR}/dvsgesture_frozen_n20_T100_seed{s}.npz")
        ridx = D.match_reference(dvs, ref)
        Sf, Pf = PL.float_run(ck, frames)
        tr, thr, pred = PL.int_run(prm, dvs["counts"])
        r = dict(extraction_bit_exact=extraction_check(prm), recorded_acc=rec,
                 int_acc=float((pred == dvs["labels"]).mean()), float_fresh_acc=float((Pf == dvs["labels"]).mean()),
                 stored_ref_acc=float((ref["pred"][ridx] == dvs["labels"]).mean()),
                 int_vs_float_fresh=PL.compare(tr.S, Sf, tr, thr),
                 int_vs_stored_ref=PL.compare(tr.S, ref["raster"][ridx], tr, thr),
                 float_fresh_vs_stored_ref=PL.compare(Sf, ref["raster"][ridx], tr, thr),
                 pred_int_eq_stored=int((pred == ref["pred"][ridx]).sum()),
                 pred_int_eq_float_fresh=int((pred == Pf).sum()),
                 identities_ok=identities(prm, dvs["counts"], weight_planes(prm.W)),
                 thresh_int=prm.thresh_int.tolist(), v_thresh=prm.v_thresh)
        r["measured"] = PL.measure(dvs["counts"], tr)
        r["worst_case"] = worst_case(prm.W, prm.thresh_int, dvs["n_events"])
        res["dvs"][s] = r
        res["gates"][f"dvs_seed{s}_accuracy_reproduced"] = bool(abs(r["int_acc"] - rec) < 1e-12)
        print(f"[dvs seed{s}] int acc {r['int_acc']:.4f} recorded {rec:.4f} | "
              f"diff spikes vs fresh float {r['int_vs_float_fresh']['differing_spikes']} , vs stored "
              f"{r['int_vs_stored_ref']['differing_spikes']}  | bit-exact samples "
              f"{r['int_vs_float_fresh']['samples_bit_exact']}/240")
        meas_all.append(r["measured"])
        dvs_out[s] = (prm, tr, thr, pred, Pf, Sf)
        if not res["gates"][f"dvs_seed{s}_accuracy_reproduced"] or not r["extraction_bit_exact"]:
            json.dump(res, open(f"{P.OUT_DIR}/results_FAILED_GATE.json", "w"), indent=1, default=str)
            sys.exit(f"STOP: seed {s} extraction does not reproduce the recorded accuracy / quantizer output.")

    # ---------------- optional train-split measurement ----------------
    if a.dvs_train_root:
        print("loading DVS-Gesture train (measurement only) ...")
        tr_d = D.load_dvs(a.dvs_train_root)
        res["measured"]["dvs_train"] = {}
        for s in a.seeds:
            prm = dvs_out[s][0]
            trn, _, _ = PL.int_run(prm, tr_d["counts"])
            m = PL.measure(tr_d["counts"], trn); res["measured"]["dvs_train"][s] = m; meas_all.append(m)

    # ---------------- N-MNIST (only seed 0 exists) ----------------
    nm_out = None
    if a.nmnist_per_class:
        print("loading N-MNIST test subsample ...")
        nm = D.load_nmnist(f"{a.data_root}/NMNIST/Test", per_class=a.nmnist_per_class)
        ck = f"{P.CKPT_DIR}/nmnist_seed0.pt"
        prm = load_int_params(ck)
        rec = json.load(open(f"{P.CKPT_DIR}/nmnist_seed0.json"))["test_accuracy"]
        ref = np.load(f"{P.REF_RASTER_DIR}/nmnist_n20_T100_seed0.npz")
        ri = nm["ref_index"]
        assert np.array_equal(ref["n_events"][ri], nm["n_events"]) and np.array_equal(ref["labels"][ri], nm["labels"])
        fr = D.float_frames(nm["counts"], nm["N_e"], normalise=True)
        Sf, Pf = PL.float_run(ck, fr, bs=128)
        tr, thr, pred = PL.int_run(prm, nm["counts"], nm["N_e"], normalised=True)
        r = dict(n_samples=len(pred), recorded_full_test_acc=rec, int_acc_subsample=float((pred == nm["labels"]).mean()),
                 float_fresh_acc_subsample=float((Pf == nm["labels"]).mean()),
                 stored_ref_acc_subsample=float((ref["pred"][ri] == nm["labels"]).mean()),
                 int_vs_float_fresh=PL.compare(tr.S, Sf, tr, thr),
                 int_vs_stored_ref=PL.compare(tr.S, ref["raster"][ri], tr, thr),
                 float_fresh_vs_stored_ref=PL.compare(Sf, ref["raster"][ri], tr, thr),
                 pred_int_eq_stored=int((pred == ref["pred"][ri]).sum()),
                 pred_int_eq_float_fresh=int((pred == Pf).sum()),
                 v_thresh=prm.v_thresh, extraction_bit_exact=extraction_check(prm),
                 identities_ok=identities(prm, nm["counts"], weight_planes(prm.W)))
        r["measured"] = PL.measure(nm["counts"], tr)
        res["nmnist"][0] = r; meas_all.append(r["measured"])
        print(f"[nmnist seed0] subsample acc int {r['int_acc_subsample']:.4f} float {r['float_fresh_acc_subsample']:.4f} | "
              f"diff spikes vs fresh float {r['int_vs_float_fresh']['differing_spikes']} / {r['int_vs_float_fresh']['spikes_compared']}")
        nm_out = (prm, tr, thr, pred, Pf, Sf, nm)

    # ---------------- freeze widths ----------------
    merged = PL.merge_measure(meas_all)
    W = PL.widths(merged)
    thr_max = max(int(np.max(v[0].thresh_int)) for v in dvs_out.values())
    if nm_out is not None:
        thr_max = max(thr_max, int(nm_out[2].max()))
    W["W_THRESH"] = bits_signed(0, thr_max)
    assert W["W_THRESH"] <= W["W_V"], "threshold must fit the V datapath"
    res["measured"]["merged"] = merged; res["frozen_widths"] = W
    print("measured:", merged); print("frozen widths:", W)

    # ---------------- export ----------------
    wdir = f"{P.VECTOR_DIR}/weights"
    for s, (prm, tr, thr, pred, Pf, Sf) in dvs_out.items():
        export_weight_image(wdir, s, prm.W, prm.thresh_int, W["W_THRESH"]); verify_image(wdir, s, prm.W)
        np.save(f"{P.OUT_DIR}/class_hv_seed{s}.npy", prm.class_hv)
        d = f"{P.VECTOR_DIR}/dvsgesture"; os.makedirs(d, exist_ok=True)
        if s == a.seeds[0]:
            EV.export_counts(d, dvs)
        pref = np.stack([xnor_scores_prefix(tr.S[i], prm.class_hv) for i in range(S)])
        EV.export_seed(d, s, tr, thr, pred, pref, Pf, (tr.S == Sf).reshape(S, -1).all(1))
    EV.write_manifest(f"{P.VECTOR_DIR}/dvsgesture", "dvsgesture", dict(seeds=a.seeds, n_samples=S, T=100, frozen_widths=W, git_sha=res["git_sha"]))
    if nm_out is not None:
        prm, tr, thr, pred, Pf, Sf, nm = nm_out
        d = f"{P.VECTOR_DIR}/nmnist"; os.makedirs(d, exist_ok=True)
        export_weight_image(wdir, "nmnist0", prm.W, prm.thresh_int, W["W_THRESH"]); verify_image(wdir, "nmnist0", prm.W)
        np.save(f"{P.OUT_DIR}/class_hv_nmnist0.npy", prm.class_hv)
        EV.export_counts(d, nm)
        n = len(pred)
        pref = np.stack([xnor_scores_prefix(tr.S[i], prm.class_hv) for i in range(n)])
        EV.export_seed(d, 0, tr, thr, pred, pref, Pf, (tr.S == Sf).reshape(n, -1).all(1))
        EV.write_manifest(d, "nmnist", dict(seeds=[0], n_samples=n, T=100, per_class=a.nmnist_per_class,
                                            note="thresh_int is per-sample: ceil(v_thresh*N_e/s_j)", frozen_widths=W, git_sha=res["git_sha"]))
    # loadability proof: reload from disk, re-run integer model from counts + weight image, compare everything
    res["vectors_verified"] = {f"dvs_seed{s}": LV.verify(P.VECTOR_DIR, "dvsgesture", s, dvs_out[s][0].class_hv) for s in a.seeds}
    if nm_out is not None:
        res["vectors_verified"]["nmnist"] = LV.verify(P.VECTOR_DIR, "nmnist", 0, nm_out[0].class_hv, weight_tag="nmnist0")
    json.dump(res, open(f"{P.OUT_DIR}/results.json", "w"), indent=1, default=str)
    print("wrote", f"{P.OUT_DIR}/results.json")


if __name__ == "__main__":
    main()
