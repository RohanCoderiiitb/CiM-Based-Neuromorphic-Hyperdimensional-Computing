"""Block C: event_ctr. The rule is t(k) = floor(k*T/n). Reference = events.boundary_counter_bins / bin_sizes (Phase 0)."""
import cocotb
import numpy as np

from common import G, reset, start_clock, ticks

T = G.T


async def run_sample(dut, n, gap_every=0):
    """Feed n events; return (timestep of each event, boundary flags)."""
    dut.cfg_n_we_i.value, dut.cfg_n_i.value, dut.ev_valid_i.value, dut.clr_i.value = 1, n, 0, 0
    await ticks(dut)
    dut.cfg_n_we_i.value = 0
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    ts, bnd = [], []
    k = 0
    while k < n:
        if gap_every and k % gap_every == 0:
            dut.ev_valid_i.value = 0
            await ticks(dut)
        dut.ev_valid_i.value = 1
        await cocotb.triggers.Timer(1, unit="ns")          # combinational outputs settle
        ts.append(int(dut.tstep_o.value)); bnd.append(int(dut.boundary_o.value))
        await ticks(dut)
        k += 1
    dut.ev_valid_i.value = 0
    await ticks(dut, 2)
    return np.array(ts), np.array(bnd)


@cocotb.test()
async def rule_floor_k_T_over_n(dut):
    await start_clock(dut); await reset(dut)
    for n in (T, T + 1, 199, 250, 1000, 4071, 12345, 20001):
        ts, bnd = await run_sample(dut, n)
        ref = G.EV.boundary_counter_bins(n, T)               # reference hardware counter: t(k) for every event
        assert np.array_equal(ts, ref), f"n={n}: timestep of event differs from the reference counter"
        assert int(bnd.sum()) == T, f"n={n}: {int(bnd.sum())} boundaries, expected exactly T={T}"
        sizes = np.bincount(ts, minlength=T)
        assert np.array_equal(sizes, G.EV.bin_sizes(n, T)), f"n={n}: timestep sizes differ from ceil((t+1)n/T)-ceil(tn/T)"
        assert set(np.unique(sizes)) <= {n // T, n // T + 1}, f"n={n}: sizes not in {{N_e, N_e+1}}"
        assert int(dut.sample_done_o.value) == 1
        assert int(dut.assert_fail_o.value) == 0
        # boundary flags sit on the last event of each timestep
        last_of_ts = np.r_[ts[1:] != ts[:-1], True]
        assert np.array_equal(bnd.astype(bool), last_of_ts)


@cocotb.test()
async def events_with_idle_gaps(dut):
    await start_clock(dut); await reset(dut)
    ts, bnd = await run_sample(dut, 1000, gap_every=7)
    assert np.array_equal(ts, G.EV.boundary_counter_bins(1000, T)) and int(bnd.sum()) == T
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def n_below_T_is_rejected_loudly(dut):
    """n < T would need the multi-fire `while`; it must fail an assertion, never silently single-fire."""
    await start_clock(dut); await reset(dut)
    dut.cfg_n_we_i.value, dut.cfg_n_i.value = 1, T - 1
    await ticks(dut)
    dut.cfg_n_we_i.value = 0
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 1, "n = T-1 must trip the 'n >= T at sample start' assertion"
