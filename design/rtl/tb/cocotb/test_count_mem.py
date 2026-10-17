"""Block B: count_mem. Directed hazards + random streams, checked against plain counting."""
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


async def read_counts(dut):
    c = np.zeros(N, np.int64)
    for b in range(W_COUNT):
        dut.row_sel_i.value = b
        await cocotb.triggers.Timer(1, unit="ns")
        row = int(dut.row_o.value)
        c += np.array([(row >> a) & 1 for a in range(N)], np.int64) << b
        assert int(dut.row_nz_o.value) == int(row != 0)
    return c


async def wipe(dut):
    dut.wipe_i.value = 1
    await ticks(dut)
    dut.wipe_i.value = 0
    await ticks(dut)


async def init(dut):
    dut.ev_valid_i.value = dut.wipe_i.value = dut.chk_i.value = 0
    dut.ev_addr_i.value = dut.row_sel_i.value = dut.chk_expected_i.value = 0
    await start_clock(dut); await reset(dut)


@cocotb.test()
async def back_to_back_same_address_forwarding(dut):
    await init(dut)
    fwd = 0
    for pattern in ([7] * 50, [3, 3, 9, 9, 9, 3], [1, 2] * 20, [5] * 3 + [6] + [5] * 3):
        await wipe(dut)
        for a in pattern:
            dut.ev_valid_i.value, dut.ev_addr_i.value = 1, a
            await cocotb.triggers.Timer(1, unit="ns")
            fwd += int(dut.fwd_o.value)
            await ticks(dut)
        dut.ev_valid_i.value = 0
        while int(dut.busy_o.value):
            await ticks(dut)
        got = await read_counts(dut)
        exp = np.bincount(pattern, minlength=N)
        assert np.array_equal(got, exp), f"pattern {pattern[:6]}...: counts differ"
    assert fwd > 0, "the forwarding path was never exercised"
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def random_streams_match_counting(dut):
    await init(dut)
    rng = np.random.default_rng(11)
    for trial in range(5):
        await wipe(dut)
        n = int(rng.integers(500, 4000))
        pool = rng.integers(0, N, size=int(rng.integers(5, 300)))
        addrs = rng.choice(pool, size=n)
        await drive(dut, addrs, gaps=bool(trial % 2))
        assert np.array_equal(await read_counts(dut), np.bincount(addrs, minlength=N))
        act = int(dut.active_o.value)
        assert [(act >> a) & 1 for a in range(N)] == list((np.bincount(addrs, minlength=N) > 0).astype(int))
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def maximum_count_then_overflow_trips_assertion(dut):
    await init(dut)
    await wipe(dut)
    await drive(dut, [5] * (2**W_COUNT - 1))
    assert (await read_counts(dut))[5] == 2**W_COUNT - 1
    assert int(dut.assert_fail_o.value) == 0, "reaching the maximum must be legal"
    await drive(dut, [5])
    await ticks(dut, 2)
    assert int(dut.assert_fail_o.value) == 1, "exceeding the counter maximum must trip the assertion"


@cocotb.test()
async def bulk_wipe_clears_everything_and_sum_check(dut):
    await init(dut)
    rng = np.random.default_rng(5)
    addrs = rng.integers(0, N, size=1234)
    await wipe(dut)
    await drive(dut, addrs)
    dut.chk_expected_i.value, dut.chk_i.value = 1234, 1       # the counters sum to the event count
    await ticks(dut)
    dut.chk_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 0
    await wipe(dut)
    assert not (await read_counts(dut)).any()
    assert int(dut.active_o.value) == 0
