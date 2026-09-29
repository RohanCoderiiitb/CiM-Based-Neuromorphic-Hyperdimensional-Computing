"""
Systematic DVS-Gesture accuracy-improvement training, per
neurohdc_implementation_audit.md Part B and dvs_accuracy_report.md.

Rules enforced here:
  1. Everything the paper specifies (IF neuron, V_reset=0, T=100, n=20,
     D_hv=2000, Adam, equal-event-count binning, 8-bit QAT, Sign() class-HV
     head with STE, "Other" class excluded) is preserved unchanged -- see
     neurohdc_implementation_audit.md Part A.
  2. Every parameter this script exposes as a CLI flag is one the paper does
     not specify numerically (Part B); values chosen here are OUR CHOICE,
     documented in dvs_accuracy_report.md, never claimed as [S].
  3. The TEST split is never touched until final_test=True. All model
     selection and all of Phase 2's systematic experiments use a validation
     split carved from the TRAINING users only (never the official test
     users).
  4. Every run's exact configuration is written to a sidecar JSON.

Usage:
  python train_dvs.py <run_name> [--weight_decay 1e-4] [--event_dropout 0.15]
                        [--epochs 200] [--lr 1e-3] [--seed 0] [--final_test]
"""
import sys
import os
import json
import time
import argparse
import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, os.path.dirname(__file__))
from neurohdc import DVSGestureDataset, NeuroHDC, collate

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_ROOT = os.path.join(os.path.dirname(ROOT), "data")
ART = os.path.join(ROOT, "artifacts", "dvs_accuracy")

# Held-out validation users: the LAST 5 of the 23 official training users
# (user19-user23), never the official test users (user24-29). exp7 tried
# narrowing this to 3 users (852 subtrain/130 val) to test whether more
# training data would help; the result (70.8%) was statistically
# indistinguishable from the 5-user split's ~75% given the val set shrank to
# 13 samples/class, so that change is reverted -- the 5-user split is kept
# for the rest of Phase 2 as the better-powered, less noisy validation
# estimate. exp7 is documented in dvs_accuracy_report.md as an inconclusive,
# reverted experiment, not deleted.
ALL_TRAIN_USERS = [f"user{i:02d}" for i in range(1, 24)]
VAL_USERS = set(f"user{i:02d}" for i in range(19, 24))
SUBTRAIN_USERS = set(ALL_TRAIN_USERS) - VAL_USERS


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


def build_loaders(input_scaling, event_dropout, batch_size, seed):
    subtrain = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTrain", T=100,
                                  input_scaling=input_scaling, event_dropout=event_dropout,
                                  users=SUBTRAIN_USERS)
    val = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTrain", T=100,
                             input_scaling=input_scaling, event_dropout=0.0,
                             users=VAL_USERS)
    test = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTest", T=100,
                              input_scaling=input_scaling, event_dropout=0.0)

    g = torch.Generator()
    g.manual_seed(seed)
    subtrain_loader = DataLoader(subtrain, batch_size=batch_size, shuffle=True,
                                  num_workers=8, collate_fn=collate, drop_last=True,
                                  persistent_workers=True, generator=g)
    val_loader = DataLoader(val, batch_size=64, shuffle=False,
                             num_workers=4, collate_fn=collate, persistent_workers=True)
    test_loader = DataLoader(test, batch_size=64, shuffle=False,
                              num_workers=4, collate_fn=collate, persistent_workers=True)
    return subtrain, val, test, subtrain_loader, val_loader, test_loader


def run(run_name, input_scaling="raw", event_dropout=0.0, weight_decay=0.0,
        epochs=150, batch_size=32, lr=1e-3, seed=0, eval_every=5,
        calibrate=True, lr_schedule=None, label_smoothing=0.0, head_dropout=0.0,
        grad_clip=0.0, final_test=False):
    torch.manual_seed(seed)
    np.random.seed(seed)

    subtrain, val, test, subtrain_loader, val_loader, test_loader = build_loaders(
        input_scaling, event_dropout, batch_size, seed)
    print(f"[{run_name}] subtrain={len(subtrain)} val={len(val)} test={len(test)}", flush=True)

    model = NeuroHDC(n=20, T=100, n_input=512, n_classes=10, head_dropout=head_dropout).to(DEVICE)

    if calibrate:
        calib_batch = next(iter(subtrain_loader))[0].to(DEVICE)
        model.calibrate_threshold(calib_batch)
        print(f"[{run_name}] calibrated v_thresh_init={model.v_thresh.item():.4f}", flush=True)

    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    sched = None
    if lr_schedule == "cosine":
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    loss_fn = torch.nn.CrossEntropyLoss(label_smoothing=label_smoothing)

    t0 = time.time()
    history = []
    best_val_acc, best_epoch, best_state = -1.0, -1, None
    for ep in range(epochs):
        model.train()
        tot_loss, tot_correct, tot_n = 0.0, 0, 0
        for frames, labels, n_events, N_e in subtrain_loader:
            frames, labels = frames.to(DEVICE), labels.to(DEVICE)
            opt.zero_grad()
            scores, raster = model(frames)
            loss = loss_fn(scores, labels)
            loss.backward()
            if grad_clip > 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            opt.step()
            tot_loss += loss.item() * labels.shape[0]
            tot_correct += (scores.argmax(1) == labels).sum().item()
            tot_n += labels.shape[0]
        if sched is not None:
            sched.step()
        train_acc = tot_correct / tot_n
        row = dict(epoch=ep + 1, loss=tot_loss / tot_n, train_acc=train_acc,
                   v_thresh=model.v_thresh.item(), lr=opt.param_groups[0]["lr"])
        if (ep + 1) % eval_every == 0 or ep == epochs - 1:
            val_acc = evaluate(model, val_loader)
            row["val_acc"] = val_acc
            if val_acc > best_val_acc:
                best_val_acc, best_epoch = val_acc, ep + 1
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            print(f"[{run_name}] epoch {ep+1}/{epochs} loss={tot_loss/tot_n:.4f} "
                  f"train_acc={train_acc:.4f} val_acc={val_acc:.4f} "
                  f"v_thresh={row['v_thresh']:.4f} ({time.time()-t0:.0f}s)", flush=True)
        else:
            print(f"[{run_name}] epoch {ep+1}/{epochs} loss={tot_loss/tot_n:.4f} "
                  f"train_acc={train_acc:.4f} v_thresh={row['v_thresh']:.4f} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        history.append(row)

    if best_state is not None:
        model.load_state_dict(best_state)
    print(f"[{run_name}] BEST val_acc={best_val_acc:.4f} at epoch {best_epoch} "
          f"(selected without ever touching the test set)", flush=True)

    test_acc = None
    if final_test:
        test_acc = evaluate(model, test_loader)
        print(f"[{run_name}] FINAL TEST test_acc={test_acc:.4f}", flush=True)

    os.makedirs(ART, exist_ok=True)
    sidecar = dict(
        run_name=run_name, dataset="dvsgesture", n=20, T=100,
        input_scaling=input_scaling, event_dropout=event_dropout,
        weight_decay=weight_decay, calibrate_threshold=calibrate,
        lr_schedule=lr_schedule, label_smoothing=label_smoothing, head_dropout=head_dropout,
        grad_clip=grad_clip, epochs=epochs, batch_size=batch_size, lr=lr, seed=seed,
        n_subtrain=len(subtrain), n_val=len(val), n_test=len(test),
        subtrain_users=sorted(SUBTRAIN_USERS), val_users=sorted(VAL_USERS),
        best_val_acc=best_val_acc, best_epoch=best_epoch,
        test_acc=test_acc, final_test_run=final_test,
        model_selection="best_val_epoch (test set untouched until final_test=True)",
        paper_reported_accuracy=0.875,
        torch_version=torch.__version__, device=DEVICE,
        wall_time_sec=time.time() - t0, history=history,
    )
    out_path = f"{ART}/{run_name}.json"
    with open(out_path, "w") as f:
        json.dump(sidecar, f, indent=2)
    print(f"[{run_name}] wrote {out_path}")

    ckpt_path = f"{ART}/{run_name}.pt"
    torch.save(model.state_dict(), ckpt_path)
    return sidecar, model


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_name")
    ap.add_argument("--input_scaling", default="raw", choices=["raw", "per_sample_norm", "clip"])
    ap.add_argument("--event_dropout", type=float, default=0.0)
    ap.add_argument("--weight_decay", type=float, default=0.0)
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--batch_size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--lr_schedule", default=None, choices=[None, "cosine"])
    ap.add_argument("--label_smoothing", type=float, default=0.0)
    ap.add_argument("--head_dropout", type=float, default=0.0)
    ap.add_argument("--grad_clip", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no_calibrate", action="store_true")
    ap.add_argument("--final_test", action="store_true")
    args = ap.parse_args()
    run(args.run_name, input_scaling=args.input_scaling, event_dropout=args.event_dropout,
        weight_decay=args.weight_decay, epochs=args.epochs, batch_size=args.batch_size,
        lr=args.lr, lr_schedule=args.lr_schedule, label_smoothing=args.label_smoothing,
        head_dropout=args.head_dropout, grad_clip=args.grad_clip, seed=args.seed,
        calibrate=not args.no_calibrate, final_test=args.final_test)
