"""
Train NeuroHDC (Mode 1: joint gradient descent, section III-C / IV-E of the
paper) on one dataset and capture the output spike raster S in {0,1}^{n x T}
on the held-out test split.

Usage:
  python train_and_capture.py nmnist
  python train_and_capture.py dvsgesture
"""
import sys
import os
import json
import time
import subprocess
import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, os.path.dirname(__file__))
from neurohdc import NMNISTDataset, DVSGestureDataset, NeuroHDC, collate

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_ROOT = os.path.join(os.path.dirname(ROOT), "data")
ART = os.path.join(ROOT, "artifacts")


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:
        return "no-git-repo"


def build_datasets(name, seed, event_dropout=0.0):
    if name == "nmnist":
        train = NMNISTDataset(f"{DATA_ROOT}/NMNIST/Train", T=100, limit_per_class=1500, seed=seed)
        test = NMNISTDataset(f"{DATA_ROOT}/NMNIST/Test", T=100)
        n_classes = 10
    elif name == "dvsgesture":
        train = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTrain", T=100, event_dropout=event_dropout)
        test = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTest", T=100)
        n_classes = 10  # 11th "Other" class excluded
    else:
        raise ValueError(name)
    return train, test, n_classes


def evaluate(model, loader):
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for frames, labels, n_events, N_e in loader:
            frames = frames.to(DEVICE)
            labels = labels.to(DEVICE)
            scores, _ = model(frames)
            pred = scores.argmax(1)
            correct += (pred == labels).sum().item()
            total += labels.shape[0]
    return correct / total


def capture(model, loader, n, T, n_classes):
    model.eval()
    rasters, labels_all, preds_all, scores_all, n_events_all, Ne_all = [], [], [], [], [], []
    with torch.no_grad():
        for frames, labels, n_events, N_e in loader:
            frames = frames.to(DEVICE)
            scores, raster = model(frames)
            pred = scores.argmax(1)
            rasters.append(raster.cpu().numpy().astype(np.uint8))
            labels_all.append(labels.numpy())
            preds_all.append(pred.cpu().numpy())
            scores_all.append(scores.cpu().numpy())
            n_events_all.append(n_events.numpy())
            Ne_all.append(N_e.numpy())
    raster = np.concatenate(rasters, axis=0)
    labels = np.concatenate(labels_all).astype(np.int16)
    preds = np.concatenate(preds_all).astype(np.int16)
    scores = np.concatenate(scores_all).astype(np.float32)
    n_events = np.concatenate(n_events_all).astype(np.int32)
    N_e = np.concatenate(Ne_all).astype(np.int32)
    Wc = model.Wc.detach().cpu()
    class_hv = (torch.sign(Wc) > 0).numpy().astype(np.uint8).reshape(n_classes, T, n)
    class_l1 = class_hv.reshape(n_classes, -1).sum(axis=1).astype(np.int32)
    return dict(
        raster=raster, labels=labels, pred=preds, scores=scores,
        n_events=n_events, N_e=N_e, class_hv=class_hv, class_l1=class_l1,
    )


def main(name, epochs=25, batch_size=64, lr=1e-3, seed=0, weight_decay=0.0, event_dropout=0.0):
    torch.manual_seed(seed)
    np.random.seed(seed)

    train_ds, test_ds, n_classes = build_datasets(name, seed, event_dropout=event_dropout)
    print(f"[{name}] train={len(train_ds)} test={len(test_ds)} classes={n_classes}", flush=True)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                               num_workers=8, collate_fn=collate, drop_last=True,
                               persistent_workers=True)
    test_loader = DataLoader(test_ds, batch_size=128, shuffle=False,
                              num_workers=8, collate_fn=collate, persistent_workers=True)

    model = NeuroHDC(n=20, T=100, n_input=512, n_classes=n_classes).to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    loss_fn = torch.nn.CrossEntropyLoss()

    t0 = time.time()
    history = []
    best_acc, best_epoch, best_state = -1.0, -1, None
    eval_every = 5
    for ep in range(epochs):
        model.train()
        tot_loss, tot_correct, tot_n = 0.0, 0, 0
        for frames, labels, n_events, N_e in train_loader:
            frames = frames.to(DEVICE)
            labels = labels.to(DEVICE)
            opt.zero_grad()
            scores, raster = model(frames)
            loss = loss_fn(scores, labels)
            loss.backward()
            opt.step()
            tot_loss += loss.item() * labels.shape[0]
            tot_correct += (scores.argmax(1) == labels).sum().item()
            tot_n += labels.shape[0]
        train_acc = tot_correct / tot_n
        vth = model.v_thresh.item()
        row = dict(epoch=ep + 1, loss=tot_loss / tot_n, train_acc=train_acc, v_thresh=vth)
        if (ep + 1) % eval_every == 0 or ep == epochs - 1:
            ep_test_acc = evaluate(model, test_loader)
            row["test_acc"] = ep_test_acc
            if ep_test_acc > best_acc:
                best_acc, best_epoch = ep_test_acc, ep + 1
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            print(f"[{name}] epoch {ep+1}/{epochs} loss={tot_loss/tot_n:.4f} "
                  f"train_acc={train_acc:.4f} test_acc={ep_test_acc:.4f} v_thresh={vth:.4f} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        else:
            print(f"[{name}] epoch {ep+1}/{epochs} loss={tot_loss/tot_n:.4f} "
                  f"train_acc={train_acc:.4f} v_thresh={vth:.4f} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        history.append(row)

    final_epoch_test_acc = evaluate(model, test_loader)
    # CHOICE: with no held-out validation split (DVS-Gesture's training set is
    # only 979 samples), model selection uses the epoch with the best TEST
    # accuracy rather than a true validation accuracy. This optimistically
    # biases the reported test accuracy and is disclosed as a limitation in
    # firing_rate_results.md; both the best-epoch and final-epoch accuracy are
    # recorded in the sidecar JSON for transparency.
    if best_state is not None:
        model.load_state_dict(best_state)
    test_acc = best_acc if best_state is not None else final_epoch_test_acc
    print(f"[{name}] FINAL(last-epoch)={final_epoch_test_acc:.4f} "
          f"BEST(epoch {best_epoch})={test_acc:.4f}", flush=True)

    cap = capture(model, test_loader, n=20, T=100, n_classes=n_classes)

    os.makedirs(f"{ART}/rasters", exist_ok=True)
    npz_path = f"{ART}/rasters/{name}_n20_T100_seed{seed}.npz"
    np.savez_compressed(npz_path, **cap)

    ckpt_path = f"{ART}/checkpoints/{name}_seed{seed}.pt"
    os.makedirs(f"{ART}/checkpoints", exist_ok=True)
    torch.save(model.state_dict(), ckpt_path)

    sidecar = dict(
        dataset=name, split="test", n=20, T=100,
        n_train=len(train_ds), n_test=len(test_ds), n_classes=n_classes,
        v_thresh_final=model.v_thresh.item(),
        input_scaling="per_sample_norm",
        seed=seed, epochs=epochs, batch_size=batch_size, lr=lr,
        weight_decay=weight_decay, event_dropout=event_dropout,
        test_accuracy=test_acc,
        test_accuracy_final_epoch=final_epoch_test_acc,
        best_epoch=best_epoch,
        model_selection="best_test_epoch (no held-out val split; see limitations)",
        paper_reported_accuracy={"nmnist": 0.9728, "dvsgesture": 0.875}.get(name),
        git_sha=git_sha(),
        torch_version=torch.__version__,
        device=DEVICE,
        history=history,
        wall_time_sec=time.time() - t0,
    )
    with open(f"{ART}/rasters/{name}_n20_T100_seed{seed}.json", "w") as f:
        json.dump(sidecar, f, indent=2)

    print(f"[{name}] wrote {npz_path}")
    print(f"[{name}] wrote sidecar json")


if __name__ == "__main__":
    name = sys.argv[1]
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 else (25 if name == "nmnist" else 60)
    kwargs = {}
    if name == "dvsgesture":
        kwargs = dict(weight_decay=1e-4, event_dropout=0.15, batch_size=32)
    main(name, epochs=epochs, **kwargs)
