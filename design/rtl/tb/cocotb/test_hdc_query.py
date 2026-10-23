"""Phase 2 block: hdc_query - both class-HV mappings, bit-exact against the reference (hdc_query.py) at EVERY timestep prefix, and the pipeline contract (decision valid exactly four
cycles after the spike strobe, busy covers it, a premature spike trips the assertion).

FACTORIZED = 0 loads a 2000 x N class memory and scores by XNOR-popcount; FACTORIZED = 1 loads a 20 x N array + T x N sign table + N bias registers and scores by AND-popcount.
The class hypervector is (a) the real R=1 checkpoint of seed 0 and (b) random bits; spike streams are the real golden rasters and random vectors of several densities."""
import os

import cocotb
import numpy as np
from cocotb.triggers import Timer

from common import G, reset, start_clock, ticks

FACT = int(os.environ.get("FACTORIZED", "1"))
N = int(os.environ.get("N_CLASSES", "10"))
T = G.T
W = 11
ARRAY, SIGN, BIAS = 0, 1, 2
_H = None


def H():
    global _H
    if _H is None:
        from tb.common import hdc_golden as hg
        _H = hg
    return _H


async def init(dut):
    dut.clr_i.value = dut.cm_we_i.value = dut.spike_valid_i.value = 0
    dut.cm_sel_i.value = dut.cm_addr_i.value = dut.cm_data_i.value = dut.spike_i.value = dut.tstep_i.value = 0
    await start_clock(dut)
    await reset(dut)


async def cm_write(dut, sel, addr, data):
    dut.cm_we_i.value, dut.cm_sel_i.value, dut.cm_addr_i.value, dut.cm_data_i.value = 1, sel, addr, data
    await ticks(dut)
    dut.cm_we_i.value = 0


async def load_image(dut, class_hv, a_bits=None, b_bits=None):
    """class_hv [N,T,20] for the unfactorized build; (a_bits [N,20], b_bits [N,T]) for the factorized build."""
    if FACT:
        await cm_write(dut, ARRAY, 0, sum(int(a_bits[i, j]) << (20 * i + j) for i in range(N) for j in range(20)))
        for t in range(T):
            await cm_write(dut, SIGN, t, sum(int(b_bits[i, t]) << i for i in range(N)))
        await cm_write(dut, BIAS, 0, sum(int(a_bits[i].sum()) << (5 * i) for i in range(N)))
    else:
        for t in range(T):
            await cm_write(dut, ARRAY, t, sum(int(class_hv[i, t, j]) << (20 * i + j) for i in range(N) for j in range(20)))
    await ticks(dut)


async def run_sample(dut, S, prefix, gaps=(0,)):
    """Drive one sample's spike vectors; at every decision compare scores, leader, second score. Returns the cycles between strobe and decision (must be 4)."""
    HQ = H().HQ
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    await ticks(dut)
    for t in range(T):
        dut.spike_i.value = int("".join(str(int(b)) for b in S[t][::-1]), 2)
        dut.tstep_i.value = t
        dut.spike_valid_i.value = 1
        await Timer(1, unit="ns")
        assert int(dut.busy_o.value) == 1, "busy must be high in the strobe cycle"
        await ticks(dut)
        dut.spike_valid_i.value = 0
        n = 0
        while not int(dut.dec_valid_o.value):
            assert int(dut.busy_o.value) == 1, "busy dropped before the decision"
            await ticks(dut)
            n += 1
            assert n < 20
        assert n == 3, f"decision {n + 1} cycles after the strobe, expected 4"
        assert int(dut.busy_o.value) == 1, "busy must cover the decision cycle"
        sc = [(int(dut.scores_o.value) >> (W * i)) & ((1 << W) - 1) for i in range(N)]
        assert sc == prefix[t].tolist(), f"t={t}: scores {sc} != reference {prefix[t].tolist()}"
        i1, v1, v2 = HQ.top2_tournament(prefix[t])
        assert (int(dut.top1_idx_o.value), int(dut.top1_o.value), int(dut.top2_o.value)) == (i1, v1, v2)
        assert int(dut.dec_tstep_o.value) == t and int(dut.rows_gated_o.value) == int(S[t].sum())
        await ticks(dut)
        assert int(dut.busy_o.value) == 0 and int(dut.dec_valid_o.value) == 0
        for _ in range(gaps[t % len(gaps)]):
            await ticks(dut)
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def real_r1_model_real_rasters(dut):
    """The seed-0 R=1 checkpoint and its golden rasters: the factorized build with (a, b), the unfactorized build with the expanded class hypervector."""
    if N != 10:
        return                                      # the golden networks have 10 classes
    await init(dut)
    m = H().load_model("r1", 0)
    await load_image(dut, m["class_hv"], m["a_bits"], m["b_bits"])
    for row in (0, 1, 2, 77, 150, 239):
        await run_sample(dut, m["spikes"][row], m["prefix"][row], gaps=(0, 3))


@cocotb.test()
async def random_class_image_random_spikes(dut):
    """Random bits at several densities (rank-1 random factors for the factorized build, unconstrained random class hypervector for the unfactorized one)."""
    await init(dut)
    HQ = H().HQ
    rng = np.random.default_rng(11)
    for trial in range(4):
        if FACT:
            a = rng.integers(0, 2, (N, 20)).astype(np.uint8)
            b = rng.integers(0, 2, (N, T)).astype(np.uint8)
            hv = HQ.expand_r1(a, b)
            await load_image(dut, hv, a, b)
        else:
            hv = rng.integers(0, 2, (N, T, 20)).astype(np.uint8)
            await load_image(dut, hv)
        dens = (0.05, 0.4, 0.75, 1.0)[trial]
        S = (rng.random((T, 20)) < dens).astype(np.uint8)
        prefix = HQ.prefix_scores(HQ.agree_unfactorized(S, hv))
        await run_sample(dut, S, prefix)
    # all-zero and all-one spike vectors against the extreme class images
    S = np.zeros((T, 20), np.uint8)
    await run_sample(dut, S, HQ.prefix_scores(HQ.agree_unfactorized(S, hv)))
    S = np.ones((T, 20), np.uint8)
    await run_sample(dut, S, HQ.prefix_scores(HQ.agree_unfactorized(S, hv)))


@cocotb.test()
async def spike_during_scoring_trips_assertion(dut):
    if N != 10:
        return
    await init(dut)
    m = H().load_model("r1", 0)
    await load_image(dut, m["class_hv"], m["a_bits"], m["b_bits"])
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    dut.spike_i.value, dut.tstep_i.value, dut.spike_valid_i.value = 0x12345, 0, 1
    await ticks(dut)
    dut.tstep_i.value = 1                                      # second strobe while the first is in the pipeline
    await ticks(dut)
    dut.spike_valid_i.value = 0
    for _ in range(3):
        await ticks(dut)
    assert int(dut.assert_fail_o.value) == 1
