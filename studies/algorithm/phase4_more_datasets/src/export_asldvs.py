"""ASL-DVS golden vectors for the LARGE chip (40 neurons, 24 classes): integer extraction of the R=1 checkpoints (same quantizer and thresholds as r1_model.py), the gate
(integer accuracy == float test accuracy on the whole test split), the bit widths the integer trace needs (X, V, thresholds), and the export:
  design/reference_model/tb/vectors/asldvs/counts.npz       the first --n-rtl test samples of the fixed random test order (their real event streams are exported too)
  design/reference_model/tb/vectors/asldvs/events.npz       AER words p<<16 | y<<8 | x (uint32), gitignored
  design/reference_model/tb/vectors/asldvs/r1_seed<k>.npz   golden trace / class store / prefix scores of those samples
  design/reference_model/tb/vectors/weights/*aslr1s<k>*     weight image (320-bit rows, 10 macros) + thresholds
   python studies/algorithm/phase4_more_datasets/src/export_asldvs.py [--seeds 0 1 2] [--random 99]   (--random: an untrained model with seed k, for plumbing tests only)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[4]
FP = REPO / "design" / "reference_model" / "model" / "fixedpoint"
sys.path.insert(0, str(FP))
import _paths as P  # noqa: E402
sys.path.insert(0, str(Path(P.MODEL_DIR) / "export"))
from export_weights import export_weight_image, verify_image  # noqa: E402
from hdc_query import agree_factorized, agree_unfactorized, expand_r1, prefix_scores  # noqa: E402
from int_model import snn_forward_batch  # noqa: E402
from quantize import thresholds  # noqa: E402
import events as EV  # noqa: E402

CACHE = REPO / "datasets" / "cache" / "asldvs"
ART = Path(__file__).resolve().parents[1] / "artifacts" / "asldvs"
VEC = Path(P.VECTOR_DIR) / "asldvs"
CKPT = "r1_lr1e-4_seed"
T, N, NCLS, H, W = 100, 40, 24, 180, 240


def quantize(sd) -> dict:
    Ws = sd["Ws"].float()
    scale_t = Ws.abs().amax(dim=1, keepdim=True).clamp_min(1e-8) / 127.0
    q = torch.round(Ws / scale_t).clamp(-127, 127)
    v_thresh = float((torch.nn.functional.softplus(sd["_v_thresh_raw"]) + 1e-3).item())
    sa, sb = torch.sign(sd["A"][:, 0, :]), torch.sign(sd["B"][:, 0, :])
    assert not (sa == 0).any() and not (sb == 0).any()
    return dict(W=q.numpy().astype(np.int8), v_thresh=v_thresh, thresh_int=thresholds(v_thresh, scale_t.reshape(-1).numpy().astype(np.float32)),
                a_bits=(sa > 0).numpy().astype(np.uint8), b_bits=(sb > 0).numpy().astype(np.uint8))


def quantize_base(sd) -> dict:
    """the unfactorized NeuroHDC-large checkpoint: int8 per-channel weights, exact thresholds, class HV bits C = sign(Wc) > 0 as [N, T, n] (flatten order t*n + j)."""
    Ws = sd["Ws"].float()
    scale_t = Ws.abs().amax(dim=1, keepdim=True).clamp_min(1e-8) / 127.0
    q = torch.round(Ws / scale_t).clamp(-127, 127)
    v_thresh = float((torch.nn.functional.softplus(sd["_v_thresh_raw"]) + 1e-3).item())
    C = (torch.sign(sd["Wc"]) > 0).numpy().astype(np.uint8).reshape(NCLS, T, N)        # sign 0 -> -1, as neurohdc.sign_ste
    return dict(W=q.numpy().astype(np.int8), v_thresh=v_thresh, thresh_int=thresholds(v_thresh, scale_t.reshape(-1).numpy().astype(np.float32)), class_hv=C)


def random_model(seed: int, X) -> dict:
    g = torch.Generator().manual_seed(seed)
    Ws = torch.randn(N, 512, generator=g) / np.sqrt(512)
    c = torch.from_numpy(X[:64].astype(np.float32)).reshape(-1, 512)
    med = float((c @ (torch.round(Ws / (Ws.abs().amax(1, keepdim=True) / 127)) * (Ws.abs().amax(1, keepdim=True) / 127)).t()).abs().median())
    sd = dict(Ws=Ws, _v_thresh_raw=torch.tensor(np.log(np.expm1(max(med, 1e-3)))), A=torch.randn(NCLS, 1, N, generator=g), B=torch.randn(NCLS, 1, T, generator=g))
    return quantize(sd)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--random", type=int, default=None)
    ap.add_argument("--n-rtl", type=int, default=2000)
    ap.add_argument("--model", choices=["r1", "unf"], default="r1", help="unf: the unfactorized checkpoints base_seed<k> (the large chip's full class store)")
    a = ap.parse_args()
    VEC.mkdir(parents=True, exist_ok=True)
    (VEC / ".gitignore").write_text("events.npz\n")
    meta = np.load(CACHE / "meta.npz")
    X = np.load(CACHE / "counts.npy", mmap_mode="r")
    order = meta["test_order"]
    rows = order[:a.n_rtl]
    labels_all = meta["label"].astype(np.int16)
    sel = np.sort(rows)                                                                   # memmap reads in ascending order, then back to the fixed random order
    counts = np.empty((len(rows), T, 512), np.uint16)
    counts[np.searchsorted(sel, rows)] = 0
    tmp = X[sel]
    counts[:] = tmp[np.searchsorted(sel, rows)]
    labels = labels_all[rows]
    nev = meta["n_events"][rows].astype(np.int32)
    np.savez_compressed(VEC / "counts.npz", counts=counts, labels=labels, n_events=nev, N_e=(nev // T).astype(np.int32),
                        sample_id=np.array([f"rec{int(meta['rec'][r])}_w{int(meta['win'][r])}" for r in rows]))
    if not (VEC / "events.npz").exists():
        e = np.load(CACHE / "test_ev.npz")
        assert np.array_equal(e["row"], order[:len(e["row"])]) and len(e["row"]) >= a.n_rtl
        off = e["offset"][:a.n_rtl + 1]
        x, y, p = (e[k][:off[-1]].astype(np.uint32) for k in ("x", "y", "p"))
        aer = (p << 16) | (y << 8) | x
        addr = EV.address(x.astype(np.int64), y.astype(np.int64), p.astype(np.int64), H, W).astype(np.uint16)
        for i in range(0, a.n_rtl, 97):
            assert np.array_equal(EV.stream_counts(addr[off[i]:off[i + 1]], T), counts[i])
        n = np.diff(off).astype(np.int64)
        np.savez(VEC / "events.npz", aer=aer, addr=addr, offset=off.astype(np.int64), sample_row=np.arange(a.n_rtl, dtype=np.int32), n_events=n, N_e=(n // T).astype(np.int32),
                 remainder=(n % T).astype(np.int32), label=labels, aer_packing=np.array("p<<16 | y<<8 | x"))
    gate = {}
    seeds = [a.random] if a.random is not None else a.seeds
    for s in seeds:
        if a.random is not None:
            m = random_model(s, counts)
            rec = None
        elif a.model == "unf":
            m = quantize_base(torch.load(ART / f"base_seed{s}.pt", map_location="cpu"))
            rec = json.loads((ART / f"base_seed{s}.json").read_text())["test_acc"]
        else:
            m = quantize(torch.load(ART / f"{CKPT}{s}.pt", map_location="cpu"))
            rec = json.loads((ART / f"{CKPT}{s}.json").read_text())["test_acc"]
        hv = m["class_hv"] if a.model == "unf" and a.random is None else expand_r1(m["a_bits"], m["b_bits"])
        unf = a.model == "unf" and a.random is None
        # whole test split in chunks: accuracy and the widths the integer trace needs
        ok = 0; mx = dict(X=0, V=0)
        for i in range(0, len(order), 1000):
            r = np.sort(order[i:i + 1000])
            tr = snn_forward_batch(X[r].astype(np.int64), m["W"], m["thresh_int"])
            pf = np.stack([(prefix_scores(agree_unfactorized(tr.S[k], hv)) if unf else prefix_scores(agree_factorized(tr.S[k], m["a_bits"], m["b_bits"])))[-1] for k in range(len(r))])
            ok += int((pf.argmax(axis=1) == labels_all[r]).sum())
            mx["X"] = max(mx["X"], int(np.abs(tr.X).max())); mx["V"] = max(mx["V"], int(np.abs(tr.V).max()))
        acc = ok / len(order)
        tr = snn_forward_batch(counts.astype(np.int64), m["W"], m["thresh_int"])
        pu = np.stack([prefix_scores(agree_unfactorized(tr.S[k], hv)) for k in range(len(counts))])
        pf = pu if unf else np.stack([prefix_scores(agree_factorized(tr.S[k], m["a_bits"], m["b_bits"])) for k in range(len(counts))])
        pred = pu[:, -1].argmax(axis=1)
        tag = f"aslunfs{s}" if unf else f"aslr1s{s}"
        export_weight_image(str(Path(P.VECTOR_DIR) / "weights"), tag, m["W"], m["thresh_int"], 15)
        verify_image(str(Path(P.VECTOR_DIR) / "weights"), tag, m["W"])
        extra = {} if unf else dict(a_bits=m["a_bits"], b_bits=m["b_bits"])
        np.savez_compressed(VEC / (f"unf_seed{s}.npz" if unf else f"r1_seed{s}.npz"), thresh_int=np.tile(m["thresh_int"].astype(np.int32), (len(counts), 1)), X=tr.X.astype(np.int32), Vp=tr.Vp.astype(np.int32),
                            V=tr.V.astype(np.int32), spikes=tr.S.astype(np.uint8), pred=pred.astype(np.int8), score_xnor_prefix=pu.astype(np.int16), class_hv=hv, **extra)
        need = dict(W_X=int(mx["X"]).bit_length() + 1, W_V=int(mx["V"]).bit_length() + 1, W_THRESH=int(np.abs(m["thresh_int"]).max()).bit_length() + 1)
        gate[s] = dict(integer_accuracy_full_test=acc, n_test=len(order), float_test_acc=rec, match=(rec is not None and abs(acc - rec) < 1e-12), rtl_subset_accuracy=float((pred == labels).mean()),
                       factorized_equals_unfactorized=bool(np.array_equal(pu, pf)), v_thresh=m["v_thresh"], max_abs_X=mx["X"], max_abs_V=mx["V"], widths_needed=need, spike_rate=float(tr.S.mean()))
        print(s, gate[s], flush=True)
    (ART / ("export_gate_random.json" if a.random is not None else f"export_gate_{a.model}.json")).write_text(json.dumps(gate, indent=1))
    json.dump(dict(dataset="asldvs", n_samples=len(rows), T=T, n_neurons=N, n_classes=NCLS, split="random 80/20 (seed 0); RTL rows = the first n of the fixed random test order"), open(VEC / "manifest.json", "w"), indent=1)


if __name__ == "__main__":
    main()
