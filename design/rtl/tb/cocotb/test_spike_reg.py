"""Block I (output): spike_reg - one-cycle valid strobe per timestep, timestep index, done after T strobes, assertion on misuse."""
import cocotb

from common import G, reset, start_clock, ticks

T = G.T


async def init(dut):
    dut.clr_i.value = dut.load_i.value = 0
    dut.spike_i.value = dut.tstep_i.value = 0
    await start_clock(dut); await reset(dut)


@cocotb.test()
async def one_strobe_per_timestep_and_done(dut):
    await init(dut)
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    for t in range(T):
        dut.spike_i.value, dut.tstep_i.value, dut.load_i.value = (0x5A5A5 ^ (t * 7919)) & 0xFFFFF, t, 1
        await ticks(dut)
        dut.load_i.value = 0
        assert int(dut.valid_o.value) == 1 and int(dut.tstep_o.value) == t and int(dut.spike_o.value) == ((0x5A5A5 ^ (t * 7919)) & 0xFFFFF)
        assert int(dut.done_o.value) == int(t == T - 1)
        await ticks(dut)
        assert int(dut.valid_o.value) == 0, "valid must be a single-cycle strobe"
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def skipped_timestep_trips_assertion(dut):
    await init(dut)
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    dut.load_i.value, dut.tstep_i.value = 1, 3         # strobe for timestep 3 although none were produced
    await ticks(dut)
    dut.load_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 1
