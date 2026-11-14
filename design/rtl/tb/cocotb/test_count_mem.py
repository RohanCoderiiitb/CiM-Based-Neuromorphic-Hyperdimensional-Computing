"""Block B: count_mem. Lane-private counters: every input lane has its own copy (2 ping-pong sets x 4 single-port SRAM banks, bank = address[1:0], double-pumped), N_LANES events
EVERY cycle with no back-pressure; the scan returns the sum of the lane copies. Directed hazards + random streams checked against plain counting; the scan reads one GROUP (the 4 counters of a row) per cycle and clears the groups it marks finished (scan_clr_i with the arriving data);
reset / flush sweep; ping-pong isolation of the two sets."""
import cocotb
import numpy as np

from common import G, reset, start_clock, ticks

N = 512
NB = 4                      # banks = counters per group
NG = N // NB                # groups
W_COUNT = 11
N_LANES = 3
W_ADDR = 9


async def put(dut, lanes):
    """present up to N_LANES events at once (a prefix of the lanes); all of them are taken (no back-pressure)."""
    await cocotb.triggers.Timer(1, unit="ns")
    m = min(len(lanes), N_LANES)
    v, a = 0, 0
    for k in range(m):
        v |= 1 << k
        a |= int(lanes[k]) << (W_ADDR * k)
    dut.ev_valid_i.value, dut.ev_addr_i.value = v, a
    await ticks(dut)
    dut.ev_valid_i.value = 0
    return m


async def drive(dut, addrs, gaps=False, rng=None):
    rng = rng if rng is not None else np.random.default_rng(3)
    i = 0
    addrs = list(map(int, addrs))
    while i < len(addrs):
        if gaps and rng.random() < 0.3:
            dut.ev_valid_i.value = 0
            await ticks(dut)
        want = int(rng.integers(1, N_LANES + 1))
        i += await put(dut, addrs[i:i + want])
    dut.ev_valid_i.value = 0
    while int(dut.busy_o.value):
        await ticks(dut)
    await ticks(dut)


async def scan_all(dut, clear=True, set_=0):
    """read all groups of counter set `set_`, one group per cycle; the group arrives a cycle later (scan_qv_o); cleared in place when `clear`."""
    c = np.zeros(N, np.int64)
    got = 0
    dut.scan_set_i.value = set_
    dut.scan_clr_i.value = 0
    for t in range(NG + 2):
        dut.scan_re_i.value = 1 if t < NG else 0
        dut.scan_grp_i.value = t if t < NG else 0
        await ticks(dut)
        dut.scan_clr_i.value = 0
        if int(dut.scan_qv_o.value):
            q = int(dut.q_o.value)
            for w in range(NB):
                c[got * NB + w] = (q >> (w * W_COUNT)) & ((1 << W_COUNT) - 1)
            got += 1
            dut.scan_clr_i.value = 1 if clear else 0           # the group in q_o is finished: clear it
    dut.scan_re_i.value = 0
    await ticks(dut)
    dut.scan_clr_i.value = 0
    await ticks(dut, 2)
    assert got == NG
    return c


async def wait_ready(dut):
    while not int(dut.ready_o.value):
        await ticks(dut)


async def init(dut):
    dut.ev_valid_i.value = dut.wipe_i.value = dut.chk_i.value = dut.flush_i.value = dut.scan_re_i.value = 0
    dut.ev_addr_i.value = dut.scan_grp_i.value = dut.chk_expected_i.value = 0
    dut.ing_sel_i.value = dut.scan_set_i.value = dut.scan_clr_i.value = 0
    dut.dirty_clr_i.value = dut.dirty_clr_set_i.value = 0
    await start_clock(dut); await reset(dut)
    assert not int(dut.ready_o.value), "the post-reset sweep must hold ready low"
    await wait_ready(dut)


@cocotb.test()
async def sweep_after_reset_leaves_zeros(dut):
    await init(dut)
    for s in (0, 1):
        assert not (await scan_all(dut, set_=s)).any()


@cocotb.test()
async def back_to_back_same_address(dut):
    await init(dut)
    for pattern in ([7] * 50, [3, 3, 9, 9, 9, 3], [1, 2] * 20, [5] * 3 + [6] + [5] * 3):
        i = 0
        while i < len(pattern):
            i += await put(dut, pattern[i:i + N_LANES])
        while int(dut.busy_o.value):
            await ticks(dut)
        got = await scan_all(dut)
        assert np.array_equal(got, np.bincount(pattern, minlength=N)), f"pattern {pattern[:6]}...: counts differ"
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def random_streams_match_counting_and_scan_clears(dut):
    await init(dut)
    rng = np.random.default_rng(11)
    for trial in range(5):
        n = int(rng.integers(500, 4000))
        pool = rng.integers(0, N, size=int(rng.integers(5, 300)))
        addrs = rng.choice(pool, size=n)
        await drive(dut, addrs, gaps=bool(trial % 2), rng=rng)
        assert np.array_equal(await scan_all(dut), np.bincount(addrs, minlength=N))
        assert not (await scan_all(dut)).any(), "the scan must leave every counter cleared (it IS the timestep wipe)"
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def single_bank_stream_at_full_rate(dut):
    """every event to ONE bank, N_LANES per cycle: nothing is lost (each lane has its own copy of the bank)."""
    await init(dut)
    rng = np.random.default_rng(2)
    addrs = rng.integers(0, NG, size=1500) * NB + 1         # all in bank 1, many distinct rows
    await drive(dut, addrs, rng=rng)
    assert np.array_equal(await scan_all(dut), np.bincount(addrs, minlength=N))
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def ping_pong_sets_are_independent(dut):
    """ingest into set 1 while set 0 is scanned: neither disturbs the other."""
    await init(dut)
    rng = np.random.default_rng(9)
    a0 = rng.integers(0, N, size=800)
    a1 = rng.integers(0, N, size=700)
    dut.ing_sel_i.value = 0
    await drive(dut, a0, rng=rng)
    dut.ing_sel_i.value = 1                                   # the scan of set 0 overlaps the ingest of set 1
    scan = cocotb.start_soon(scan_all(dut, set_=0))
    await drive(dut, a1, rng=rng)
    got0 = await scan
    assert np.array_equal(got0, np.bincount(a0, minlength=N)), "set 0 was disturbed by ingest into set 1"
    dut.ing_sel_i.value = 0
    assert np.array_equal(await scan_all(dut, set_=1), np.bincount(a1, minlength=N)), "set 1 lost events during the scan of set 0"
    assert not (await scan_all(dut, set_=0)).any()
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def multi_pass_read_does_not_clear(dut):
    """scan_clr_i = 0 reads without clearing (earlier passes); the last pass (scan_clr_i = 1) clears."""
    await init(dut)
    rng = np.random.default_rng(4)
    addrs = rng.integers(0, N, size=900)
    await drive(dut, addrs, rng=rng)
    ref = np.bincount(addrs, minlength=N)
    assert np.array_equal(await scan_all(dut, clear=False), ref)
    assert np.array_equal(await scan_all(dut, clear=False), ref), "a read without clear changed the counters"
    assert np.array_equal(await scan_all(dut, clear=True), ref)
    assert not (await scan_all(dut)).any()


@cocotb.test()
async def dirty_flags_follow_the_events_per_set(dut):
    """a flag per block of 2 groups (8 counters), per set; set by the events of the ingest set, cleared for one set by dirty_clr_i."""
    await init(dut)
    N_SG = 64
    a0, a1 = [0, 9, 300, 511], [17, 250]
    dut.ing_sel_i.value = 0
    await drive(dut, a0)
    dut.ing_sel_i.value = 1
    await drive(dut, a1)
    d = int(dut.dirty_o.value)
    assert d & ((1 << N_SG) - 1) == sum(1 << f for f in {a >> 3 for a in a0}), "set 0 flags"
    assert d >> N_SG == sum(1 << f for f in {a >> 3 for a in a1}), "set 1 flags"
    dut.dirty_clr_i.value, dut.dirty_clr_set_i.value = 1, 0
    await ticks(dut)
    dut.dirty_clr_i.value = 0
    await ticks(dut)
    d = int(dut.dirty_o.value)
    assert d & ((1 << N_SG) - 1) == 0 and d >> N_SG == sum(1 << f for f in {a >> 3 for a in a1}), "clearing set 0 must not touch set 1"
    dut.ing_sel_i.value = 0
    for s_ in (0, 1):
        await scan_all(dut, set_=s_)


@cocotb.test()
async def maximum_count_then_overflow_trips_assertion(dut):
    await init(dut)
    await drive(dut, [5] * (2**W_COUNT - 1))
    assert (await scan_all(dut))[5] == 2**W_COUNT - 1
    assert int(dut.assert_fail_o.value) == 0, "reaching the maximum must be legal"
    await drive(dut, [5] * 2**W_COUNT)
    await scan_all(dut)                                         # the lane copies sum above the maximum: caught when the group is scanned
    await ticks(dut, 2)
    assert int(dut.assert_fail_o.value) == 1, "exceeding the counter maximum must trip the assertion"


@cocotb.test()
async def sum_check_at_the_end_of_a_scan(dut):
    await init(dut)
    rng = np.random.default_rng(5)
    addrs = rng.integers(0, N, size=1234)
    await drive(dut, addrs, rng=rng)
    await scan_all(dut)
    dut.chk_expected_i.value, dut.chk_i.value = 1234, 1
    await ticks(dut)
    dut.chk_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 0
    await drive(dut, addrs[:100], rng=rng)
    await scan_all(dut)
    dut.chk_expected_i.value, dut.chk_i.value = 99, 1          # wrong on purpose
    await ticks(dut)
    dut.chk_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 1


@cocotb.test()
async def flush_drops_the_pipeline_and_sweeps_the_counters(dut):
    """flush_i (abort) drops events still in the FIFOs / read-modify-write pipeline and clears all counters of both sets with a sweep (ready_o low meanwhile); counting restarts from zero."""
    await init(dut)
    rng = np.random.default_rng(5)
    for trial in range(4):
        addrs = rng.integers(0, N, size=int(rng.integers(20, 200)))
        i = 0
        while i < len(addrs):
            i += await put(dut, addrs[i:i + N_LANES])
        dut.flush_i.value = 1          # events are still in flight: this is the point of the abort
        await ticks(dut)
        dut.flush_i.value = 0
        dut.ev_valid_i.value = 0
        await ticks(dut)
        assert not int(dut.busy_o.value)
        assert not int(dut.ready_o.value), "the sweep must hold ready low"
        await wait_ready(dut)
        for s in (0, 1):
            assert np.array_equal(await scan_all(dut, set_=s), np.zeros(N, np.int64)), "counters not cleared by flush"
        addrs = rng.integers(0, N, size=300)
        await drive(dut, addrs, rng=rng)
        assert np.array_equal(await scan_all(dut), np.bincount(addrs, minlength=N)), "counting after a flush is wrong"
    assert int(dut.assert_fail_o.value) == 0
