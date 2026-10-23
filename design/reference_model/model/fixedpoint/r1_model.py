"""
The R=1 factorized model (Phase 3 experiment 1, `r1_binary_svd_seed{0,1,2}`): integer extraction, the Phase 0 gate for it, and the golden-vector export for Phases 2-4.

The checkpoint holds the SNN weights Ws (trained jointly with the factors), v_thresh, and the class-HV factors A [N,1,20] and B [N,1,100]; the class hypervector is
C_i[t,j] = sign(sign(A_i[j]) * sign(B_i[t])). In bits (1 == +1): a_i[j] = A > 0, b_i[t] = B > 0, C = XNOR(a, b).

Gate (like Phase 0's): the integer pipeline - int8 weights, exact-ceil thresholds, integer SNN, factorized scoring - must reproduce the recorded test accuracy of the float
checkpoint (the sidecar JSON `test_acc`) exactly. It is the same quantizer (per-channel, the default of the frozen training configuration the runs reused).
Usage: python model/fixedpoint/r1_model.py        (re-exports tb/vectors/dvsgesture/r1_seed*.npz and tb/vectors/weights/*r1s*)
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths as P  # noqa: E402
sys.path.insert(0, os.path.join(P.MODEL_DIR, "export"))
from export_weights import export_weight_image, verify_image  # noqa: E402
from export_vectors import sha256  # noqa: E402
from hdc_query import agree_factorized, agree_unfactorized, expand_r1, prefix_scores  # noqa: E402
from int_model import snn_forward_batch  # noqa: E402
from quantize import thresholds  # noqa: E402

W_THRESH = 15
CKPT = lambda s: f"{P.CKPT_DIR}/r1_binary_svd_seed{s}.pt"      # noqa: E731
TAG = lambda s: f"r1s{s}"                                       # noqa: E731  weight-image tag (files weights_seedr1s0_*.mem)


def load_r1(seed: int, per_channel: bool = True) -> dict:
    sd = torch.load(CKPT(seed), map_location="cpu")
    Ws = sd["Ws"].float()
    scale_t = (Ws.abs().amax(dim=1, keepdim=True).clamp_min(1e-8) if per_channel else Ws.abs().max().clamp_min(1e-8)) / 127.0      # identical torch ops to neurohdc.fake_quant_int8
    q = torch.round(Ws / scale_t).clamp(-127, 127)
    v_thresh = float((torch.nn.functional.softplus(sd["_v_thresh_raw"]) + 1e-3).item())
    scale = np.broadcast_to(scale_t.reshape(-1).numpy(), (Ws.shape[0],)).astype(np.float32)
    A, B = sd["A"][:, 0, :], sd["B"][:, 0, :]
    sa, sb = torch.sign(A), torch.sign(B)
    assert not (sa == 0).any() and not (sb == 0).any(), "a factor is exactly zero: the sign is undefined"
    return dict(W=q.numpy().astype(np.int8), scale=scale, v_thresh=v_thresh, thresh_int=thresholds(v_thresh, scale), a_bits=(sa > 0).numpy().astype(np.uint8),
                b_bits=(sb > 0).numpy().astype(np.uint8))


def run(seed: int, counts: np.ndarray, labels: np.ndarray) -> dict:
    m = load_r1(seed)
    tr = snn_forward_batch(counts.astype(np.int64), m["W"], m["thresh_int"])
    S = tr.S                                                                                    # [S,100,20]
    hv = expand_r1(m["a_bits"], m["b_bits"])
    prefix_u = np.stack([prefix_scores(agree_unfactorized(S[i], hv)) for i in range(len(S))])  # [S,100,10]
    prefix_f = np.stack([prefix_scores(agree_factorized(S[i], m["a_bits"], m["b_bits"])) for i in range(len(S))])
    pred = prefix_u[:, -1].argmax(axis=1)
    return dict(model=m, trace=tr, class_hv=hv, prefix=prefix_u, identical_scores=bool(np.array_equal(prefix_u, prefix_f)), pred=pred, acc=float((pred == labels).mean()))


def main() -> None:
    c = np.load(f"{P.VECTOR_DIR}/dvsgesture/counts.npz")
    counts, labels = c["counts"], c["labels"].astype(int)
    out = {}
    for s in (0, 1, 2):
        r = run(s, counts, labels)
        rec = json.load(open(f"{P.CKPT_DIR}/r1_binary_svd_seed{s}.json"))["test_acc"]
        ok = abs(r["acc"] - rec) < 1e-12
        print(f"r1 seed {s}: integer pipeline accuracy {r['acc']:.4f} ({round(r['acc'] * 240)}/240), recorded float test_acc {rec:.4f} -> {'MATCH' if ok else 'MISMATCH'};"
              f" factorized == unfactorized scores on all {len(counts)} x 100 prefixes: {r['identical_scores']}")
        assert ok and r["identical_scores"]
        m = r["model"]
        wdir = f"{P.VECTOR_DIR}/weights"
        export_weight_image(wdir, TAG(s), m["W"], m["thresh_int"], W_THRESH)
        verify_image(wdir, TAG(s), m["W"])
        tr = r["trace"]
        np.savez_compressed(f"{P.VECTOR_DIR}/dvsgesture/r1_seed{s}.npz", thresh_int=np.tile(m["thresh_int"].astype(np.int32), (len(counts), 1)), X=tr.X.astype(np.int32),
                            Vp=tr.Vp.astype(np.int32), V=tr.V.astype(np.int32), spikes=tr.S.astype(np.uint8), pred=r["pred"].astype(np.int8),
                            score_xnor_prefix=r["prefix"].astype(np.int16), a_bits=m["a_bits"], b_bits=m["b_bits"], class_hv=r["class_hv"])
        out[s] = dict(accuracy=r["acc"], recorded=rec, v_thresh=m["v_thresh"], thresh_int=[int(t) for t in m["thresh_int"]],
                      npz_sha256=sha256(f"{P.VECTOR_DIR}/dvsgesture/r1_seed{s}.npz"))
    json.dump(out, open(f"{P.OUT_DIR}/r1_gate.json", "w"), indent=1)


if __name__ == "__main__":
    main()
