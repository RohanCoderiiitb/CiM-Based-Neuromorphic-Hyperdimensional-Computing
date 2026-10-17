"""Block H: if_neuron_array. Reference = int_model.snn_forward. X sequences are built by feeding snn_forward counts/weights where
X_j(t) = 127*(counts[t, j] - counts[t, 20 + j]) so any signed sequence is expressible, and the golden trace supplies X, V and spikes."""
import cocotb
import numpy as np

from common import G, reset, start_clock, ticks, to_signed, unpack_signed

WX, WV, WT = 21, 26, 15


def make_case(deltas, thresh):
    """deltas [T, 20] signed ints (|d| <= 2047) -> (counts, W) such that X_j(t) = 127*d[t, j]."""
    T = deltas.shape[0]
    counts = np.zeros((T, 512), np.int64)
    counts[:, :20] = np.maximum(deltas, 0)
    counts[:, 20:40] = np.maximum(-deltas, 0)
    W = np.zeros((20, 512), np.int8)
    for j in range(20):
        W[j, j], W[j, 20 + j] = 127, -127
    return counts, W, np.asarray(thresh, np.int64)


async def init(dut):
    for s in ("clr_i", "upd_i", "x_i", "thresh_i", "thresh_shared_i"):
        getattr(dut, s).value = 0
    await start_clock(dut); await reset(dut)


def pack(vals, w):
    return sum((int(v) & ((1 << w) - 1)) << (i * w) for i, v in enumerate(vals))


async def play(dut, X, thresh, shared=False):
    dut.clr_i.value = 1
    await ticks(dut)
    dut.clr_i.value = 0
    dut.thresh_i.value = pack(thresh, WT)
    dut.thresh_shared_i.value = int(shared)
    S, V = [], []
    for t in range(X.shape[0]):
        dut.x_i.value, dut.upd_i.value = pack(X[t], WX), 1
        await ticks(dut)
        dut.upd_i.value = 0
        S.append([(int(dut.spike_o.value) >> j) & 1 for j in range(20)])
        V.append(unpack_signed(int(dut.v_o.value), 20, WV))
        await ticks(dut)
    return np.array(S, np.uint8), np.array(V, np.int64)


@cocotb.test()
async def threshold_edges(dut):
    """Exactly at threshold, one below, one above - all through the golden model. X is a multiple of 127, so the threshold is placed at
    V1 + 1 / V1 / V1 - 1 where V1 = X0 + X1 is the membrane potential after the second step."""
    await init(dut)
    rng = np.random.default_rng(4)
    for off in (+1, 0, -1):                       # threshold = V1 + off  ->  V1 is one below / exactly at / one above the threshold
        a = rng.integers(1, 60, 20)                # keeps thresholds inside the 15-bit signed threshold register (127*(a+b)+1 < 16384)
        b = rng.integers(1, 60, 20)
        d = np.stack([a, b])                      # X0 = 127 a, X1 = 127 b (both positive, so V0 < thr and the first step cannot spike)
        thr = 127 * (a + b) + off
        counts, W, th = make_case(d, thr)
        tr = G.reference_trace(counts, W, th)
        S, V = await play(dut, tr.X, thr)
        want = int(off <= 0)
        assert list(tr.S[1]) == [want] * 20, "golden-model self-check of the edge construction"
        assert np.array_equal(S, tr.S) and np.array_equal(V, tr.V), f"threshold offset {off:+d}: DUT differs from int_model.snn_forward"
        assert all(V[1][j] == (0 if want else 127 * (a[j] + b[j])) for j in range(20)), "V must be 0 right after a spike"
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def random_and_long_negative_runs_match_golden(dut):
    await init(dut)
    rng = np.random.default_rng(9)
    thr = rng.integers(500, 12000, 20)
    d = rng.integers(-60, 60, (100, 20))
    d[10:90, 3] = -2047                                            # neuron 3: long negative run, V sinks to about -21e6 (26 bits needed)
    d[:, 7] = np.where(np.arange(100) % 5 == 0, 2000, -30)         # neuron 7: spikes and resets repeatedly
    counts, W, th = make_case(d, thr)
    tr = G.reference_trace(counts, W, th)
    S, V = await play(dut, tr.X, thr)
    assert np.array_equal(S, tr.S), "spikes differ from int_model.snn_forward"
    assert np.array_equal(V, tr.V), "V differs from int_model.snn_forward"
    assert V[:, 3].min() < -(1 << 24), "the long negative run did not exercise the wide V"
    assert int(dut.assert_fail_o.value) == 0


@cocotb.test()
async def real_sample_and_shared_threshold(dut):
    await init(dut)
    man, c, s, W = G.load_dataset("dvsgesture", 0)
    tr = G.reference_trace(c["counts"][3], W, s["thresh_int"][3])
    S, V = await play(dut, tr.X, s["thresh_int"][3])
    assert np.array_equal(S, tr.S) and np.array_equal(V, tr.V)
    man, c, s, W = G.load_dataset("nmnist", 0)               # per-tensor: one threshold shared by all 20 neurons
    th = s["thresh_int"][2]
    assert len(set(th.tolist())) == 1
    tr = G.reference_trace(c["counts"][2], W, th)
    S, V = await play(dut, tr.X, np.r_[th[0], np.zeros(19, np.int64)], shared=True)    # only register 0 is meaningful in shared mode
    assert np.array_equal(S, tr.S) and np.array_equal(V, tr.V)
    assert int(dut.assert_fail_o.value) == 0
