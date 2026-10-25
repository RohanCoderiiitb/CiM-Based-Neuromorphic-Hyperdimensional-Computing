"""Block B: count_mem (double-pumped single-port SRAM). Directed hazards + random streams, checked against plain counting; the scan reads AND clears; reset / flush sweep."""
import cocotb
import numpy as np

from common import G, reset, start_clock, ticks

N = 512
W_COUNT = 11


async def drive(dut, addrs, gaps=False):
    rng = np.random.default_rng(3)
    for a in addrs:
        if gaps and rng.random() < 0.3:
            dut.ev_valid_i.value = 0
            await ticks(dut)
        dut.ev_valid_i.value, dut.ev_addr_i.value = 1, int(a)
        await ticks(dut)
    dut.ev_valid_i.value = 0
    while int(dut.busy_o.value):
        await ticks(dut)
    await ticks(dut)


async def scan_all(dut):
    """read all 512 counters through the scan port, one per cycle; each word arrives a cycle later (scan_qv_o) and is cleared in place."""
    c = np.zeros(N, np.int64)
    got = 0
    for t in range(N + 2):
        dut.scan_re_i.value = 1 if t < N else 0
        dut.scan_addr_i.value = t if t < N else 0
        await ticks(dut)
        if int(dut.scan_qv_o.value):
            c[got] = int(dut.q_o.value)
            got += 1
    dut.scan_re_i.value = 0
    await ticks(dut, 2)
    assert got == N
    return c


async def wait_ready(dut):
    while not int(dut.ready_o.value):
        await ticks(dut)


async def init(dut):
    dut.ev_valid_i.value = dut.wipe_i.value = dut.chk_i.value = dut.flush_i.value = dut.scan_re_i.value = 0
    dut.ev_addr_i.value = dut.scan_addr_i.value = dut.chk_expected_i.value = 0
    await start_clock(dut); await reset(dut)
    assert not int(dut.ready_o.value), "the post-reset sweep must hold ready low"
    await wait_ready(dut)


@cocotb.test()
async def sweep_after_reset_leaves_zeros(dut):
    await init(dut)
    assert not (await scan_all(dut)).any()


@cocotb.test()
async def back_to_back_same_address(dut):
    await init(dut)
    fwd = 0
    for pattern in ([7] * 50, [3, 3, 9, 9, 9, 3], [1, 2] * 20, [5] * 3 + [6] + [5] * 3):
        for a in pattern:
            dut.ev_valid_i.value, dut.ev_addr_i.value = 1, a
            await cocotb.triggers.Timer(1, unit="ns")
            fwd += int(dut.fwd_o.value)
            await ticks(dut)
        dut.ev_valid_i.value = 0
        while int(dut.busy_o.value):
            await ticks(dut)
        got = await scan_all(dut)
        assert np.array_equal(got, np.bincount(pattern, minlength=N)), f"pattern {pattern[:6]}...: counts differ"
    assert fwd > 0, "back-to-back same-address events were never exercised"
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def random_streams_match_counting_and_scan_clears(dut):
    await init(dut)
    rng = np.random.default_rng(11)
    for trial in range(5):
        n = int(rng.integers(500, 4000))
        pool = rng.integers(0, N, size=int(rng.integers(5, 300)))
        addrs = rng.choice(pool, size=n)
        await drive(dut, addrs, gaps=bool(trial % 2))
        assert np.array_equal(await scan_all(dut), np.bincount(addrs, minlength=N))
        assert not (await scan_all(dut)).any(), "the scan must leave every counter cleared (it IS the timestep wipe)"
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def maximum_count_then_overflow_trips_assertion(dut):
    await init(dut)
    await drive(dut, [5] * (2**W_COUNT - 1))
    assert (await scan_all(dut))[5] == 2**W_COUNT - 1
    assert int(dut.assert_fail_o.value) == 0, "reaching the maximum must be legal"
    await drive(dut, [5] * 2**W_COUNT)
    await ticks(dut, 2)
    assert int(dut.assert_fail_o.value) == 1, "exceeding the counter maximum must trip the assertion"


@cocotb.test()
async def sum_check_at_the_end_of_a_scan(dut):
    await init(dut)
    rng = np.random.default_rng(5)
    addrs = rng.integers(0, N, size=1234)
    await drive(dut, addrs)
    await scan_all(dut)
    dut.chk_expected_i.value, dut.chk_i.value = 1234, 1
    await ticks(dut)
    dut.chk_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 0
    await drive(dut, addrs[:100])
    await scan_all(dut)
    dut.chk_expected_i.value, dut.chk_i.value = 99, 1          # wrong on purpose
    await ticks(dut)
    dut.chk_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 1


@cocotb.test()
async def flush_drops_the_pipeline_and_sweeps_the_counters(dut):
    """flush_i (abort) drops events still in the read-modify-write pipeline and clears all counters with a 512-cycle sweep (ready_o low meanwhile); counting restarts from zero."""
    await init(dut)
    rng = np.random.default_rng(5)
    for trial in range(4):
        addrs = rng.integers(0, N, size=int(rng.integers(20, 200)))
        for a in addrs:
            dut.ev_valid_i.value, dut.ev_addr_i.value = 1, int(a)
            await ticks(dut)
        dut.flush_i.value = 1          # events are still in flight: this is the point of the abort
        await ticks(dut)
        dut.flush_i.value = 0
        dut.ev_valid_i.value = 0
        await ticks(dut)
        assert not int(dut.busy_o.value)
        assert not int(dut.ready_o.value), "the sweep must hold ready low"
        await wait_ready(dut)
        assert np.array_equal(await scan_all(dut), np.zeros(N, np.int64)), "counters not cleared by flush"
        addrs = rng.integers(0, N, size=300)
        await drive(dut, addrs)
        assert np.array_equal(await scan_all(dut), np.bincount(addrs, minlength=N)), "counting after a flush is wrong"
    assert int(dut.assert_fail_o.value) == 0
