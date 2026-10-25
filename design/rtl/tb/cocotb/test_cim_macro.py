"""Block E: cim_macro (behavioural). m[j][k] = popcount(input bit & stored weight plane bit) over one group. Reference weights/planes are the
Phase 0 exported images; directed weights -128, -1, 0, +1, +127; input rows all-zero and all-one."""
import os

import cocotb
import numpy as np

from common import G, reset, start_clock, ticks, unpack_signed, weights_to_macro_words, write_weights_flat

G_ROWS = int(os.environ.get("ROWS_PER_GROUP", "4"))
COLS = int(os.environ.get("N_PARALLEL_COLS", "40"))
NG = -(-512 // G_ROWS)
MW = (G_ROWS).bit_length()          # clog2(g + 1)
PL = COLS // 20                     # weight bit-planes per pass
PASSES = 8 // PL


def planes_of(W):
    u = W.astype(np.int64) & 0xFF
    return np.stack([(u >> k) & 1 for k in range(8)], axis=1)          # [20, 8, 512]


async def load(dut, W):
    words = weights_to_macro_words(W)
    for m in range(5):
        for a in range(512):
            dut.wr_en_i.value, dut.wr_macro_i.value, dut.wr_addr_i.value, dut.wr_data_i.value = 1, m, a, int(words[m, a])
            await ticks(dut)
    dut.wr_en_i.value = 0
    await ticks(dut)


async def read(dut, bits, grp, p=0):
    """one read of group `grp` with the g row bits of the group (bits are the 512 input bits; only the group's are driven), pass p; returns m[20, 8] with the PL planes of the pass filled in"""
    lo, hi = grp * G_ROWS, min((grp + 1) * G_ROWS, 512)
    dut.rd_valid_i.value, dut.rd_bits_i.value, dut.rd_grp_i.value, dut.rd_pass_i.value = 1, int(sum(int(b) << i for i, b in enumerate(bits[lo:hi]))), grp, p
    await ticks(dut)
    dut.rd_valid_i.value = 0
    assert int(dut.m_valid_o.value) == 1
    v = int(dut.m_o.value)
    m = np.zeros((20, 8), np.int64)
    for j in range(20):
        for q in range(PL):
            m[j, p * PL + q] = (v >> ((j * PL + q) * MW)) & ((1 << MW) - 1)
    return m


def expect(planes, bits, grp, p=0):
    lo, hi = grp * G_ROWS, min((grp + 1) * G_ROWS, 512)
    m = np.zeros((20, 8), np.int64)
    for k in range(p * PL, (p + 1) * PL):
        m[:, k] = planes[:, k, lo:hi] @ np.asarray(bits[lo:hi], np.int64)
    return m


def expect_all(planes, bits, grp):
    return sum(expect(planes, bits, grp, p) for p in range(PASSES))


async def init(dut):
    dut.wr_en_i.value = dut.rd_valid_i.value = 0
    dut.rd_bits_i.value = dut.rd_grp_i.value = dut.rd_pass_i.value = 0
    await start_clock(dut); await reset(dut)


@cocotb.test()
async def real_weights_real_rows(dut):
    await init(dut)
    man, c, s, W = G.load_dataset("dvsgesture", 0)
    await load(dut, W)
    planes = planes_of(W)
    rng = np.random.default_rng(1)
    counts = c["counts"][0].astype(np.int64)
    for t in (0, 17, 60):
        for b in (0, 3, 9):
            bits = ((counts[t] >> b) & 1)
            for grp in rng.integers(0, NG, 6).tolist() + [0, NG - 1]:
                for p in range(PASSES):
                    got = await read(dut, bits, int(grp), p)
                    assert np.array_equal(got, expect(planes, bits, int(grp), p)), f"t={t} b={b} grp={grp} pass={p}"


@cocotb.test()
async def directed_weights_and_input_rows(dut):
    await init(dut)
    W = np.zeros((20, 512), np.int8)
    for j, v in enumerate((-128, -1, 0, 1, 127)):
        W[j, :] = v                                              # the sign plane (k = 7) is set for -128 and -1
    await load(dut, W)
    planes = planes_of(W)
    ones, zeros = np.ones(512, np.int64), np.zeros(512, np.int64)
    for grp in (0, NG // 2, NG - 1):
        got1 = np.zeros((20, 8), np.int64)
        for p in range(PASSES):
            got1 += await read(dut, ones, grp, p)                              # the passes fill disjoint planes
        assert np.array_equal(got1, expect_all(planes, ones, grp))
        lo, hi = grp * G_ROWS, min((grp + 1) * G_ROWS, 512)
        n = hi - lo
        # -128 = 0b10000000 -> only plane 7 set; -1 = 0b11111111 -> all planes; 0 -> none; +1 -> plane 0; +127 -> planes 0..6
        assert list(got1[0]) == [0] * 7 + [n] and list(got1[1]) == [n] * 8 and list(got1[2]) == [0] * 8
        assert list(got1[3]) == [n] + [0] * 7 and list(got1[4]) == [n] * 7 + [0]
        got0 = np.zeros((20, 8), np.int64)
        for p in range(PASSES):
            got0 += await read(dut, zeros, grp, p)
        assert not got0.any(), "an all-zero input row must give zero matches"
