"""Level 3: blocks B + D + E + G + H as one unit (wrapper mvm_unit). X must equal the golden integer MVM for empty / one address / all addresses / one maxed / real count vectors, and for
weights that exercise the int8 sign plane (-128, -1, 0, +1, +127). The read accounting is the PACKED-ROW rule: a read drives up to 4 active rows of one count bit-plane inside one 128-row band,
so reads = sum over bands and planes of ceil(n_active / S_ROWS). Each run logs X (the cols sweep asserts X is identical for every N_PARALLEL_COLS)."""
import json
import os
from pathlib import Path

import cocotb
import numpy as np

from common import G, reset, start_clock, ticks, unpack_signed, write_weights

G_ROWS = int(os.environ.get("ROWS_PER_GROUP", "4"))
import re as _re
from pathlib import Path as _P
S_ROWS = int(_re.search(r"localparam int S_ROWS\s*=\s*(\d+)", (_P(__file__).resolve().parents[2] / "rtl" / "pkg" / "cim_neurohdc_pkg.sv").read_text()).group(1))
COLS = int(os.environ.get("N_PARALLEL_COLS", "40"))
OUT = Path(os.environ.get("MVM_OUT", "/tmp/mvm_x.json"))
PASSES = 160 // COLS
WX = 21


async def inject(dut, counts):
    for a in np.flatnonzero(counts):
        n = int(counts[a])
        while n:
            await cocotb.triggers.Timer(1, unit="ns")
            if int(dut.lane_ok_o.value):
                dut.ev_valid_i.value, dut.ev_addr_i.value = 1, int(a)
                n -= 1
            else:
                dut.ev_valid_i.value = 0
            await ticks(dut)
    dut.ev_valid_i.value = 0
    while int(dut.busy_o.value):
        await ticks(dut)
    await ticks(dut)


def packed_reads(counts):
    n = 0
    for b in range(11):
        bits = ((counts >> b) & 1).reshape(4, 128)
        n += int(np.ceil(bits.sum(axis=1) / S_ROWS).sum())
    return n


async def mvm(dut, counts):
    await inject(dut, counts)
    dut.start_i.value = 1
    await ticks(dut)
    dut.start_i.value = 0
    guard = 0
    while not int(dut.xvalid_o.value):
        await ticks(dut)
        guard += 1
        assert guard < 400000
    x = unpack_signed(int(dut.x_o.value), 20, WX)
    stats = dict(rows_skipped=int(dut.rows_skipped_o.value), rows_read=int(dut.rows_read_o.value), reads_allcols=int(dut.reads_allcols_o.value),
                 reads_plane=int(dut.reads_plane_o.value), reads_issued=int(dut.reads_issued_o.value), zero_groups=int(dut.zero_groups_o.value), active=int(dut.active_o.value))
    await ticks(dut, 2)
    return x, stats


def vectors():
    man, c, s, W = G.load_dataset("dvsgesture", 0)
    out = [("empty", np.zeros(512, np.int64)), ("one address", np.eye(1, 512, 300, dtype=np.int64)[0] * 3),
           ("all addresses", np.ones(512, np.int64)), ("one address maxed", np.eye(1, 512, 41, dtype=np.int64)[0] * 2047),
           ("two maxed + singles", np.where(np.isin(np.arange(512), (0, 511)), 2047, 1).astype(np.int64))]
    for r, t in ((0, 0), (11, 50), (77, 99), (200, 33)):          # real, sampled from the measured DVS-Gesture counts
        out.append((f"real row {r} t {t}", c["counts"][r, t].astype(np.int64)))
    return out, W


async def run(dut, vecs, W, tag):
    log = {}
    await write_weights(dut, W)
    for name, counts in vecs:
        x, st = await mvm(dut, counts)
        ref = G.IM.snn_forward(counts[None, :], W, np.full(20, 1 << 40, np.int64)).X[0]       # golden X of this single count vector
        assert x == list(ref), f"{tag}: {name}: X differs from int_model (first diff at neuron {int(np.argmax(np.array(x) != ref))})"
        nz_rows = sum(1 for b in range(11) if ((counts >> b) & 1).any())
        reads = packed_reads(counts)
        assert st["rows_read"] == nz_rows and st["rows_skipped"] == 11 - nz_rows, f"{name}: skip accounting {st}"
        assert st["reads_allcols"] == reads and st["reads_plane"] == reads * 8 and st["reads_issued"] == reads * PASSES, f"{name}: read accounting {st} expected {reads} reads"
        assert st["zero_groups"] == 0 and st["active"] == int((counts > 0).sum()), f"{name}: {st}"
        log[name] = dict(X=x, stats=st)
    return log


@cocotb.test()
async def x_matches_golden_for_every_vector(dut):
    for s in ("ev_valid_i", "ev_addr_i", "wr_en_i", "wr_macro_i", "wr_addr_i", "wr_data_i", "start_i"):
        getattr(dut, s).value = 0
    await start_clock(dut); await reset(dut)
    while not int(dut.ready_o.value):                                # the post-reset sweep of the SRAM
        await ticks(dut)
    vecs, W = vectors()
    log = await run(dut, vecs, W, "real weights")
    assert int(dut.assert_fail_o.value) == 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(g=G_ROWS, cols=COLS, vectors=log)))


@cocotb.test()
async def sign_plane_directed_weights(dut):
    """Weights -128, -1, 0, +1, +127 (the sign-plane cases), a single address and the maximum count."""
    for s in ("ev_valid_i", "ev_addr_i", "wr_en_i", "wr_macro_i", "wr_addr_i", "wr_data_i", "start_i"):
        getattr(dut, s).value = 0
    await start_clock(dut); await reset(dut)
    while not int(dut.ready_o.value):
        await ticks(dut)
    W = np.zeros((20, 512), np.int8)
    for j, v in enumerate((-128, -1, 0, 1, 127)):
        W[j, :] = v
    vecs = [("one event", np.eye(1, 512, 0, dtype=np.int64)[0]), ("count 2047 at one address", np.eye(1, 512, 77, dtype=np.int64)[0] * 2047),
            ("all addresses c=1", np.ones(512, np.int64)), ("empty", np.zeros(512, np.int64))]
    await run(dut, vecs, W, "directed")
    x, _ = await mvm(dut, np.eye(1, 512, 9, dtype=np.int64)[0] * 2047)
    assert x[0] == -128 * 2047 and x[4] == 127 * 2047 and x[1] == -2047 and x[3] == 2047 and x[2] == 0
    assert int(dut.assert_fail_o.value) == 0
