"""Phase 4 block: top2_tree - leader value + lowest index, and the SECOND-LARGEST VALUE, without a sort. Random vectors, forced ties, all-equal, zeros; the expected values come from the
Phase 2-4 reference (hdc_query.top2_tournament, itself checked here against a sort)."""
import os

import cocotb
import numpy as np

from common import G, reset, start_clock, ticks

N = int(os.environ.get("N", "10"))
W = 11
HQ = None


def ref():
    global HQ
    if HQ is None:
        from tb.common import hdc_golden as H
        HQ = H.HQ
    return HQ


async def check(dut, scores):
    dut.scores_i.value = sum(int(v) << (W * i) for i, v in enumerate(scores))
    await ticks(dut, 3)
    got = (int(dut.i1_o.value), int(dut.v1_o.value), int(dut.v2_o.value))
    exp = ref().top2_tournament(scores)
    s = sorted(scores, reverse=True)
    assert exp[1] == s[0] and exp[2] == s[1], "reference tournament disagrees with the sort"
    assert exp[0] == int(np.argmax(scores)), "reference leader is not the lowest-index maximum"
    assert got == (exp[0], exp[1], exp[2]), f"{scores}: got {got}, expected {exp}"


@cocotb.test()
async def random_and_structured(dut):
    dut.scores_i.value = 0
    await start_clock(dut)
    await reset(dut)
    rng = np.random.default_rng(7)
    for hi in (3, 20, 2000):                                   # tiny range = many ties
        for _ in range(400):
            await check(dut, rng.integers(0, hi + 1, N).tolist())
    await check(dut, [0] * N)
    await check(dut, [2000] * N)
    for k in range(N):                                         # a single leader at every position, others equal
        v = [5] * N; v[k] = 9
        await check(dut, v)
        v = [9] * N; v[k] = 5
        await check(dut, v)
    for a in range(N):                                         # two tied leaders at every pair of positions: second == leader, lowest index wins
        for b in range(a + 1, N):
            v = rng.integers(0, 50, N).tolist(); v[a] = v[b] = 77
            await check(dut, v)
