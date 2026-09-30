"""
Raw AER event streams and the exact rules that turn them into the count vectors c[t,addr].

This is the reference for the Phase-1 address generator and event/timestep counter. It restates
what the original `neurohdc.events_to_frames` does, in the form the hardware sees it: one event at
a time, in stream order. `verify_stream` proves, per sample, that these rules reproduce the
`events_to_frames` counts exactly.

Stream order: DVS-Gesture = rows of the .npy sorted by t with a STABLE sort (DVSGestureDataset);
N-MNIST = `_read_nmnist_bin` order (also a stable sort by t). Timestamps are not needed beyond the
order, so they are not exported.

Address (NeuroHDC eq. 19, with the clamps in events_to_frames):
    addr = p*256 + min(y*16 // H, 15)*16 + min(x*16 // W, 15),  x,y first clamped to W-1 / H-1
    DVS-Gesture (H=W=128): addr = p*256 + (y>>3)*16 + (x>>3)
    N-MNIST     (H=W=34) : integer division by 34, NOT a shift

Timestep of event k (0-based) in a sample of n events:  t(k) = floor(k*T / n).
Timestep t therefore holds  ceil((t+1)n/T) - ceil(tn/T)  events, i.e. N_e = n//T or N_e+1;
exactly r = n mod T timesteps hold N_e+1. Every event is used; none is dropped. This is NOT
"a boundary every N_e events" (IMPLEMENTATION_README P1.1 / P1.2): that rule would put
N_e*T events in the first T timesteps and leave r events over.
Hardware form (`boundary_counter_bins`): acc += T per event; while acc >= n: acc -= n, boundary.
It needs n (the sample's event total) up front, as does N_e = n//T itself.
"""
import numpy as np
import _paths  # noqa: F401
from neurohdc import _read_nmnist_bin, events_to_frames

GEOM = {"dvsgesture": (128, 128), "nmnist": (34, 34)}     # (H, W) passed to events_to_frames


def read_stream(dataset, path):
    """(x, y, p) int64 arrays in the exact order the original dataset feeds events_to_frames."""
    if dataset == "dvsgesture":
        ev = np.load(path)
        order = np.argsort(ev[:, 3], kind="stable")
        x, y, p = ev[:, 0], ev[:, 1], ev[:, 2]
        return x[order].astype(np.int64), y[order].astype(np.int64), p[order].astype(np.int64)
    x, y, p, _ = _read_nmnist_bin(path)
    return x, y, p


def address(x, y, p, H, W):
    """NeuroHDC eq. (19), bit-identical to events_to_frames."""
    x = np.minimum(x, W - 1); y = np.minimum(y, H - 1)
    return p * 256 + np.minimum(y * 16 // H, 15) * 16 + np.minimum(x * 16 // W, 15)


def timestep_of_event(n, T=100):
    """Closed form used by events_to_frames: t(k) = floor(k*T/n)."""
    return (np.arange(n, dtype=np.int64) * T) // n


def bin_sizes(n, T=100):
    """Events in each timestep: ceil((t+1)n/T) - ceil(tn/T)  (values N_e or N_e+1)."""
    edges = -((-np.arange(T + 1, dtype=np.int64) * n) // T)          # ceil(t*n/T), t = 0..T
    return np.diff(edges)


def boundary_counter_bins(n, T=100):
    """Event-by-event hardware counter (reference for the Phase-1 event_ctr). Returns t(k) for
    every event. Uses only an accumulator compared against n: no division, no multiply."""
    t_of = np.empty(n, np.int64)
    acc, t = 0, 0
    for k in range(n):
        t_of[k] = t
        acc += T
        while acc >= n:            # 'while' covers n < T (empty timesteps); for n >= T it fires at most once
            acc -= n
            t += 1
    assert t == T, "counter must emit exactly T boundaries"
    return t_of


def stream_counts(addr, T=100):
    """c[t,addr] from an address stream using the timestep rule above."""
    n = len(addr)
    c = np.zeros((T, 512), np.int64)
    if n:
        np.add.at(c, (timestep_of_event(n, T), addr), 1)
    return c


def verify_stream(dataset, path, counts_ref, T=100):
    """True iff read_stream -> address -> timestep rule reproduces counts_ref [T,512] exactly,
    and also equals a fresh events_to_frames call on the same stream."""
    H, W = GEOM[dataset]
    x, y, p = read_stream(dataset, path)
    a = address(x, y, p, H, W)
    c = stream_counts(a, T)
    fr, _, _ = events_to_frames(x, y, p, T, H, W)
    return bool(np.array_equal(c, counts_ref)) and bool(np.array_equal(c, np.rint(fr).astype(np.int64)))


def export_streams(outdir, dataset, paths, labels, sample_rows, T=100):
    """Write events_<dataset>.npz with the concatenated streams of the chosen samples.
    DVS-Gesture events pack as uint16 word  p<<14 | y<<7 | x  (the AER input to addr_gen);
    N-MNIST as p<<12 | y<<6 | x. `addr` (uint16) is the expected addr_gen output per event."""
    H, W = GEOM[dataset]
    shift = 7 if dataset == "dvsgesture" else 6
    words, addrs, offs, ns = [], [], [0], []
    for i in sample_rows:
        x, y, p = read_stream(dataset, paths[i])
        words.append(((p << (2 * shift)) | (y << shift) | x).astype(np.uint16))
        addrs.append(address(x, y, p, H, W).astype(np.uint16))
        ns.append(len(x)); offs.append(offs[-1] + len(x))
    n = np.array(ns, np.int64)
    np.savez_compressed(f"{outdir}/events.npz", aer=np.concatenate(words), addr=np.concatenate(addrs),
                        offset=np.array(offs, np.int64), sample_row=np.asarray(sample_rows, np.int32),
                        n_events=n, N_e=(n // T).astype(np.int32), remainder=(n % T).astype(np.int32),
                        label=np.asarray(labels)[list(sample_rows)].astype(np.int16),
                        aer_packing=np.array(f"p<<{2 * shift} | y<<{shift} | x"))
