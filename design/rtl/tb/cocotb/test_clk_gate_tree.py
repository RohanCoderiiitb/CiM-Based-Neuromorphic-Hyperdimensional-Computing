"""clk_gate_tree: every word's gated clock rises in a cycle exactly when it should (clr enables every word; otherwise only the addressed word, and only when we_i is high) - never an extra
edge, never a missing one, whatever the sequence of enables and addresses. Checked by counting the rising edges each word's gated clock produced."""
import os

import cocotb
import numpy as np

from common import start_clock, ticks

N = int(os.environ.get("N", "512"))


def snapshot(dut):
    v = int(dut.edges_o.value)
    return np.array([(v >> (4 * i)) & 0xF for i in range(N)], np.int64)


@cocotb.test()
async def edges_match_enables(dut):
    dut.clr_i.value = dut.we_i.value = 0
    dut.addr_i.value = 0
    await start_clock(dut)
    await ticks(dut, 3)
    rng = np.random.default_rng(7)
    prev = snapshot(dut)
    hit = np.zeros(N, np.int64)
    for cyc in range(3000):
        clr = int(rng.random() < 0.01)
        we = int(rng.random() < 0.6)
        # runs of the same address (like back-to-back events) and jumps, including both ends of the range
        addr = int(rng.choice([0, N - 1, int(rng.integers(0, N))])) if rng.random() < 0.3 else int(rng.integers(0, N))
        dut.clr_i.value, dut.we_i.value, dut.addr_i.value = clr, we, addr
        await ticks(dut)                       # the rising edge happens inside this wait; the enables were set half a cycle before it
        cur = snapshot(dut)
        exp = np.ones(N, np.int64) if clr else (np.eye(N, dtype=np.int64)[addr] if we else np.zeros(N, np.int64))
        got = (cur - prev) % 16
        assert np.array_equal(got, exp), f"cycle {cyc}: clr={clr} we={we} addr={addr}: words with the wrong edge count {np.nonzero(got != exp)[0][:8]} (got {got[got != exp][:8]}, expected {exp[got != exp][:8]})"
        hit += exp
        prev = cur
    assert hit.min() > 0 or N > 512, "some word was never written in the test"
