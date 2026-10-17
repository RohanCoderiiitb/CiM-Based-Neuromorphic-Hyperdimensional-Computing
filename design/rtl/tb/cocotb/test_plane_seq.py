"""Block D: plane_seq. Walks count bit-rows 0..10, skips all-zero rows, walks ceil(512/g) groups; instrumented skip and read counters.
Parameters (set by the runner): ROWS_PER_GROUP, N_PARALLEL_COLS, PLANE_SKIP_EN."""
import os

import cocotb
import numpy as np

from common import reset, start_clock, ticks

G_ROWS = int(os.environ.get("ROWS_PER_GROUP", "8"))
COLS = int(os.environ.get("N_PARALLEL_COLS", "160"))
SKIP = int(os.environ.get("PLANE_SKIP_EN", "1"))
W_COUNT, NG = 11, -(-512 // G_ROWS)
PASSES = 160 // COLS


async def walk(dut, nz):
    """Run one timestep's sequence; the testbench plays count_mem by answering row_nz_i for whatever bit-row is selected."""
    dut.start_i.value = 1
    await ticks(dut)
    dut.start_i.value = 0
    seq, done, cycles = [], False, 0
    while not done and cycles < 100000:
        await cocotb.triggers.Timer(1, unit="ns")
        dut.row_nz_i.value = int(nz[int(dut.row_sel_o.value)])
        await cocotb.triggers.Timer(1, unit="ns")
        if int(dut.rd_valid_o.value):
            seq.append((int(dut.row_sel_o.value), int(dut.group_idx_o.value), int(dut.plane_mask_o.value), int(dut.rd_last_o.value)))
        done = bool(int(dut.done_o.value))
        await ticks(dut)
        cycles += 1
    assert done, "sequence never finished"
    await ticks(dut, 2)
    return seq


def expected(nz):
    out, rows = [], [b for b in range(W_COUNT) if nz[b] or not SKIP]
    for b in rows:
        for p in range(PASSES):
            for g in range(NG):
                out.append((b, g, 0xFF if PASSES == 1 else 1 << p, int(g == NG - 1 and p == PASSES - 1)))
    return out, rows


@cocotb.test()
async def walks_and_skips(dut):
    dut.start_i.value = dut.row_nz_i.value = 0
    await start_clock(dut); await reset(dut)
    rng = np.random.default_rng(2)
    cases = {"all empty": [0] * W_COUNT, "all full": [1] * W_COUNT, **{f"only row {b}": [int(i == b) for i in range(W_COUNT)] for b in range(W_COUNT)},
             "random a": list(rng.integers(0, 2, W_COUNT)), "random b": list(rng.integers(0, 2, W_COUNT))}
    for name, nz in cases.items():
        seq = await walk(dut, nz)
        exp, rows = expected(nz)
        assert seq == exp, f"{name}: read sequence differs (got {len(seq)} reads, expected {len(exp)})"
        skipped = W_COUNT - len(rows)
        assert int(dut.rows_skipped_o.value) == skipped, f"{name}: skipped rows {int(dut.rows_skipped_o.value)} != {skipped}"
        assert int(dut.rows_read_o.value) == len(rows)
        assert int(dut.reads_allcols_o.value) == len(rows) * NG, "reads (bit-row, group) activations"
        assert int(dut.reads_plane_o.value) == len(rows) * NG * 8, "plane-serial form (x8)"
        assert int(dut.reads_issued_o.value) == len(rows) * NG * PASSES
        # every group boundary appears: group indices of each row are exactly 0..NG-1, the last read of each row carries rd_last
        for b in rows:
            groups = [g for (bb, g, m, l) in seq if bb == b and (m == 0xFF or m == 1)]
            assert groups == list(range(NG)) or PASSES > 1
    assert int(dut.assert_fail_o.value) == 0
