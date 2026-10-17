"""Block F: weight_load. The shift-in stream must land every Phase 0 export word at (macro, address) in macro-major order, 2560 words."""
import cocotb
import numpy as np

from common import G, reset, start_clock, ticks


def image_words(seed=0):
    files = G.weight_mem_files("dvsgesture", seed)
    return [G.read_mem(str(f)) for f in files]


async def init(dut):
    dut.start_i.value = dut.wl_valid_i.value = 0
    dut.wl_data_i.value = 0
    await start_clock(dut); await reset(dut)


@cocotb.test()
async def streams_the_whole_image_in_order(dut):
    await init(dut)
    img = image_words(0)
    dut.start_i.value = 1
    await ticks(dut)
    dut.start_i.value = 0
    seen = []
    for m in range(5):
        for a in range(512):
            dut.wl_valid_i.value, dut.wl_data_i.value = 1, img[m][a]
            await cocotb.triggers.Timer(1, unit="ns")
            assert int(dut.wl_ready_o.value) == 1
            assert int(dut.wr_en_o.value) == 1
            seen.append((int(dut.wr_macro_o.value), int(dut.wr_addr_o.value), int(dut.wr_data_o.value)))
            await ticks(dut)
    dut.wl_valid_i.value = 0
    await ticks(dut, 2)
    assert seen == [(m, a, img[m][a]) for m in range(5) for a in range(512)]
    assert len(seen) == 2560 and int(dut.done_o.value) == 1 and int(dut.busy_o.value) == 0
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def word_without_a_load_trips_assertion(dut):
    await init(dut)
    dut.wl_valid_i.value = 1
    await ticks(dut, 2)
    dut.wl_valid_i.value = 0
    await ticks(dut)
    assert int(dut.assert_fail_o.value) == 1
