"""
Phase 4: capture the output spike raster S in {0,1}^{20x100} from the FROZEN,
accuracy-improved DVS-Gesture NeuroHDC model (dvs_accuracy_report.md), on the
full official test split (240 samples, 240 events already excludes the
11th "Other" class).

Run for all 3 frozen seeds (checkpoints already trained and saved under
artifacts/dvs_accuracy/frozen_seed{0,1,2}.pt) so cross-seed consistency of
the firing-rate statistics can be checked, not just a single run.

Output written in the same schema as the original (now-superseded) capture,
under a new name so the old artifacts are preserved, not overwritten:
  artifacts/rasters/dvsgesture_frozen_seed{s}.npz  (+ .json sidecar)
"""
import sys
import os
import json
import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, os.path.dirname(__file__))
from neurohdc import DVSGestureDataset, NeuroHDC, collate

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_ROOT = os.path.join(os.path.dirname(ROOT), "data")
ART = os.path.join(ROOT, "artifacts")

FROZEN_CONFIG = dict(
    input_scaling="raw", weight_decay=1e-4, event_dropout=0.1,
    lr_schedule="cosine", grad_clip=0.5, lr=1e-3, batch_size=32, epochs=200,
    calibrate_threshold=True, quantization="per_channel int8",
)


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
    correct = (labels == preds).mean()
    return dict(
        raster=raster, labels=labels, pred=preds, scores=scores,
        n_events=n_events, N_e=N_e, class_hv=class_hv, class_l1=class_l1,
    ), float(correct)


def main():
    test = DVSGestureDataset(f"{DATA_ROOT}/DVSGesture/ibmGestureTest", T=100,
                              input_scaling=FROZEN_CONFIG["input_scaling"], event_dropout=0.0)
    test_loader = DataLoader(test, batch_size=64, shuffle=False, num_workers=4, collate_fn=collate)
    print(f"test={len(test)}")

    test_accs = []
    for seed in [0, 1, 2]:
        ckpt_path = f"{ART}/dvs_accuracy/frozen_seed{seed}.pt"
        sidecar_path = f"{ART}/dvs_accuracy/frozen_seed{seed}.json"
        with open(sidecar_path) as f:
            train_sidecar = json.load(f)

        model = NeuroHDC(n=20, T=100, n_input=512, n_classes=10).to(DEVICE)
        model.load_state_dict(torch.load(ckpt_path, map_location=DEVICE))

        cap, test_acc = capture(model, test_loader, n=20, T=100, n_classes=10)
        print(f"[seed{seed}] recomputed test_acc={test_acc:.4f} "
              f"(training-time recorded test_acc={train_sidecar['test_acc']:.4f})")
        assert abs(test_acc - train_sidecar["test_acc"]) < 1e-6, "capture must reproduce training-time test accuracy exactly"
        test_accs.append(test_acc)

        os.makedirs(f"{ART}/rasters", exist_ok=True)
        npz_path = f"{ART}/rasters/dvsgesture_frozen_n20_T100_seed{seed}.npz"
        np.savez_compressed(npz_path, **cap)

        sidecar = dict(
            dataset="dvsgesture_frozen", split="test", n=20, T=100,
            status="CURRENT -- supersedes dvsgesture_n20_T100_seed0 (58-60% accuracy, provisional)",
            n_test=len(test), n_classes=10,
            frozen_config=FROZEN_CONFIG,
            v_thresh_final=model.v_thresh.item(),
            seed=seed, test_accuracy=test_acc,
            best_val_acc=train_sidecar["best_val_acc"], best_epoch=train_sidecar["best_epoch"],
            n_subtrain=train_sidecar["n_subtrain"], n_val=train_sidecar["n_val"],
            paper_reported_accuracy=0.875,
            torch_version=torch.__version__, device=DEVICE,
        )
        with open(f"{ART}/rasters/dvsgesture_frozen_n20_T100_seed{seed}.json", "w") as f:
            json.dump(sidecar, f, indent=2)
        print(f"[seed{seed}] wrote {npz_path}")

    print(f"\nMean test_acc={np.mean(test_accs):.4f} std={np.std(test_accs):.4f}")


if __name__ == "__main__":
    main()
