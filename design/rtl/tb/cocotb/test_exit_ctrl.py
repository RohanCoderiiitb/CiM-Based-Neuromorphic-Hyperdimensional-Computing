"""Phase 4 block: exit_ctrl - margin comparator, exit FSM, prediction register. Boundary margins (theta-1, theta, theta+1), the runtime enable, the last timestep, and the
EARLY_EXIT_EN = 0 build (never fires, still latches the final prediction)."""
import os

import cocotb
from cocotb.triggers import Timer

from common import G, reset, start_clock, ticks

EE = int(os.environ.get("EARLY_EXIT_EN", "1"))
NEVER = 4095


async def init(dut):
    dut.clr_i.value = dut.dec_valid_i.value = 0
    dut.dec_tstep_i.value = dut.top1_idx_i.value = dut.top1_i.value = dut.top2_i.value = 0
    dut.theta_i.value = NEVER
    dut.exit_en_i.value = 1
    await start_clock(dut)
    await reset(dut)


async def decide(dut, t, idx, top1, top2):
    dut.dec_valid_i.value, dut.dec_tstep_i.value, dut.top1_idx_i.value, dut.top1_i.value, dut.top2_i.value = 1, t, idx, top1, top2
    await Timer(1, unit="ns")
    fire = int(dut.fire_o.value)
    margin = int(dut.margin_o.value)
    await ticks(dut)
    dut.dec_valid_i.value = 0
    return fire, margin


@cocotb.test()
async def margin_boundaries(dut):
    await init(dut)
    for theta in (1, 2, 17, 64, 1000, 1990):
        for off in (-1, 0, 1):
            dut.clr_i.value = 1
            await ticks(dut)
            dut.clr_i.value = 0
            dut.theta_i.value = theta
            top2 = 5
            top1 = top2 + theta + off
            fire, margin = await decide(dut, 5, 3, top1, top2)
            if EE:
                assert margin == theta + off
                assert fire == int(theta + off >= theta), (theta, off, fire)
                if fire:
                    assert int(dut.exited_q_o.value) == 1 and int(dut.pred_valid_o.value) == 1
                    assert int(dut.pred_o.value) == 3 and int(dut.pred_tstep_o.value) == 5 and int(dut.pred_early_o.value) == 1
                    await ticks(dut)
                    assert int(dut.pred_valid_o.value) == 0, "prediction strobe must be one cycle"
                    assert int(dut.pred_o.value) == 3, "prediction must be held"
                else:
                    assert int(dut.exited_q_o.value) == 0 and int(dut.finished_o.value) == 0
            else:
                assert fire == 0 and int(dut.exited_q_o.value) == 0


@cocotb.test()
async def never_threshold_and_runtime_disable(dut):
    await init(dut)
    dut.theta_i.value = NEVER
    fire, _ = await decide(dut, 10, 2, 2000, 0)               # the largest possible margin cannot reach 4095
    assert fire == 0
    dut.theta_i.value = 1
    dut.exit_en_i.value = 0
    fire, _ = await decide(dut, 11, 2, 500, 10)
    assert fire == 0
    dut.exit_en_i.value = 1
    fire, _ = await decide(dut, 12, 4, 500, 10)
    assert fire == int(EE)


@cocotb.test()
async def last_timestep_finishes_without_firing(dut):
    await init(dut)
    dut.theta_i.value = NEVER
    fire, _ = await decide(dut, G.T - 1, 7, 900, 899)
    assert fire == 0
    assert int(dut.finished_o.value) == 1 and int(dut.pred_o.value) == 7 and int(dut.pred_tstep_o.value) == G.T - 1 and int(dut.pred_early_o.value) == 0
    assert int(dut.exited_q_o.value) == 0, "finishing is not an early exit"


@cocotb.test()
async def tie_gives_margin_zero(dut):
    await init(dut)
    dut.theta_i.value = 1
    fire, margin = await decide(dut, 3, 0, 40, 40)
    assert fire == 0 and (margin == 0 or not EE)
