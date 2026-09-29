"""
Experiment 1 training driver: axis-factorized class hypervector.

Reuses the FROZEN training configuration from dvs_accuracy_report.md section 4
EXACTLY (input_scaling=raw, threshold calibration, per-channel int8 QAT,
Adam lr=1e-3, cosine schedule, batch 32, 200 epochs, weight_decay=1e-4,
event_dropout=0.1, label_smoothing=0, head_dropout=0, grad_clip_norm=0.5,
ATan alpha=2.0) and the same validation protocol (users 19-23 held out from
the 23 official training users; the 240-sample official test set is touched
exactly once per seed, after freezing). The ONLY thing that differs run to
run is the class-hypervector parameterization (rank R, factor_mode, init).

Usage:
  python train_factorized.py <run_name> --rank 4 --factor_mode binary \
      --init svd --baseline_seed 0 --seed 0 [--final_test]
"""
import sys
import os
import json
import time
import argparse
import numpy as np
import torch
from torch.utils.data import DataLoader

P1_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "phase1_firing_characterization", "src")
sys.path.insert(0, P1_SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from neurohdc import DVSGestureDataset, collate  # noqa: E402
from factorized_model import NeuroHDCFactorized  # noqa: E402

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # phase3_experiments/
P1_ROOT = os.path.join(os.path.dirname(ROOT), "phase1_firing_characterization")
DATA_ROOT = os.path.join(os.path.dirname(ROOT), "data")
ART = os.path.join(ROOT, "artifacts")

# IDENTICAL to phase1_firing_characterization/src/train_dvs.py's validation
# split -- users 19-23 held out, never the official test users 24-29.
ALL_TRAIN_USERS = [f"user{i:02d}" for i in range(1, 24)]
VAL_USERS = set(f"user{i:02d}" for i in range(19, 24))
SUBTRAIN_USERS = set(ALL_TRAIN_USERS) - VAL_USERS

# Frozen config, reused exactly (dvs_accuracy_report.md section 4)
FROZEN = dict(input_scaling="raw", weight_decay=1e-4, event_dropout=0.1,
              lr=1e-3, batch_size=32, epochs=200, grad_clip=0.5, alpha=2.0)


def evaluate(model, loader):
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for frames, labels, n_events, N_e in loader:
            frames, labels = frames.to(DEVICE), labels.to(DEVICE)
            scores, _ = model(frames)
            correct += (scores.argmax(1) == labels).sum().item()
            total += labels.shape[0]
    return correct / total


def build_loaders(seed):
    subtrain = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTrain", T=100,
                                  input_scaling=FROZEN["input_scaling"],
                                  event_dropout=FROZEN["event_dropout"], users=SUBTRAIN_USERS)
    val = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTrain", T=100,
                             input_scaling=FROZEN["input_scaling"], event_dropout=0.0, users=VAL_USERS)
    test = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTest", T=100,
                              input_scaling=FROZEN["input_scaling"], event_dropout=0.0)
    g = torch.Generator(); g.manual_seed(seed)
    subtrain_loader = DataLoader(subtrain, batch_size=FROZEN["batch_size"], shuffle=True,
                                  num_workers=6, collate_fn=collate, drop_last=True,
                                  persistent_workers=True, generator=g)
    val_loader = DataLoader(val, batch_size=64, shuffle=False, num_workers=3,
                             collate_fn=collate, persistent_workers=True)
    test_loader = DataLoader(test, batch_size=64, shuffle=False, num_workers=3,
                              collate_fn=collate, persistent_workers=True)
    return subtrain, val, test, subtrain_loader, val_loader, test_loader


def run(run_name, rank, factor_mode, init="svd", baseline_seed=0, seed=0,
        final_test=False, eval_every=5):
    torch.manual_seed(seed)
    np.random.seed(seed)

    subtrain, val, test, subtrain_loader, val_loader, test_loader = build_loaders(seed)

    model = NeuroHDCFactorized(n=20, T=100, n_input=512, n_classes=10,
                                alpha=FROZEN["alpha"], rank=rank, factor_mode=factor_mode).to(DEVICE)

    calib_batch = next(iter(subtrain_loader))[0].to(DEVICE)
    model.calibrate_threshold(calib_batch)

    init_source = None
    if init == "svd":
        base_ckpt = f"{P1_ROOT}/artifacts/dvs_accuracy/frozen_seed{baseline_seed}.pt"
        base_state = torch.load(base_ckpt, map_location=DEVICE)
        model.svd_init(base_state["Wc"])
        init_source = base_ckpt
    elif init == "random":
        pass  # A, B already randomly initialized in __init__
    else:
        raise ValueError(init)

    print(f"[{run_name}] rank={rank} mode={factor_mode} init={init} "
          f"bits={model.class_hv_bits()} subtrain={len(subtrain)} val={len(val)} "
          f"v_thresh_init={model.v_thresh.item():.4f}", flush=True)

    opt = torch.optim.Adam(model.parameters(), lr=FROZEN["lr"], weight_decay=FROZEN["weight_decay"])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=FROZEN["epochs"])
    loss_fn = torch.nn.CrossEntropyLoss()

    t0 = time.time()
    history = []
    best_val_acc, best_epoch, best_state = -1.0, -1, None
    for ep in range(FROZEN["epochs"]):
        model.train()
        tot_loss, tot_correct, tot_n = 0.0, 0, 0
        for frames, labels, n_events, N_e in subtrain_loader:
            frames, labels = frames.to(DEVICE), labels.to(DEVICE)
            opt.zero_grad()
            scores, raster = model(frames)
            loss = loss_fn(scores, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), FROZEN["grad_clip"])
            opt.step()
            tot_loss += loss.item() * labels.shape[0]
            tot_correct += (scores.argmax(1) == labels).sum().item()
            tot_n += labels.shape[0]
        sched.step()
        train_acc = tot_correct / tot_n
        row = dict(epoch=ep + 1, loss=tot_loss / tot_n, train_acc=train_acc)
        if (ep + 1) % eval_every == 0 or ep == FROZEN["epochs"] - 1:
            val_acc = evaluate(model, val_loader)
            row["val_acc"] = val_acc
            if val_acc > best_val_acc:
                best_val_acc, best_epoch = val_acc, ep + 1
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        history.append(row)
        if (ep + 1) % 20 == 0 or ep == FROZEN["epochs"] - 1:
            print(f"[{run_name}] epoch {ep+1}/{FROZEN['epochs']} loss={row['loss']:.4f} "
                  f"train_acc={train_acc:.4f}" + (f" val_acc={row.get('val_acc'):.4f}" if 'val_acc' in row else "")
                  + f" ({time.time()-t0:.0f}s)", flush=True)

    if best_state is not None:
        model.load_state_dict(best_state)
    print(f"[{run_name}] BEST val_acc={best_val_acc:.4f} @ epoch {best_epoch}", flush=True)

    test_acc = None
    if final_test:
        test_acc = evaluate(model, test_loader)
        print(f"[{run_name}] TEST test_acc={test_acc:.4f}", flush=True)

    os.makedirs(f"{ART}/checkpoints", exist_ok=True)
    torch.save(model.state_dict(), f"{ART}/checkpoints/{run_name}.pt")

    sidecar = dict(
        run_name=run_name, rank=rank, factor_mode=factor_mode, init=init,
        baseline_seed=baseline_seed if init == "svd" else None, init_source=init_source,
        seed=seed, class_hv_bits=model.class_hv_bits(),
        frozen_config=FROZEN, best_val_acc=best_val_acc, best_epoch=best_epoch,
        test_acc=test_acc, final_test_run=final_test,
        model_selection="best_val_epoch (test set untouched until final_test=True)",
        n_subtrain=len(subtrain), n_val=len(val), n_test=len(test),
        torch_version=torch.__version__, device=DEVICE,
        wall_time_sec=time.time() - t0, history=history,
    )
    os.makedirs(f"{ART}/tables", exist_ok=True)
    out_path = f"{ART}/tables/{run_name}.json"
    with open(out_path, "w") as f:
        json.dump(sidecar, f, indent=2)
    print(f"[{run_name}] wrote {out_path}")
    return sidecar


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_name")
    ap.add_argument("--rank", type=int, required=True)
    ap.add_argument("--factor_mode", required=True, choices=["fp", "binary"])
    ap.add_argument("--init", default="svd", choices=["svd", "random"])
    ap.add_argument("--baseline_seed", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--final_test", action="store_true")
    args = ap.parse_args()
    run(args.run_name, args.rank, args.factor_mode, init=args.init,
        baseline_seed=args.baseline_seed, seed=args.seed, final_test=args.final_test)
