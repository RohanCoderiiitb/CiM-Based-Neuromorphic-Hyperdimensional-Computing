"""Block D: plane_seq (PACKED-ROW scan sequencer). The testbench plays count_mem: it presents the dirty flags of the groups that hold events (and clears them on dirty_clr_o), answers every group read one cycle later with the
4 counters of the group (held until the next read, like the SRAM output register), and clears a group when the sequencer marks it finished as it arrives. Checks, for each case:
  - every active (count bit-plane, row) is driven by exactly one read, nothing else is ever driven;
  - a read holds <= 4 rows, all of one bit-plane and one position band (128 rows), as a prefix of the row slots;
  - the number of reads is sum over bands and planes of ceil(n_active / S) (the packing is complete); every read runs its passes 0..PASSES-1 in order (pass-major groups);
  - the dirty blocks (2 groups per flag) are fetched in ascending order once per pass; a group is marked finished (scan_clr_o, with its data) once no count bit is left above the pass's planes;
  - the statistics outputs; abort from any state.   Parameters (set by the runner): ROWS_PER_GROUP (must be 4), N_PARALLEL_COLS (multiple of 8)."""
import os

import cocotb
import numpy as np

from common import reset, start_clock, ticks

G_ROWS = int(os.environ.get("ROWS_PER_GROUP", "4"))
COLS = int(os.environ.get("N_PARALLEL_COLS", "40"))
W_COUNT, NG, N = 11, 512 // G_ROWS, 512
PASSES = 160 // COLS
N_PK = 3
GS = 2                      # groups per dirty flag
N_BANDS, BAND = 4, 128
import re as _re
from pathlib import Path as _P
S = int(_re.search(r"localparam int S_ROWS\s*=\s*(\d+)", (_P(__file__).resolve().parents[2] / 'rtl' / 'pkg' / 'cim_neurohdc_pkg.sv').read_text()).group(1))


class Env:
    """count_mem and the event path as the sequencer sees them"""
    def __init__(self, counts, extra_marks=()):
        self.counts, self.pend, self.q = counts.copy(), None, 0
        self.fetches, self.clears, self.reads, self.done = [], [], [], False
        self.extra = extra_marks

    def word(self, g):
        v = 0
        for w in range(G_ROWS):
            v |= int(self.counts[g * G_ROWS + w]) << (w * W_COUNT)
        return v

    async def mark(self, dut):
        groups = sorted(set(int(a) // G_ROWS for a in np.nonzero(self.counts)[0]) | set(self.extra))
        dut.ing_sel_i.value = 0
        self.dirty = sum(1 << f for f in {g // GS for g in groups})     # set 0 (the set being scanned); set 1 empty
        self.clr = []
        dut.dirty_i.value = self.dirty
        await ticks(dut)

    async def step(self, dut):
        dut.scan_qv_i.value = 0 if self.pend is None else 1
        if self.pend is not None:
            self.q = self.word(self.pend)
        dut.scan_q_i.value = self.q
        await cocotb.triggers.Timer(1, unit="ns")
        nxt = None
        if int(dut.scan_re_o.value):
            nxt = int(dut.scan_grp_o.value)
            self.fetches.append(nxt)
        if int(dut.rd_valid_o.value):
            rv = int(dut.rd_rv_o.value)
            rows = int(dut.rd_rows_o.value)
            self.reads.append((int(dut.row_sel_o.value), int(dut.rd_band_o.value), int(dut.pass_o.value), rv, tuple((rows >> (7 * i)) & 127 for i in range(S))))
        if self.pend is not None:
            c = int(dut.scan_clr_o.value)
            self.clears.append(c)
            if c:
                self.counts[self.pend * G_ROWS:(self.pend + 1) * G_ROWS] = 0    # count_mem clears the group (its output register keeps the word)
        done = bool(int(dut.done_o.value))
        clr = int(dut.dirty_clr_o.value)
        if clr:
            self.clr.append(int(dut.dirty_clr_set_o.value))
        await ticks(dut)
        if clr:
            self.dirty = 0
            dut.dirty_i.value = 0
        self.pend = nxt
        return done


def expected_active(counts):
    return {(b, r) for b in range(W_COUNT) for r in range(N) if (int(counts[r]) >> b) & 1}


def expected_reads(counts):
    n = 0
    for b in range(W_COUNT):
        for band in range(N_BANDS):
            k = sum((int(counts[band * BAND + i]) >> b) & 1 for i in range(BAND))
            n += -(-k // S)
    return n


def expected_fetch_groups(counts, extra=()):
    marked = set(int(a) // G_ROWS for a in np.nonzero(counts)[0]) | set(extra)
    flags = sorted(set(g // GS for g in marked))
    return [f * GS + i for f in flags for i in range(GS)]


async def walk(dut, counts, cut=None, extra=()):
    env = Env(counts, extra)
    await env.mark(dut)
    dut.start_i.value = 1
    await ticks(dut)
    dut.start_i.value = 0
    dut.ing_sel_i.value = 1                                       # the ingest side has moved on to the other set
    cycles = 0
    while not env.done and cycles < 200000:
        env.done = await env.step(dut)
        cycles += 1
        if cut is not None and cycles == cut:
            return env, False
    assert env.done, "scan never finished"
    await ticks(dut, 2)
    return env, True


def check(env, counts, name, extra=()):
    # reads are issued in GROUPS, pass-major: rebuild each read from its passes (same plane / band / rows); every read gets passes 0..PASSES-1 exactly once, in order,
    # and a read's passes are not interleaved with a pass of another round (a pass p issue follows the pass p-1 issues of the same group)
    reads, open_ = [], {}
    for x in env.reads:
        key = (x[0], x[1], x[3], x[4])
        if x[2] == 0:
            assert key not in open_, f"{name}: read {key} started again before it finished"
            open_[key] = 0
        else:
            assert open_.get(key) == x[2] - 1, f"{name}: pass {x[2]} of {key} out of order"
            open_[key] = x[2]
        if x[2] == PASSES - 1:
            reads.append(x)
            del open_[key]
    assert not open_, f"{name}: reads left unfinished {list(open_)[:3]}"
    seen = set()
    for plane, band, _, rv, rows in reads:
        n = bin(rv).count("1")
        assert 1 <= n <= S and rv == (1 << n) - 1, f"{name}: row-valid mask {rv:04b} is not a non-empty prefix"
        for k in range(n):
            key = (plane, band * BAND + rows[k])
            assert key not in seen, f"{name}: row {key} driven twice"
            seen.add(key)
    assert seen == expected_active(counts), f"{name}: driven rows differ from the active rows ({len(seen)} vs {len(expected_active(counts))})"
    assert len(reads) == expected_reads(counts), f"{name}: {len(reads)} reads, packing needs {expected_reads(counts)}"
    # fetch sequence: the dirty blocks, ascending, once per pass; cleared on the last pass only
    blocks = expected_fetch_groups(counts, extra)
    if blocks:
        top = max((int(c).bit_length() for c in counts), default=0)
        npass = max(1, -(-top // N_PK))
        assert env.fetches == blocks * npass, f"{name}: fetch sequence differs ({len(env.fetches)} fetches, expected {len(blocks)} x {npass} passes)"
        bl = [max((int(c).bit_length() for c in counts[g * G_ROWS:(g + 1) * G_ROWS]), default=0) for g in blocks]
        exp = [int(b <= N_PK * (q + 1)) for q in range(npass) for b in bl]
        assert env.clears == exp, f"{name}: scan_clr_o must mark a group finished exactly when no count bit is left above the pass"
        assert env.clr == [0], f"{name}: the dirty flags of the scanned set must be cleared exactly once at the end ({env.clr})"
    else:
        assert not env.fetches


@cocotb.test()
async def packs_the_active_rows_of_every_plane(dut):
    dut.start_i.value = dut.abort_i.value = dut.scan_qv_i.value = dut.scan_q_i.value = dut.dirty_i.value = dut.ing_sel_i.value = 0
    await start_clock(dut); await reset(dut)
    rng = np.random.default_rng(2)
    cases = {"all empty": np.zeros(512, np.int64), "one address": np.eye(1, 512, 300, dtype=np.int64)[0] * 3, "all ones": np.ones(512, np.int64),
             "all maxed": np.full(512, 2047, np.int64), "first and last": np.where(np.isin(np.arange(512), (0, 511)), 2047, 0).astype(np.int64),
             "sparse": np.where(rng.random(512) < 0.1, rng.integers(0, 2048, 512), 0).astype(np.int64), "dense": rng.integers(0, 2048, 512).astype(np.int64),
             "low bits": rng.integers(0, 4, 512).astype(np.int64), "one band": np.where(np.arange(512) < 128, rng.integers(0, 64, 512), 0).astype(np.int64),
             "seven rows in one plane": np.where(np.isin(np.arange(512), (3, 9, 40, 41, 100, 127, 128)), 1, 0).astype(np.int64)}
    for name, counts in cases.items():
        env, _ = await walk(dut, counts)
        check(env, counts, name)
        nz = [b for b in range(W_COUNT) if ((counts >> b) & 1).any()]
        nreads = expected_reads(counts)
        assert int(dut.rows_read_o.value) == len(nz) and int(dut.rows_skipped_o.value) == W_COUNT - len(nz), name
        assert int(dut.reads_allcols_o.value) == nreads and int(dut.reads_plane_o.value) == nreads * 8 and int(dut.reads_issued_o.value) == nreads * PASSES, name
        assert int(dut.active_o.value) == int((counts > 0).sum()), name
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def clean_groups_inside_a_dirty_block_are_harmless(dut):
    """a flagged block is fetched whole: its clean group costs a fetch but no read."""
    dut.start_i.value = dut.abort_i.value = dut.scan_qv_i.value = dut.scan_q_i.value = dut.dirty_i.value = dut.ing_sel_i.value = 0
    await start_clock(dut); await reset(dut)
    counts = np.zeros(512, np.int64)
    counts[40] = 5
    env, _ = await walk(dut, counts, extra=(7, 100))
    check(env, counts, "marked but empty", extra=(7, 100))
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def abort_returns_to_idle_from_any_state(dut):
    """abort_i drops the scan wherever it is: idle next cycle, no done pulse, and the next scan is the full, correct one."""
    dut.start_i.value = dut.abort_i.value = dut.scan_qv_i.value = dut.scan_q_i.value = dut.dirty_i.value = dut.ing_sel_i.value = 0
    await start_clock(dut); await reset(dut)
    counts = np.random.default_rng(4).integers(0, 2048, 512).astype(np.int64)
    for cut in (1, 2, 3, 5, 9, 40, 200, 500, 1500):
        env, finished = await walk(dut, counts, cut=cut)
        dut.scan_qv_i.value = 1                                   # the testbench keeps answering while the abort is applied (a late word is legal)
        dut.abort_i.value = 1
        await ticks(dut)
        dut.abort_i.value = 0
        assert not int(dut.busy_o.value) and not int(dut.rd_valid_o.value), f"cut {cut}: still busy after abort"
        for _ in range(4):
            assert not int(dut.done_o.value) or finished, f"cut {cut}: a done pulse after abort"
            await ticks(dut)
        env, _ = await walk(dut, counts)
        check(env, counts, f"after abort at {cut}")
    assert int(dut.assert_fail_o.value) == 0
