"""Block E: cim_macro (behavioural). m[j][k] = popcount(input bit & stored weight plane bit) over one group. Reference weights/planes are the
Phase 0 exported images; directed weights -128, -1, 0, +1, +127; input rows all-zero and all-one."""
import os

import cocotb
import numpy as np

from common import G, reset, start_clock, ticks, unpack_signed, weights_to_macro_words, write_weights_flat

G_ROWS = int(os.environ.get("ROWS_PER_GROUP", "8"))
NG = -(-512 // G_ROWS)
MW = 10


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


async def read(dut, bits, grp, mask=0xFF):
    dut.rd_valid_i.value, dut.rd_bitrow_i.value, dut.rd_grp_i.value, dut.rd_plane_mask_i.value = 1, int(sum(int(b) << i for i, b in enumerate(bits))), grp, mask
    await ticks(dut)
    dut.rd_valid_i.value = 0
    assert int(dut.m_valid_o.value) == 1
    vals = unpack_signed(int(dut.m_o.value), 160, MW)       # 10-bit fields, values 0..512 (unsigned) - use & mask
    return np.array([v & ((1 << MW) - 1) for v in vals]).reshape(20, 8)


def expect(planes, bits, grp, mask=0xFF):
    lo, hi = grp * G_ROWS, min((grp + 1) * G_ROWS, 512)
    m = np.zeros((20, 8), np.int64)
    for k in range(8):
        if (mask >> k) & 1:
            m[:, k] = planes[:, k, lo:hi] @ np.asarray(bits[lo:hi], np.int64)
    return m


async def init(dut):
    dut.wr_en_i.value = dut.rd_valid_i.value = 0
    dut.rd_bitrow_i.value = dut.rd_grp_i.value = dut.rd_plane_mask_i.value = 0
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
                got = await read(dut, bits, int(grp))
                assert np.array_equal(got, expect(planes, bits, int(grp))), f"t={t} b={b} grp={grp}"
    mask = 0b00100101                                           # plane-serial style partial mask
    got = await read(dut, ((counts[5] >> 1) & 1), 3, mask)
    assert np.array_equal(got, expect(planes, ((counts[5] >> 1) & 1), 3, mask))


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
        got1 = await read(dut, ones, grp)
        assert np.array_equal(got1, expect(planes, ones, grp))
        lo, hi = grp * G_ROWS, min((grp + 1) * G_ROWS, 512)
        n = hi - lo
        # -128 = 0b10000000 -> only plane 7 set; -1 = 0b11111111 -> all planes; 0 -> none; +1 -> plane 0; +127 -> planes 0..6
        assert list(got1[0]) == [0] * 7 + [n] and list(got1[1]) == [n] * 8 and list(got1[2]) == [0] * 8
        assert list(got1[3]) == [n] + [0] * 7 and list(got1[4]) == [n] * 7 + [0]
        got0 = await read(dut, zeros, grp)
        assert not got0.any(), "an all-zero input row must give zero matches"
