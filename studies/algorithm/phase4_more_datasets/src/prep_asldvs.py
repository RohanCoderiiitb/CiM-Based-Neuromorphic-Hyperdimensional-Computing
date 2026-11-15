"""ASL-DVS (raw release: one jAER AEDAT 2.0 recording per subject and letter, DAVIS240C, 240 x 180) -> NeuroHDC count tensors.

Segmentation: consecutive, non-overlapping 100 ms windows of every recording (the published ASL-DVS samples are ~100 ms; 120 recordings x ~790 windows ~= the published 100,800).
Our windows are not the published sample boundaries; windows with fewer than T = 100 events are dropped. Files: the 24 letters a..y without j (static handshapes), one
recording per subject and letter. The extra takes a1, b1, g1, l_1, xtrash and z are not used.
DAVIS address word: DVS event iff bit 31 = 0 and bit 10 = 0; x = (a >> 12) & 1023, y = (a >> 22) & 511, p = (a >> 11) & 1.
Address rule: NeuroHDC eq. 19 on the full frame (H = 180, W = 240): addr = p*256 + floor(16 y / 180)*16 + floor(16 x / 240). Timestep rule: the reference floor(k T / n).
Split (the paper's protocol): random 80/20 over samples, seed 0; validation = a random 10 % of the training part.

Outputs (datasets/cache/asldvs/, gitignored):
  counts.npy   uint16 [N, 100, 512]; max_count recorded (the chip counter is 11 bits)
  meta.npz     label, subject, recording id, window index, n_events, split (0 train, 1 val, 2 test)
  test_ev.npz  x, y, p (uint8) of the first --n-test-events test samples in a fixed random order (the RTL streams), offsets, rows
   python -I studies/algorithm/phase4_more_datasets/src/prep_asldvs.py
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "design" / "reference_model" / "model" / "fixedpoint"))
import events as EV  # noqa: E402

SRC = REPO / "datasets" / "ASL-DVS"
OUT = REPO / "datasets" / "cache" / "asldvs"
LETTERS = [c for c in "abcdefghiklmnopqrstuvwxy"]          # 24 classes, j and z excluded (they need motion)
T, H, W, WIN_US, MIN_EV = 100, 180, 240, 100_000, 100


def recordings():
    out = []
    for f in sorted(SRC.glob("*/subject*/*.aedat")):
        if f.stem in LETTERS:
            out.append((int(f.parent.name.replace("subject", "")), LETTERS.index(f.stem), f))
    out.sort(key=lambda r: (r[0], r[1]))
    keys = [(s, l) for s, l, _ in out]
    assert len(keys) == len(set(keys)), "two recordings for one subject and letter"
    return out


def read_dvs(path: Path):
    raw = path.read_bytes()
    pos = 0
    while raw.startswith(b"#", pos):
        pos = raw.index(b"\n", pos) + 1
    best = None
    for k in range(8):                                     # one recording (subject2/k) has its event records 7 bytes after the header end: pick the record alignment
        d = np.frombuffer(raw, ">u4", offset=pos + k, count=(len(raw) - pos - k) // 8 * 2).reshape(-1, 2)
        a0, t0 = d[:, 0].astype(np.int64), d[:, 1].astype(np.int64)
        ok = float(((((a0 >> 31) & 1) == 0) & (((a0 >> 12) & 1023) < W) & (((a0 >> 22) & 511) < H)).mean())
        if best is None or ok > best[0]:
            best = (ok, a0, t0)
    assert best[0] > 0.999, f"{path}: no record alignment gives valid DVS events ({best[0]:.3f})"
    a, t = best[1], best[2]
    k = (((a >> 31) & 1) == 0) & (((a >> 10) & 1) == 0) & (((a >> 12) & 1023) < W) & (((a >> 22) & 511) < H)
    a, t = a[k], t[k]
    o = np.argsort(t, kind="stable")
    a, t = a[o], t[o]
    return (a >> 12) & 1023, (a >> 22) & 511, (a >> 11) & 1, t


def windows(t):
    w = (t - t[0]) // WIN_US
    nwin = int(w[-1])                                     # the last (partial) window is dropped
    starts = np.searchsorted(w, np.arange(nwin + 1))
    return [(int(starts[i]), int(starts[i + 1])) for i in range(nwin) if starts[i + 1] - starts[i] >= MIN_EV]


def do_rec(arg):
    rid, (subj, lab, path) = arg
    x, y, p, t = read_dvs(path)
    assert x.max() < W and y.max() < H
    addr = EV.address(x, y, p, H, W)
    win = windows(t)
    c = np.zeros((len(win), T, 512), np.int64)
    for i, (lo, hi) in enumerate(win):
        c[i] = EV.stream_counts(addr[lo:hi], T)
    return rid, subj, lab, c.astype(np.uint16), np.array([hi - lo for lo, hi in win]), np.arange(len(win))


def do_events(arg):
    path, wins = arg
    x, y, p, t = read_dvs(path)
    allw = windows(t)
    return {wi: (x[allw[wi][0]:allw[wi][1]].astype(np.uint8), y[allw[wi][0]:allw[wi][1]].astype(np.uint8), p[allw[wi][0]:allw[wi][1]].astype(np.uint8)) for wi in wins}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-test-events", type=int, default=2000)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    recs = recordings()
    print(len(recs), "recordings", flush=True)
    parts = {}
    with ProcessPoolExecutor(4) as ex:
        for rid, subj, lab, c, n, wi in ex.map(do_rec, list(enumerate(recs))):
            np.save(OUT / f"part_{rid:03d}.npy", c)
            parts[rid] = (subj, lab, n, wi, len(c))
            print(rid, f"s{subj}", LETTERS[lab], len(c), "windows, mean events", int(n.mean()), flush=True)
    N = sum(v[4] for v in parts.values())
    counts = np.lib.format.open_memmap(OUT / "counts.npy", mode="w+", dtype=np.uint16, shape=(N, T, 512))
    meta = {k: [] for k in ("label", "subject", "rec", "win", "n_events")}
    r0 = 0
    for rid in sorted(parts):
        subj, lab, n, wi, m = parts[rid]
        counts[r0:r0 + m] = np.load(OUT / f"part_{rid:03d}.npy")
        (OUT / f"part_{rid:03d}.npy").unlink()
        meta["label"] += [lab] * m; meta["subject"] += [subj] * m; meta["rec"] += [rid] * m; meta["win"] += list(wi); meta["n_events"] += list(n)
        r0 += m
    counts.flush()
    rng = np.random.default_rng(0)
    perm = rng.permutation(N)
    n_test = N // 5
    split = np.zeros(N, np.int8)
    split[perm[:n_test]] = 2
    tr = perm[n_test:]
    split[tr[:len(tr) // 10]] = 1
    meta = {k: np.asarray(v) for k, v in meta.items()}
    test_rows = perm[:n_test]                              # fixed random order; the RTL uses the first --n-test-events
    np.savez(OUT / "meta.npz", max_count=int(np.asarray(counts).max()), split=split, test_order=test_rows, letters=np.array(LETTERS), **meta)
    pick = test_rows[:a.n_test_events]
    want = {}
    for r in pick:
        want.setdefault(int(meta["rec"][r]), []).append(int(meta["win"][r]))
    got = {}
    with ProcessPoolExecutor(4) as ex:
        for rid, res in zip(sorted(want), ex.map(do_events, [(recs[rid][2], want[rid]) for rid in sorted(want)])):
            got.update({(rid, wi): v for wi, v in res.items()})
    xs, ys, ps, off = [], [], [], [0]
    for r in pick:
        x, y, p = got[(int(meta["rec"][r]), int(meta["win"][r]))]
        assert np.array_equal(EV.stream_counts(EV.address(x.astype(np.int64), y.astype(np.int64), p.astype(np.int64), H, W), T), counts[r])
        xs.append(x); ys.append(y); ps.append(p); off.append(off[-1] + len(x))
    np.savez(OUT / "test_ev.npz", x=np.concatenate(xs), y=np.concatenate(ys), p=np.concatenate(ps), offset=np.array(off, np.int64), row=pick)
    print("done:", N, "samples; train", int((split == 0).sum()), "val", int((split == 1).sum()), "test", int((split == 2).sum()), "| events/sample mean", int(meta["n_events"].mean()),
          "| max count", int(np.asarray(counts).max()), flush=True)


if __name__ == "__main__":
    main()
