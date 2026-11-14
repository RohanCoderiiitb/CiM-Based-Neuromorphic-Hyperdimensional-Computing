"""Block C: event_ctr. The rule is t(k) = floor(k*T/n) (events k in timestep t when ceil(t n/T) < k <= ceil((t+1) n/T)). Reference = events.boundary_counter_bins / bin_sizes (Phase 0).
N_LANES events can be accepted per cycle (a prefix of the lanes, none behind a timestep boundary); n/T comes from a divider that must finish before the first event (ready_o)."""
import cocotb
import numpy as np

from common import G, reset, start_clock, ticks

T = G.T
N_LANES = 3


async def wait_ready(dut, limit=200):
    for i in range(limit):
        if int(dut.ready_o.value) == 1:
            return i
        await ticks(dut)
    raise AssertionError("ready_o never rose")


async def run_sample(dut, n, lanes=1, gap_every=0, rng=None):
    """Feed n events, `lanes` per cycle (or a random 1..lanes when rng is given); return (timestep of each event, number of cycles with a boundary)."""
    dut.cfg_n_we_i.value, dut.cfg_n_i.value, dut.n_acc_i.value, dut.clr_i.value = 1, n, 0, 0
    await ticks(dut)
    dut.cfg_n_we_i.value = 0
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    await ticks(dut)
    await wait_ready(dut)
    ts, k, nb, cyc = [], 0, 0, 0
    while k < n:
        if gap_every and cyc % gap_every == 0:
            dut.n_acc_i.value = 0
            await ticks(dut)
        want = int(rng.integers(1, lanes + 1)) if rng is not None else lanes
        want = min(want, n - k)
        await cocotb.triggers.Timer(1, unit="ns")
        pre = int(dut.bnd_pre_o.value)
        # a prefix of the lanes, none behind the first boundary
        m = want
        for lane in range(want):
            if (pre >> lane) & 1:
                m = lane + 1
                break
        dut.n_acc_i.value = m
        await cocotb.triggers.Timer(1, unit="ns")
        t_now = int(dut.tstep_o.value)
        ts.extend([t_now] * m)
        nb += int(dut.bnd_acc_o.value)
        await ticks(dut)
        k += m
        cyc += 1
    dut.n_acc_i.value = 0
    await ticks(dut, 2)
    return np.array(ts), nb


@cocotb.test()
async def rule_floor_k_T_over_n(dut):
    await start_clock(dut); await reset(dut)
    rng = np.random.default_rng(3)
    for n in (T, T + 1, 199, 250, 1000, 4071, 12345, 20001):
        for lanes, rnd in ((1, None), (2, None), (N_LANES, None), (N_LANES, rng)):
            ts, nb = await run_sample(dut, n, lanes, rng=rnd)
            ref = G.EV.boundary_counter_bins(n, T)               # reference hardware counter: t(k) for every event
            assert np.array_equal(ts, ref), f"n={n} lanes={lanes}: timestep of event differs from the reference counter"
            assert nb == T, f"n={n}: {nb} boundaries, expected exactly T={T}"
            sizes = np.bincount(ts, minlength=T)
            assert np.array_equal(sizes, G.EV.bin_sizes(n, T)), f"n={n}: timestep sizes differ from ceil((t+1)n/T)-ceil(tn/T)"
            assert set(np.unique(sizes)) <= {n // T, n // T + 1}, f"n={n}: sizes not in {{N_e, N_e+1}}"
            assert int(dut.sample_done_o.value) == 1
            assert int(dut.ev_total_o.value) == n
            assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def events_with_idle_gaps(dut):
    await start_clock(dut); await reset(dut)
    ts, nb = await run_sample(dut, 1000, N_LANES, gap_every=7)
    assert np.array_equal(ts, G.EV.boundary_counter_bins(1000, T)) and nb == T
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def not_ready_while_dividing(dut):
    """ready_o is low from the configuration write until n/T is known (W_NEVENTS cycles) and until the sample-start load is done."""
    await start_clock(dut); await reset(dut)
    dut.n_acc_i.value, dut.clr_i.value = 0, 0
    dut.cfg_n_we_i.value, dut.cfg_n_i.value = 1, 4071
    await ticks(dut)
    dut.cfg_n_we_i.value = 0
    await ticks(dut)
    assert int(dut.ready_o.value) == 0, "divider running: ready_o must be low"
    waited = await wait_ready(dut)
    assert 1 <= waited <= 40, f"divider took {waited} cycles"


@cocotb.test()
async def n_below_T_is_rejected_loudly(dut):
    """n < T would give a timestep with no event; it must fail an assertion, never silently continue."""
    await start_clock(dut); await reset(dut)
    dut.n_acc_i.value = 0
    dut.cfg_n_we_i.value, dut.cfg_n_i.value = 1, T - 1
    await ticks(dut)
    dut.cfg_n_we_i.value = 0
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 1, "n = T-1 must trip the 'n >= T at sample start' assertion"
