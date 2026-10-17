"""
Bit-plane-transposed weight image export.

Logical image: 512 addresses (rows) x 160 columns, column = neuron*8 + plane.
  plane 0 = LSB ... plane 7 = sign bit (int8 two's complement).
Physical word for address a (160 bits): bit index (LSB = bit 0) = neuron*8 + plane.
Files (per seed), all under tb/vectors/weights/:
  weights_seed{s}_int8.npy         int8  [20,512]     natural layout (reference only)
  weights_seed{s}_planes.npy       uint8 [20,8,512]   [neuron][plane][address], 0/1
  weights_seed{s}_160b.mem         512 lines x 40 hex chars, line i = address i, MSB first
                                   ($readmemh-compatible)
  weights_seed{s}_macro{m}_32b.mem 5 files, 512 lines x 8 hex chars; macro m holds neurons
                                   4m..4m+3; bit index = (neuron%4)*8 + plane
                                   (mirrors NeuroHDC's 512x32b macros, 4 neurons each)
  thresh_seed{s}.mem / .json       20 integer thresholds (signed, two's complement hex)
"""
import json, os
import numpy as np

N_NEURON, N_PLANE, N_ADDR = 20, 8, 512


def weight_planes(W: np.ndarray) -> np.ndarray:
    """int8 [20,512] -> uint8 [20,8,512] bit-planes of the two's-complement byte."""
    u = np.ascontiguousarray(W).view(np.uint8)              # two's-complement byte
    return np.stack([(u >> k) & 1 for k in range(N_PLANE)], axis=1).astype(np.uint8)


def decode_planes(planes: np.ndarray) -> np.ndarray:
    """Inverse: bit-planes -> int8 [20,512]. plane 7 carries weight -128 (never used: |q|<=127)."""
    val = np.zeros(planes.shape[0::2], np.int64)
    for k in range(N_PLANE):
        val += (-(1 << 7) if k == 7 else (1 << k)) * planes[:, k, :].astype(np.int64)
    return val.astype(np.int8)


def pack_rows(planes: np.ndarray, neurons=range(N_NEURON)) -> list[int]:
    """One integer per address; bit (i*8 + k) = plane k of the i-th listed neuron."""
    rows = []
    for a in range(N_ADDR):
        w = 0
        for i, j in enumerate(neurons):
            for k in range(N_PLANE):
                w |= int(planes[j, k, a]) << (i * N_PLANE + k)
        rows.append(w)
    return rows


def unpack_rows(rows: list[int], n_neurons: int) -> np.ndarray:
    planes = np.zeros((n_neurons, N_PLANE, N_ADDR), np.uint8)
    for a, w in enumerate(rows):
        for j in range(n_neurons):
            for k in range(N_PLANE):
                planes[j, k, a] = (w >> (j * N_PLANE + k)) & 1
    return planes


def read_mem(path: str) -> list[int]:
    with open(path) as f:
        return [int(l.strip(), 16) for l in f if l.strip() and not l.startswith("//")]


def write_mem(path: str, rows: list[int], bits: int):
    nh = bits // 4
    with open(path, "w") as f:
        f.write(f"// {len(rows)} words x {bits} b, address 0 first, hex MSB-first, bit index = neuron_in_macro*8+plane\n")
        for w in rows:
            f.write(f"{w:0{nh}x}\n")


def export_weight_image(outdir: str, seed: int, W: np.ndarray, thresh_int: np.ndarray, w_thresh_bits: int):
    os.makedirs(outdir, exist_ok=True)
    planes = weight_planes(W)
    assert np.array_equal(decode_planes(planes), W)
    np.save(f"{outdir}/weights_seed{seed}_int8.npy", W)
    np.save(f"{outdir}/weights_seed{seed}_planes.npy", planes)
    rows = pack_rows(planes)
    write_mem(f"{outdir}/weights_seed{seed}_160b.mem", rows, 160)
    for m in range(5):
        write_mem(f"{outdir}/weights_seed{seed}_macro{m}_32b.mem",
                  pack_rows(planes, range(4 * m, 4 * m + 4)), 32)
    with open(f"{outdir}/thresh_seed{seed}.mem", "w") as f:
        f.write(f"// 20 x {w_thresh_bits} b two's complement, neuron 0 first\n")
        for t in thresh_int:
            f.write(f"{int(t) & ((1 << w_thresh_bits) - 1):0{(w_thresh_bits + 3) // 4}x}\n")
    with open(f"{outdir}/thresh_seed{seed}.json", "w") as f:
        json.dump({"thresh_int": [int(t) for t in thresh_int], "signed_bits": w_thresh_bits}, f, indent=1)
    return rows


def verify_image(outdir: str, seed: int, W: np.ndarray):
    """Reload every emitted file and prove it reconstructs W exactly."""
    rows = read_mem(f"{outdir}/weights_seed{seed}_160b.mem")
    assert len(rows) == N_ADDR and np.array_equal(decode_planes(unpack_rows(rows, 20)), W)
    for m in range(5):
        r = read_mem(f"{outdir}/weights_seed{seed}_macro{m}_32b.mem")
        assert np.array_equal(decode_planes(unpack_rows(r, 4)), W[4 * m:4 * m + 4])
    assert np.array_equal(decode_planes(np.load(f"{outdir}/weights_seed{seed}_planes.npy")), W)
    return True
