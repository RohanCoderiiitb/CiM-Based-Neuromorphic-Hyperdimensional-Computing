"""
Golden-vector export. Format is specified in formats.md (FORMAT_VERSION below).
Layout:  tb/vectors/<dataset>/counts.npz , seed<k>.npz , manifest.json
"""
import hashlib, json, os
import numpy as np

FORMAT_VERSION = "1.0"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def export_counts(outdir, d):
    os.makedirs(outdir, exist_ok=True)
    np.savez_compressed(f"{outdir}/counts.npz", counts=d["counts"].astype(np.uint16), labels=d["labels"],
                        n_events=d["n_events"], N_e=d["N_e"], sample_id=d["paths"].astype(str))


def export_seed(outdir, seed, tr, thr, pred, prefix_scores, ref_pred, float_S_match):
    np.savez_compressed(
        f"{outdir}/seed{seed}.npz",
        thresh_int=np.asarray(thr, np.int32),               # [S,20]
        X=tr.X.astype(np.int32), Vp=tr.Vp.astype(np.int32), V=tr.V.astype(np.int32),
        spikes=tr.S.astype(np.uint8),                        # [S,100,20]
        pred=pred.astype(np.int8),                           # [S]
        score_xnor_prefix=prefix_scores.astype(np.int16),    # [S,100,10]
        float_pred=ref_pred.astype(np.int8),                 # prediction of the float model (fresh run)
        float_raster_identical=np.asarray(float_S_match, np.uint8))  # [S] 1 if raster == float raster


def write_manifest(outdir, dataset, meta):
    files = sorted(f for f in os.listdir(outdir) if f.endswith(".npz"))
    meta = dict(meta, format_version=FORMAT_VERSION, dataset=dataset,
                sha256={f: sha256(f"{outdir}/{f}") for f in files})
    json.dump(meta, open(f"{outdir}/manifest.json", "w"), indent=1)
