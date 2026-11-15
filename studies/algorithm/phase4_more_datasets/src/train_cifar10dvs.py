"""Train the chip's model for CIFAR10-DVS: n = 20 IF neurons, T = 100, 512 inputs, int8 per-channel QAT, then the R = 1 binary factorized class HV (the chip's HDC store).

Same two steps and the same frozen hyper-parameters as DVS-Gesture (phase3 train_factorized.py FROZEN: raw input, Adam 1e-3, cosine, batch 32, weight decay 1e-4,
grad clip 0.5, ATan alpha 2, threshold calibration):
  stage 'base': unfactorized NeuroHDC (C = sign(Wc))                 -> checkpoint base_seed<k>.pt
  stage 'r1'  : NeuroHDCFactorized rank 1, binary, SVD init from base -> checkpoint r1_seed<k>.pt   (what the chip runs)
Differences from DVS-Gesture, all forced by the data size and disclosed:
  - epochs (8,100 training recordings instead of 769): --epochs, default 100 per stage
  - event dropout 0.1 is applied as binomial thinning of the binned counts (events are not re-binned); training-only augmentation
Model selection: validation = recordings 810..899 of every class (900), held out from training; the test split (900..999) is evaluated once, after selection.
   python studies/algorithm/phase4_more_datasets/src/train_cifar10dvs.py --stage base --seed 0
   python studies/algorithm/phase4_more_datasets/src/train_cifar10dvs.py --stage r1 --seed 0
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "design" / "reference_model" / "model" / "neurohdc"))
sys.path.insert(1, str(REPO / "studies" / "algorithm" / "phase3_experiments" / "src"))
from neurohdc import NeuroHDC  # noqa: E402
from factorized_model import NeuroHDCFactorized  # noqa: E402

CACHE = REPO / "datasets" / "cache" / "cifar10dvs"
ART = Path(__file__).resolve().parents[1] / "artifacts" / "cifar10dvs"
# --dataset asldvs (NeuroHDC-large: n = 40, 24 classes; prep_asldvs.py, random 80/20 split with a 10 % validation part) switches these
# --dataset cifar10dvs_large: CIFAR10-DVS on the large chip (n = 40, the 10 classes; the chip's other 14 class slots hold copies of class 0, which never win: ties keep the lower index)
DS = dict(cifar10dvs=dict(n=20, classes=10), asldvs=dict(n=40, classes=24), cifar10dvs_large=dict(n=40, classes=10, cache="cifar10dvs"))
FROZEN = dict(input_scaling="raw", weight_decay=1e-4, event_dropout=0.1, lr=1e-3, batch_size=32, grad_clip=0.5, alpha=2.0)


def splits():
    m = np.load(CACHE / "meta.npz")
    if "label" in m.files:                                 # asldvs
        sp = m["split"]
        return np.flatnonzero(sp == 0), np.flatnonzero(sp == 1), np.flatnonzero(sp == 2), m["label"].astype(np.int64)
    rec, split = m["rec"], m["split"]
    tr = np.flatnonzero((split == 0) & (rec < 810))
    va = np.flatnonzero((split == 0) & (rec >= 810))
    te = np.flatnonzero(split == 1)
    return tr, va, te, m["labels"].astype(np.int64)


def evaluate(model, X, y, idx, dev, bs=250):
    model.eval()
    ok = 0
    with torch.no_grad():
        for i in range(0, len(idx), bs):
            j = idx[i:i + bs]
            s, _ = model(torch.from_numpy(X[j].astype(np.float32)).to(dev))
            ok += int((s.argmax(1).cpu().numpy() == y[j]).sum())
    return ok / len(idx)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["base", "r1"], required=True)
    ap.add_argument("--dataset", choices=list(DS), default="cifar10dvs")
    ap.add_argument("--max-test", type=int, default=0, help="evaluate the test split on its first N samples of the fixed random order (0: all)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--eval-every", type=int, default=2)
    ap.add_argument("--lr", type=float, default=FROZEN["lr"])
    ap.add_argument("--fresh-ws", action="store_true", help="r1: start the SNN from fresh weights (as DVS-Gesture's r1 runs did) instead of the base checkpoint's")
    ap.add_argument("--name", default=None, help="checkpoint name (default: <stage>_seed<k>)")
    a = ap.parse_args()
    global CACHE, ART
    CACHE = REPO / "datasets" / "cache" / DS[a.dataset].get("cache", a.dataset)
    ART = Path(__file__).resolve().parents[1] / "artifacts" / a.dataset
    n, ncls = DS[a.dataset]["n"], DS[a.dataset]["classes"]
    torch.manual_seed(a.seed); np.random.seed(a.seed)
    torch.set_num_threads(3)
    dev = torch.device(a.device)
    X = np.load(CACHE / "counts.npy", mmap_mode="r" if a.dataset == "asldvs" else None)      # ASL-DVS: 4.9 GB, memory-mapped (page cache shared by parallel runs)
    tr, va, te, y = splits()
    if a.stage == "base":
        model = NeuroHDC(n=n, T=100, n_input=512, n_classes=ncls, alpha=FROZEN["alpha"]).to(dev)
    else:
        model = NeuroHDCFactorized(n=n, T=100, n_input=512, n_classes=ncls, alpha=FROZEN["alpha"], rank=1, factor_mode="binary").to(dev)
    rng = np.random.default_rng(a.seed)
    model.calibrate_threshold(torch.from_numpy(X[np.sort(rng.choice(tr, 32, replace=False))].astype(np.float32)).to(dev))
    if a.max_test:
        te = np.load(CACHE / "meta.npz")["test_order"][:a.max_test]
    init = None
    if a.stage == "r1":
        base = torch.load(ART / f"base_seed{a.seed}.pt", map_location="cpu")
        model.svd_init(base["Wc"])
        if not a.fresh_ws:
          with torch.no_grad():                              # start the SNN from the trained base too (DVS-Gesture's r1 started from fresh Ws; here the base Ws is reused to save epochs)
            model.Ws.copy_(base["Ws"]); model._v_thresh_raw.copy_(base["_v_thresh_raw"])
        init = str(ART / f"base_seed{a.seed}.pt")
    opt = torch.optim.Adam(model.parameters(), lr=a.lr, weight_decay=FROZEN["weight_decay"])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)
    loss_fn = torch.nn.CrossEntropyLoss()
    keep = 1.0 - FROZEN["event_dropout"]
    t0 = time.time()
    hist, best = [], (-1.0, -1, None)
    for ep in range(a.epochs):
        model.train()
        perm = rng.permutation(tr)
        tl = tc = tn = 0
        for i in range(0, len(perm) - FROZEN["batch_size"] + 1, FROZEN["batch_size"]):
            j = np.sort(perm[i:i + FROZEN["batch_size"]])
            c = torch.from_numpy(X[j].astype(np.float32))
            c = torch.binomial(c, torch.full_like(c, keep))
            lab = torch.from_numpy(y[j]).to(dev)
            opt.zero_grad()
            s, _ = model(c.to(dev))
            loss = loss_fn(s, lab)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), FROZEN["grad_clip"])
            opt.step()
            tl += loss.item() * len(j); tc += int((s.argmax(1) == lab).sum()); tn += len(j)
        sched.step()
        row = dict(epoch=ep + 1, loss=tl / tn, train_acc=tc / tn)
        if (ep + 1) % a.eval_every == 0 or ep == a.epochs - 1:
            row["val_acc"] = evaluate(model, X, y, va, dev)
            if row["val_acc"] > best[0]:
                best = (row["val_acc"], ep + 1, {k: v.detach().clone() for k, v in model.state_dict().items()})
        hist.append(row)
        print(f"[{a.stage} s{a.seed}] ep {ep + 1}/{a.epochs} loss {row['loss']:.4f} train {row['train_acc']:.4f}" + (f" val {row['val_acc']:.4f}" if "val_acc" in row else "") + f" ({time.time() - t0:.0f}s)", flush=True)
    model.load_state_dict(best[2])
    test_acc = evaluate(model, X, y, te, dev)
    print(f"[{a.stage} s{a.seed}] BEST val {best[0]:.4f} @ ep {best[1]}  TEST {test_acc:.4f}", flush=True)
    ART.mkdir(parents=True, exist_ok=True)
    nm = a.name or f"{a.stage}_seed{a.seed}"
    torch.save({k: v.cpu() for k, v in model.state_dict().items()}, ART / f"{nm}.pt")
    (ART / f"{nm}.json").write_text(json.dumps(dict(stage=a.stage, seed=a.seed, epochs=a.epochs, frozen_config=FROZEN, lr=a.lr, fresh_ws=a.fresh_ws, init=init, best_val_acc=best[0], best_epoch=best[1],
                                                                       test_acc=test_acc, n_train=len(tr), n_val=len(va), n_test=len(te), v_thresh=float(model.v_thresh.item()),
                                                                       device=a.device, torch_version=torch.__version__, wall_time_sec=time.time() - t0, history=hist), indent=1))


if __name__ == "__main__":
    main()
