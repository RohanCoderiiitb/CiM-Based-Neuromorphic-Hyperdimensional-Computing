"""
Phase-0 driver: extraction check -> integer vs float raster comparison (bit for bit) ->
true-maximum measurement -> width freeze -> weight image + golden vector + event stream export.

  python run_phase0.py --data-root /path/to/data [--nmnist-per-class 100] [--dvs-train-root ...]

Expected layout under --data-root (same as the original training scripts):
  DVSGesture/ibmGestureTest/  [DVSGesture/ibmGestureTrain/]     NMNIST/Test/
Hard gate (nothing is exported unless every item holds):
  - each checkpoint's extracted q*s equals the float quantizer output (with the granularity it was trained with);
  - DVS-Gesture, every seed: integer raster == recorded raster, 240/240 samples, and recorded accuracy reproduced;
  - N-MNIST, FULL test set (10000): integer raster == recorded raster and recorded accuracy reproduced;
  - every test sample's raw event stream, through events.py's address/timestep rules, reproduces its counts.
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
import events as E
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
    """Extracted q*s must equal, bit for bit, what the float model's quantizer produces
    with the granularity the checkpoint was trained with."""
    sd = torch.load(prm.ckpt, map_location="cpu")
    wq = fake_quant_int8(sd["Ws"].float(), per_channel=prm.per_channel).numpy()
    return bool(np.array_equal(wq, prm.Wq_float)) and bool(np.abs(prm.W).max() <= 127)


def identities(prm, counts, planes, n_samples=3, n_steps=10):
    """Batching identity (P1.1.3) and bit-plane dataflow, on real count vectors."""
    nb = max(1, int(counts.max()).bit_length())
    for i in range(min(n_samples, len(counts))):
        for t in range(0, 100, 100 // n_steps):
            ct = counts[i, t].astype(np.int64)
            X = ct @ prm.W.astype(np.int64).T
            assert np.array_equal(event_serial_X(ct, prm.W), X), "batching identity violated"
            assert np.array_equal(bitplane_X(ct, planes, nb), X), "bit-plane dataflow mismatch"
    return True


def binning_stats(d, T=100):
    """Timestep sizes implied by events_to_frames: N_e or N_e+1, and how often N_e+1 occurs."""
    n = d["n_events"].astype(np.int64)
    step_sum = d["counts"].astype(np.int64).sum(-1)                       # [S,T]
    sizes_ok = all(np.array_equal(step_sum[i], E.bin_sizes(int(n[i]), T)) for i in range(len(n)))
    r = n % T
    return dict(sum_c_equals_bin_sizes=bool(sizes_ok), samples=int(len(n)),
                samples_with_remainder=int((r > 0).sum()),
                timesteps_with_Ne_plus_1=int(r.sum()), timesteps_total=int(len(n) * T),
                frac_timesteps_Ne_plus_1=float(r.sum() / (len(n) * T)),
                events_left_over_by_fixed_Ne_rule_total=int(r.sum()),
                events_left_over_by_fixed_Ne_rule_max=int(r.max()))


def verify_streams(dataset, d, label):
    bad = [i for i in range(len(d["paths"])) if not E.verify_stream(dataset, str(d["paths"][i]), d["counts"][i])]
    print(f"[{label}] event streams -> counts: {len(d['paths']) - len(bad)}/{len(d['paths'])} exact")
    return dict(samples=int(len(d["paths"])), exact=int(len(d["paths"]) - len(bad)), failing=bad[:20])


def dvs_event_rows(d):
    """Samples whose full AER streams are exported: per class the fewest-event and most-event
    sample (includes the global extremes of N_e)."""
    rows = []
    for c in np.unique(d["labels"]):
        idx = np.nonzero(d["labels"] == c)[0]
        rows += [int(idx[np.argmin(d["n_events"][idx])]), int(idx[np.argmax(d["n_events"][idx])])]
    return sorted(set(rows))


def gate_fail(res, msg):
    json.dump(res, open(f"{P.OUT_DIR}/results_FAILED_GATE.json", "w"), indent=1, default=str)
    sys.exit(f"STOP: {msg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=os.path.join(os.path.dirname(P.ROOT), "data"))
    ap.add_argument("--nmnist-per-class", type=int, default=100, help="size of the EXPORTED N-MNIST subsample "
                    "(the gate always runs on the full test set); 0 skips N-MNIST")
    ap.add_argument("--dvs-train-root", default=None, help="optional: also MEASURE maxima (and compare) on the train split")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    a = ap.parse_args()
    os.makedirs(P.OUT_DIR, exist_ok=True)
    res = dict(git_sha=git_sha(), torch=torch.__version__, numpy=np.__version__, python=platform.python_version(),
               date=time.strftime("%Y-%m-%d %H:%M:%S"), dvs={}, nmnist={}, measured={}, gates={}, streams={}, binning={})
    meas_all = []

    # ---------------- DVS-Gesture ----------------
    print("loading DVS-Gesture test ...")
    dvs = D.load_dvs(f"{a.data_root}/DVSGesture/ibmGestureTest")
    S = len(dvs["labels"]); assert S == 240, f"expected 240 test samples, got {S}"
    res["binning"]["dvs_test"] = binning_stats(dvs)
    res["streams"]["dvs_test"] = verify_streams("dvsgesture", dvs, "dvs test")
    res["gates"]["dvs_streams_reproduce_counts"] = res["streams"]["dvs_test"]["exact"] == S
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
        r = dict(per_channel=prm.per_channel, extraction_bit_exact=extraction_check(prm), recorded_acc=rec,
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
        ok = (abs(r["int_acc"] - rec) < 1e-12 and r["extraction_bit_exact"]
              and r["int_vs_stored_ref"]["differing_spikes"] == 0 and r["pred_int_eq_stored"] == S)
        res["gates"][f"dvs_seed{s}"] = bool(ok)
        print(f"[dvs seed{s}] int acc {r['int_acc']:.4f} recorded {rec:.4f} | "
              f"diff spikes vs fresh float {r['int_vs_float_fresh']['differing_spikes']} , vs stored "
              f"{r['int_vs_stored_ref']['differing_spikes']}  | bit-exact samples "
              f"{r['int_vs_stored_ref']['samples_bit_exact']}/240 | ties Vp==thr {r['int_vs_stored_ref']['n_margin_eq0']}")
        meas_all.append(r["measured"])
        dvs_out[s] = (prm, tr, thr, pred, Pf, Sf)
        if not ok:
            gate_fail(res, f"DVS seed {s} does not reproduce the recorded raster / accuracy / quantizer output.")
    if not res["gates"]["dvs_streams_reproduce_counts"]:
        gate_fail(res, "DVS event streams do not reproduce the counts.")

    # ---------------- optional train-split measurement (+ comparison, extra evidence) ----------------
    if a.dvs_train_root:
        print("loading DVS-Gesture train (measurement + comparison) ...")
        tr_d = D.load_dvs(a.dvs_train_root)
        res["binning"]["dvs_train"] = binning_stats(tr_d)
        fr_t = D.float_frames(tr_d["counts"], tr_d["N_e"], normalise=False)
        res["measured"]["dvs_train"] = {}; res["dvs_train_compare"] = {}
        for s in a.seeds:
            prm = dvs_out[s][0]
            trn, thr_t, _ = PL.int_run(prm, tr_d["counts"])
            Sf_t, _ = PL.float_run(prm.ckpt, fr_t)
            c = PL.compare(trn.S, Sf_t, trn, thr_t); c.pop("first_divergences"); c.pop("differing_samples")
            res["dvs_train_compare"][s] = c
            print(f"[dvs train seed{s}] n={len(tr_d['labels'])} diff spikes vs fresh float {c['differing_spikes']} "
                  f"ties Vp==thr {c['n_margin_eq0']}")
            m = PL.measure(tr_d["counts"], trn); res["measured"]["dvs_train"][s] = m; meas_all.append(m)
        del fr_t

    # ---------------- N-MNIST (only seed 0 exists; gate on the FULL test set) ----------------
    nm_out = None
    if a.nmnist_per_class:
        print("loading N-MNIST test (full) ...")
        root = f"{a.data_root}/NMNIST/Test"
        nm = D.load_nmnist(root, per_class=None)
        n_all = len(nm["labels"])
        ck = f"{P.CKPT_DIR}/nmnist_seed0.pt"
        prm = load_int_params(ck)
        rec = json.load(open(f"{P.CKPT_DIR}/nmnist_seed0.json"))["test_accuracy"]
        ref = np.load(f"{P.REF_RASTER_DIR}/nmnist_n20_T100_seed0.npz")
        ri = nm["ref_index"]
        assert np.array_equal(ref["n_events"][ri], nm["n_events"]) and np.array_equal(ref["labels"][ri], nm["labels"])
        res["binning"]["nmnist_test"] = binning_stats(nm)
        res["streams"]["nmnist_test"] = verify_streams("nmnist", nm, "nmnist test")
        fr = D.float_frames(nm["counts"], nm["N_e"], normalise=True)
        Sf, Pf = PL.float_run(ck, fr, bs=256)
        del fr
        tr, thr, pred = PL.int_run(prm, nm["counts"], nm["N_e"], normalised=True)
        r = dict(per_channel=prm.per_channel, n_samples=n_all, recorded_full_test_acc=rec,
                 int_acc=float((pred == nm["labels"]).mean()), float_fresh_acc=float((Pf == nm["labels"]).mean()),
                 stored_ref_acc=float((ref["pred"][ri] == nm["labels"]).mean()),
                 int_vs_float_fresh=PL.compare(tr.S, Sf, tr, thr),
                 int_vs_stored_ref=PL.compare(tr.S, ref["raster"][ri], tr, thr),
                 float_fresh_vs_stored_ref=PL.compare(Sf, ref["raster"][ri], tr, thr),
                 pred_int_eq_stored=int((pred == ref["pred"][ri]).sum()),
                 pred_int_eq_float_fresh=int((pred == Pf).sum()),
                 v_thresh=prm.v_thresh, extraction_bit_exact=extraction_check(prm),
                 thresh_int_range=[int(thr.min()), int(thr.max())],
                 identities_ok=identities(prm, nm["counts"], weight_planes(prm.W)))
        r["measured"] = PL.measure(nm["counts"], tr)
        res["nmnist"][0] = r; meas_all.append(r["measured"])
        ok = (abs(r["int_acc"] - rec) < 1e-12 and r["extraction_bit_exact"]
              and r["int_vs_stored_ref"]["differing_spikes"] == 0 and r["pred_int_eq_stored"] == n_all)
        res["gates"]["nmnist_seed0_full_test"] = bool(ok)
        res["gates"]["nmnist_streams_reproduce_counts"] = res["streams"]["nmnist_test"]["exact"] == n_all
        print(f"[nmnist seed0] full test n={n_all} acc int {r['int_acc']:.4f} recorded {rec:.4f} | "
              f"diff spikes vs stored {r['int_vs_stored_ref']['differing_spikes']} / {r['int_vs_stored_ref']['spikes_compared']}"
              f" | vs fresh float {r['int_vs_float_fresh']['differing_spikes']} | ties Vp==thr {r['int_vs_stored_ref']['n_margin_eq0']}")
        if not ok:
            gate_fail(res, "N-MNIST does not reproduce the recorded raster / accuracy / quantizer output.")
        if not res["gates"]["nmnist_streams_reproduce_counts"]:
            gate_fail(res, "N-MNIST event streams do not reproduce the counts.")
        # exported subsample (class balanced, same draw as NMNISTDataset(limit_per_class=...))
        rows = D.nmnist_subsample_rows(root, a.nmnist_per_class)
        pos = {int(k): i for i, k in enumerate(ri)}
        rows = np.array([pos[int(k)] for k in rows], np.int64)
        nm_sub = D.subset(nm, rows)
        tr_sub = type(tr)(X=tr.X[rows], Vp=tr.Vp[rows], V=tr.V[rows], S=tr.S[rows])
        nm_out = (prm, tr_sub, thr[rows], pred[rows], Pf[rows], Sf[rows], nm_sub)
        del nm, tr, Sf

    # ---------------- freeze widths ----------------
    merged = PL.merge_measure(meas_all)
    W = PL.widths(merged)
    thr_max = max(int(np.max(v[0].thresh_int)) for v in dvs_out.values())
    if nm_out is not None:
        thr_max = max(thr_max, res["nmnist"][0]["thresh_int_range"][1])
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
            E.export_streams(d, "dvsgesture", dvs["paths"], dvs["labels"], dvs_event_rows(dvs))
        pref = np.stack([xnor_scores_prefix(tr.S[i], prm.class_hv) for i in range(S)])
        EV.export_seed(d, s, tr, thr, pred, pref, Pf, (tr.S == Sf).reshape(S, -1).all(1))
    EV.write_manifest(f"{P.VECTOR_DIR}/dvsgesture", "dvsgesture",
                      dict(seeds=a.seeds, n_samples=S, T=100, quantizer="per-channel", frozen_widths=W,
                           event_stream_rows=dvs_event_rows(dvs), git_sha=res["git_sha"]))
    if nm_out is not None:
        prm, tr, thr, pred, Pf, Sf, nm = nm_out
        d = f"{P.VECTOR_DIR}/nmnist"; os.makedirs(d, exist_ok=True)
        export_weight_image(wdir, "nmnist0", prm.W, prm.thresh_int, W["W_THRESH"]); verify_image(wdir, "nmnist0", prm.W)
        np.save(f"{P.OUT_DIR}/class_hv_nmnist0.npy", prm.class_hv)
        EV.export_counts(d, nm)
        n = len(pred)
        E.export_streams(d, "nmnist", nm["paths"], nm["labels"], list(range(n)))
        pref = np.stack([xnor_scores_prefix(tr.S[i], prm.class_hv) for i in range(n)])
        EV.export_seed(d, 0, tr, thr, pred, pref, Pf, (tr.S == Sf).reshape(n, -1).all(1))
        EV.write_manifest(d, "nmnist", dict(seeds=[0], n_samples=n, T=100, per_class=a.nmnist_per_class,
                                            quantizer="per-tensor (all 20 s_j equal)",
                                            note="thresh_int is per-sample: ceil(v_thresh*N_e/s); "
                                                 "thresh_seednmnist0.mem holds the N_e=1 value",
                                            event_stream_rows="all", frozen_widths=W, git_sha=res["git_sha"]))
    # loadability proof: reload from disk, re-run integer model from counts + weight image, compare everything
    res["vectors_verified"] = {f"dvs_seed{s}": LV.verify(P.VECTOR_DIR, "dvsgesture", s, dvs_out[s][0].class_hv) for s in a.seeds}
    res["vectors_verified"]["dvs_events"] = LV.verify_events(P.VECTOR_DIR, "dvsgesture")
    if nm_out is not None:
        res["vectors_verified"]["nmnist"] = LV.verify(P.VECTOR_DIR, "nmnist", 0, nm_out[0].class_hv, weight_tag="nmnist0")
        res["vectors_verified"]["nmnist_events"] = LV.verify_events(P.VECTOR_DIR, "nmnist")
    if os.path.exists(f"{P.OUT_DIR}/results_FAILED_GATE.json"):
        os.remove(f"{P.OUT_DIR}/results_FAILED_GATE.json")
    json.dump(res, open(f"{P.OUT_DIR}/results.json", "w"), indent=1, default=str)
    print("gates:", res["gates"])
    print("wrote", f"{P.OUT_DIR}/results.json")


if __name__ == "__main__":
    main()
