"""Block D: plane_seq (scan sequencer). The testbench plays count_mem: it answers each scan read one cycle later with the counter's value. Checks the exact read sequence - groups ascending, within
a group the set bit-planes ascending, every pass of a (plane, group) read back to back - with the row bits and the pass index, that no all-zero (plane, group) is ever read, the access counters,
the scan covering all 512 addresses, and abort from any state. Parameters (set by the runner): ROWS_PER_GROUP, N_PARALLEL_COLS."""
import os

import cocotb
import numpy as np

from common import reset, start_clock, ticks

G_ROWS = int(os.environ.get("ROWS_PER_GROUP", "4"))
COLS = int(os.environ.get("N_PARALLEL_COLS", "40"))
W_COUNT, NG = 11, 512 // G_ROWS
PASSES = 160 // COLS


class Memory:
    """the count memory as seen by the sequencer: a read in cycle t returns the word in cycle t+1"""
    def __init__(self, counts):
        self.counts, self.pend, self.reads = counts, None, []

    async def step(self, dut):
        dut.scan_qv_i.value = 0 if self.pend is None else 1
        dut.scan_q_i.value = 0 if self.pend is None else int(self.counts[self.pend])
        await cocotb.triggers.Timer(1, unit="ns")
        nxt = int(dut.scan_addr_o.value) if int(dut.scan_re_o.value) else None
        if nxt is not None:
            self.reads.append(nxt)
        issued = None
        if int(dut.rd_valid_o.value):
            issued = (int(dut.row_sel_o.value), int(dut.group_idx_o.value), int(dut.pass_o.value), int(dut.rd_bits_o.value))
        done = bool(int(dut.done_o.value))
        await ticks(dut)
        self.pend = nxt
        return issued, done


def expected(counts):
    out = []
    for g in range(NG):
        words = [int(counts[g * G_ROWS + r]) for r in range(G_ROWS)]
        for b in range(W_COUNT):
            bits = sum(((w >> b) & 1) << r for r, w in enumerate(words))
            if bits:
                for p in range(PASSES):
                    out.append((b, g, p, bits))
    return out


async def walk(dut, counts, cut=None):
    mem = Memory(counts)
    dut.start_i.value = 1
    await ticks(dut)
    dut.start_i.value = 0
    seq, done, cycles = [], False, 0
    while not done and cycles < 100000:
        issued, done = await mem.step(dut)
        if issued:
            seq.append(issued)
        cycles += 1
        if cut is not None and cycles == cut:
            return seq, mem, False
    assert done, "scan never finished"
    await ticks(dut, 2)
    return seq, mem, True


@cocotb.test()
async def reads_exactly_the_nonempty_plane_group_pairs(dut):
    dut.start_i.value = dut.abort_i.value = dut.scan_qv_i.value = dut.scan_q_i.value = 0
    await start_clock(dut); await reset(dut)
    rng = np.random.default_rng(2)
    cases = {"all empty": np.zeros(512, np.int64), "one address": np.eye(1, 512, 300, dtype=np.int64)[0] * 3, "all ones": np.ones(512, np.int64),
             "all maxed": np.full(512, 2047, np.int64), "first and last": np.where(np.isin(np.arange(512), (0, 511)), 2047, 0).astype(np.int64),
             "sparse": np.where(rng.random(512) < 0.1, rng.integers(0, 2048, 512), 0).astype(np.int64), "dense": rng.integers(0, 2048, 512).astype(np.int64),
             "low bits": rng.integers(0, 4, 512).astype(np.int64)}
    for name, counts in cases.items():
        seq, mem, _ = await walk(dut, counts)
        exp = expected(counts)
        assert seq == exp, f"{name}: read sequence differs (got {len(seq)} reads, expected {len(exp)})"
        assert sorted(mem.reads) == list(range(512)) and mem.reads == list(range(512)), f"{name}: the scan must read every address exactly once, in order"
        nz_planes = [b for b in range(W_COUNT) if ((counts >> b) & 1).any()]
        nreads = len(exp) // PASSES
        assert int(dut.rows_read_o.value) == len(nz_planes) and int(dut.rows_skipped_o.value) == W_COUNT - len(nz_planes), name
        assert int(dut.reads_allcols_o.value) == nreads and int(dut.reads_plane_o.value) == nreads * 8 and int(dut.reads_issued_o.value) == nreads * PASSES, name
        assert int(dut.zero_groups_o.value) == len(nz_planes) * NG - nreads and int(dut.active_o.value) == int((counts > 0).sum()), name
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def abort_returns_to_idle_from_any_state(dut):
    """abort_i drops the scan wherever it is: idle next cycle, no done pulse, and the next scan is the full, correct one."""
    dut.start_i.value = dut.abort_i.value = dut.scan_qv_i.value = dut.scan_q_i.value = 0
    await start_clock(dut); await reset(dut)
    counts = np.random.default_rng(4).integers(0, 2048, 512).astype(np.int64)
    exp = expected(counts)
    for cut in (1, 2, 3, 5, 9, 40, 200, 500, len(exp) // 2 + 600):
        seq, mem, finished = await walk(dut, counts, cut=cut)
        dut.scan_qv_i.value = 1                                   # the testbench keeps answering while the abort is applied (a late word is legal)
        dut.abort_i.value = 1
        await ticks(dut)
        dut.abort_i.value = 0
        assert not int(dut.busy_o.value) and not int(dut.rd_valid_o.value), f"cut {cut}: still busy after abort"
        for _ in range(4):
            assert not int(dut.done_o.value) or finished, f"cut {cut}: a done pulse after abort"
            await ticks(dut)
        seq, mem, _ = await walk(dut, counts)
        assert seq == exp, f"cut {cut}: the scan after an abort differs"
    assert int(dut.assert_fail_o.value) == 0
