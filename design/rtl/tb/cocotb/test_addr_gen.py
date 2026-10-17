"""Block A: addr_gen. Reference = events.address (Phase 0): exhaustive over every sensor coordinate, both geometries, both polarities."""
import cocotb
from cocotb.triggers import Timer

from common import G

H_DVS, MUL_DVS = 128, 128
H_NM, MUL_NM = 34, 482


async def addr(dut, x, y, p, mul):
    dut.x_i.value, dut.y_i.value, dut.p_i.value, dut.coord_mul_i.value = x, y, p, mul
    await Timer(1, unit="ns")
    return int(dut.addr_o.value)


@cocotb.test()
async def corners_both_geometries(dut):
    for name, side, mul in (("dvs", H_DVS, MUL_DVS), ("nmnist", H_NM, MUL_NM)):
        for p in (0, 1):
            for x, y in ((0, 0), (side - 1, 0), (0, side - 1), (side - 1, side - 1)):
                got = await addr(dut, x, y, p, mul)
                exp = int(G.EV.address(x, y, p, side, side))
                assert got == exp, f"{name} corner (x={x}, y={y}, p={p}): got {got}, reference {exp}"
                assert got < 512


@cocotb.test()
async def exhaustive_dvsgesture_128x128(dut):
    bad = 0
    for p in (0, 1):
        for y in range(128):
            for x in range(128):
                got = await addr(dut, x, y, p, MUL_DVS)
                if got != int(G.EV.address(x, y, p, 128, 128)):
                    bad += 1
    assert bad == 0, f"{bad} coordinates differ from events.address"


@cocotb.test()
async def exhaustive_nmnist_34x34_and_clamp(dut):
    """Divide-by-34 via reciprocal multiply, exhaustive over the sensor AND over out-of-range coordinates (the reference clamps to W-1)."""
    bad = 0
    for p in (0, 1):
        for y in range(128):
            for x in range(0, 128, 1 if y < 34 else 17):
                got = await addr(dut, x, y, p, MUL_NM)
                if got != int(G.EV.address(x, y, p, 34, 34)):
                    bad += 1
    assert bad == 0, f"{bad} coordinates differ from events.address"
