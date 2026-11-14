"""Block A: addr_gen. Reference = events.address (Phase 0): exhaustive over every sensor coordinate, both geometries, both polarities. The block takes the AER word and the geometry flag:
128x128 word = p<<14 | y<<7 | x (7-bit fields), 34x34 word = p<<12 | y<<6 | x (6-bit fields)."""
import cocotb
from cocotb.triggers import Timer

from common import G

GEOM = {"dvs": (128, 7, 1), "nmnist": (34, 6, 0)}       # side, field width, geom_dvs_i


async def addr(dut, x, y, p, name, junk=0):
    side, sh, flag = GEOM[name]
    word = (p << (2 * sh)) | (y << sh) | x
    word |= junk << (2 * sh + 1)                          # bits above the polarity are ignored
    dut.aer_i.value, dut.geom_dvs_i.value = word & 0xFFFF, flag
    await Timer(1, unit="ns")
    return int(dut.addr_o.value)


@cocotb.test()
async def corners_both_geometries(dut):
    for name, (side, sh, flag) in GEOM.items():
        for p in (0, 1):
            for x, y in ((0, 0), (side - 1, 0), (0, side - 1), (side - 1, side - 1)):
                got = await addr(dut, x, y, p, name)
                exp = int(G.EV.address(x, y, p, side, side))
                assert got == exp, f"{name} corner (x={x}, y={y}, p={p}): got {got}, reference {exp}"
                assert got < 512


@cocotb.test()
async def exhaustive_dvsgesture_128x128(dut):
    bad = 0
    for p in (0, 1):
        for y in range(128):
            for x in range(128):
                got = await addr(dut, x, y, p, "dvs", junk=(x ^ y) & 1)
                if got != int(G.EV.address(x, y, p, 128, 128)):
                    bad += 1
    assert bad == 0, f"{bad} coordinates differ from events.address"


@cocotb.test()
async def exhaustive_nmnist_34x34_and_clamp(dut):
    """Divide-by-34 by a constant table, exhaustive over the sensor AND over the out-of-range values of the 6-bit fields (the reference clamps to the last cell)."""
    bad = 0
    for p in (0, 1):
        for y in range(64):
            for x in range(64):
                got = await addr(dut, x, y, p, "nmnist", junk=(x + y) & 7)
                if got != int(G.EV.address(x, y, p, 34, 34)):
                    bad += 1
    assert bad == 0, f"{bad} coordinates differ from events.address"
