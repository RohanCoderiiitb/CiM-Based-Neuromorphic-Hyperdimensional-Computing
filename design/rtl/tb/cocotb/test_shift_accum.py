"""Block G: shift_accum. Group counts are added into a full count, then folded with weights sigma(k) 2^(b+k), sigma(7) = -1 (sign plane).
Reference = int_model.bitplane_X / event_serial_X (Phase 0)."""
import os

import cocotb
import numpy as np

from common import G, reset, start_clock, ticks, unpack_signed

G_ROWS = int(os.environ.get("ROWS_PER_GROUP", "4"))
COLS = int(os.environ.get("N_PARALLEL_COLS", "40"))
NG = -(-512 // G_ROWS)
MW = G_ROWS.bit_length()
PL = COLS // 20
PASSES = 8 // PL
WX = 21


def planes_of(W):
    u = W.astype(np.int64) & 0xFF
    return np.stack([(u >> k) & 1 for k in range(8)], axis=1)


def group_counts(planes, bits, grp, p):
    lo, hi = grp * G_ROWS, min((grp + 1) * G_ROWS, 512)
    return np.stack([planes[:, p * PL + q, lo:hi] @ bits[lo:hi] for q in range(PL)], axis=1)       # [20, PL]


def pack_m(m):
    v = 0
    for j in range(20):
        for q in range(PL):
            v |= int(m[j, q]) << ((j * PL + q) * MW)
    return v


async def run_vector(dut, counts_t, W):
    """Play the issue/result protocol of one MVM for a count vector: every (bit-plane b, group) with an active row, every pass back to back, the result one cycle after the issue; return X."""
    planes = planes_of(W)
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    pad = np.zeros(NG * G_ROWS, np.int64); pad[:512] = counts_t
    pending = None
    for grp in range(NG):
        for b in range(11):
            bits = ((pad >> b) & 1).astype(np.int64)
            gb = bits[grp * G_ROWS:(grp + 1) * G_ROWS]
            if not gb.any():
                continue
            for p in range(PASSES):
                dut.iss_valid_i.value, dut.iss_b_i.value, dut.iss_pass_i.value, dut.iss_bits_i.value = 1, b, p, int(sum(int(x) << i for i, x in enumerate(gb)))
                dut.m_valid_i.value, dut.m_i.value = (1, pending) if pending is not None else (0, 0)
                pending = pack_m(group_counts(planes, bits[:512] if False else np.pad(bits, (0, 0)), grp, p))
                await ticks(dut)
    dut.iss_valid_i.value = 0
    dut.m_valid_i.value, dut.m_i.value = (1, pending) if pending is not None else (0, 0)
    await ticks(dut)
    dut.m_valid_i.value = 0
    await ticks(dut, 2)
    return unpack_signed(int(dut.x_o.value), 20, WX)


async def init(dut):
    for s in ("clr_i", "iss_valid_i", "iss_bits_i", "iss_b_i", "iss_pass_i", "m_valid_i", "m_i"):
        getattr(dut, s).value = 0
    await start_clock(dut); await reset(dut)


@cocotb.test()
async def sign_bit_directed(dut):
    """Weights -128, -1, 0, +1, +127 (the sign-plane cases), single address and max count."""
    await init(dut)
    W = np.zeros((20, 512), np.int8)
    for j, v in enumerate((-128, -1, 0, 1, 127)):
        W[j, :] = v
    for name, counts in (("one event", np.eye(1, 512, 0, dtype=np.int64)[0]), ("count 2047 at one address", np.eye(1, 512, 77, dtype=np.int64)[0] * 2047),
                         ("all addresses c=1", np.ones(512, np.int64)), ("empty", np.zeros(512, np.int64))):
        got = await run_vector(dut, counts, W)
        ref_bp = G.IM.bitplane_X(counts, planes_of(W).astype(np.uint8), 11)
        ref_es = G.IM.event_serial_X(counts, W) if counts.sum() < 5000 else ref_bp
        assert np.array_equal(ref_bp, ref_es), "reference self-check"
        assert got[:5] == list(ref_bp[:5]), f"{name}: X = {got[:5]}, reference {list(ref_bp[:5])}"
    assert int(dut.assert_fail_o.value) == 0
    # extremes of X: -128 * 2047 and +127 * 2047 land inside 21 signed bits
    got = await run_vector(dut, np.eye(1, 512, 9, dtype=np.int64)[0] * 2047, W)
    assert got[0] == -128 * 2047 and got[4] == 127 * 2047 and got[1] == -2047 and got[3] == 2047 and got[2] == 0


@cocotb.test()
async def real_count_vectors_group_accumulation(dut):
    await init(dut)
    man, c, s, W = G.load_dataset("dvsgesture", 1)
    planes = planes_of(W).astype(np.uint8)
    for r, t in ((0, 3), (5, 40), (100, 77), (239, 99)):
        counts = c["counts"][r, t].astype(np.int64)
        got = await run_vector(dut, counts, W)
        assert got == list(G.IM.bitplane_X(counts, planes, 11)), f"row {r} t {t}"
        assert got == list(c["counts"][r, t].astype(np.int64) @ W.astype(np.int64).T), "X must equal the plain integer MVM"
    assert int(dut.assert_fail_o.value) == 0
