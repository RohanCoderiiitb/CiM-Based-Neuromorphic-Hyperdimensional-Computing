"""Block E: cim_macro (behavioural, packed-row reads). A read drives up to 4 arbitrary rows of one 128-row band (row slots + valid mask); in pass p the macro returns, for the PN = COLS/8 neurons
p*PN .. p*PN+PN-1 (neuron-major columns) and each of the 8 weight bit-planes, the number of driven rows whose stored plane bit is set. Reference weights/planes are the Phase 0 exported images;
directed weights -128, -1, 0, +1, +127; empty and full row sets."""
import os

import cocotb
import numpy as np

from common import G, reset, start_clock, ticks, weights_to_macro_words

COLS = int(os.environ.get("N_PARALLEL_COLS", "40"))
PN = COLS // 8
PASSES = 160 // COLS
MW = 3                               # clog2(4 + 1)
BAND = 128


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


async def read(dut, band, rows, p):
    """drive `rows` (indices inside `band`, at most 4), pass p; returns m[neuron, plane] for the neurons of this pass (others zero)"""
    rv = (1 << len(rows)) - 1
    packed = sum(int(r) << (7 * i) for i, r in enumerate(rows))
    dut.rd_valid_i.value, dut.rd_rv_i.value, dut.rd_rows_i.value, dut.rd_band_i.value, dut.rd_pass_i.value = 1, rv, packed, band, p
    await ticks(dut)
    dut.rd_valid_i.value = 0
    assert int(dut.m_valid_o.value) == 1
    v = int(dut.m_o.value)
    m = np.zeros((20, 8), np.int64)
    for l in range(PN):
        j = p * PN + l
        if j < 20:
            for q in range(8):
                m[j, q] = (v >> ((l * 8 + q) * MW)) & ((1 << MW) - 1)
    return m


def expect(planes, band, rows, p):
    m = np.zeros((20, 8), np.int64)
    for l in range(PN):
        j = p * PN + l
        if j < 20:
            for q in range(8):
                m[j, q] = sum(int(planes[j, q, band * BAND + r]) for r in rows)
    return m


async def init(dut):
    dut.wr_en_i.value = dut.rd_valid_i.value = 0
    dut.rd_rv_i.value = dut.rd_rows_i.value = dut.rd_band_i.value = dut.rd_pass_i.value = 0
    await start_clock(dut); await reset(dut)


@cocotb.test()
async def real_weights_arbitrary_rows(dut):
    await init(dut)
    man, c, s, W = G.load_dataset("dvsgesture", 0)
    await load(dut, W)
    planes = planes_of(W)
    rng = np.random.default_rng(1)
    for _ in range(40):
        band = int(rng.integers(0, 4))
        n = int(rng.integers(1, 5))
        rows = [int(x) for x in rng.choice(BAND, size=n, replace=False)]
        for p in range(PASSES):
            got = await read(dut, band, rows, p)
            assert np.array_equal(got, expect(planes, band, rows, p)), f"band={band} rows={rows} pass={p}"


@cocotb.test()
async def directed_weights_and_row_sets(dut):
    await init(dut)
    W = np.zeros((20, 512), np.int8)
    for j, v in enumerate((-128, -1, 0, 1, 127)):
        W[j, :] = v                                              # the sign plane (k = 7) is set for -128 and -1
    await load(dut, W)
    planes = planes_of(W)
    for band in (0, 3):
        for rows in ([0], [0, 127], [5, 6, 7, 8], []):
            got = np.zeros((20, 8), np.int64)
            for p in range(PASSES):
                got += await read(dut, band, rows, p)              # the passes fill disjoint neurons
            n = len(rows)
            want = sum(expect(planes, band, rows, p) for p in range(PASSES))
            assert np.array_equal(got, want)
            # -128 = 0b10000000 -> only plane 7 set; -1 = all planes; 0 -> none; +1 -> plane 0; +127 -> planes 0..6
            assert list(got[0]) == [0] * 7 + [n] and list(got[1]) == [n] * 8 and list(got[2]) == [0] * 8
            assert list(got[3]) == [n] + [0] * 7 and list(got[4]) == [n] * 7 + [0]
