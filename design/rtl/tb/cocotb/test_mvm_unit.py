"""Level 3: blocks B + D + E + G as one unit (wrapper mvm_unit). X must equal the golden integer MVM for empty / one address / all addresses /
one maxed / real count vectors. Run for every g in the sweep (the runner builds mvm_unit once per g), each run logs X so that the g-sweep
check can assert X is IDENTICAL at every g - grouping changes how many reads happen, never the answer."""
import json
import os
from pathlib import Path

import cocotb
import numpy as np

from common import G, reset, start_clock, ticks, unpack_signed, write_weights

G_ROWS = int(os.environ.get("ROWS_PER_GROUP", "8"))
COLS = int(os.environ.get("N_PARALLEL_COLS", "160"))
SKIP = int(os.environ.get("PLANE_SKIP_EN", "1"))
OUT = Path(os.environ.get("MVM_OUT", "/tmp/mvm_x.json"))
NG = -(-512 // G_ROWS)
PASSES = 160 // COLS


async def inject(dut, counts):
    for a in np.flatnonzero(counts):
        for _ in range(int(counts[a])):
            dut.ev_valid_i.value, dut.ev_addr_i.value = 1, int(a)
            await ticks(dut)
    dut.ev_valid_i.value = 0
    while int(dut.busy_o.value):
        await ticks(dut)
    await ticks(dut)


async def mvm(dut, counts):
    await inject(dut, counts)
    dut.start_i.value = 1
    await ticks(dut)
    dut.start_i.value = 0
    guard = 0
    while not int(dut.seq_done_o.value):
        await ticks(dut)
        guard += 1
        assert guard < 200000
    await ticks(dut, 3)                                              # pipeline drain (macro + accumulate)
    x = unpack_signed(int(dut.x_o.value), 20, 21)
    stats = dict(rows_skipped=int(dut.rows_skipped_o.value), rows_read=int(dut.rows_read_o.value), reads_allcols=int(dut.reads_allcols_o.value),
                 reads_plane=int(dut.reads_plane_o.value), reads_issued=int(dut.reads_issued_o.value), zero_groups=int(dut.zero_groups_o.value))
    dut.wipe_i.value = 1
    await ticks(dut)
    dut.wipe_i.value = 0
    await ticks(dut)
    return x, stats


def vectors():
    man, c, s, W = G.load_dataset("dvsgesture", 0)
    out = [("empty", np.zeros(512, np.int64)), ("one address", np.eye(1, 512, 300, dtype=np.int64)[0] * 3),
           ("all addresses", np.ones(512, np.int64)), ("one address maxed", np.eye(1, 512, 41, dtype=np.int64)[0] * 2047),
           ("two maxed + singles", np.where(np.isin(np.arange(512), (0, 511)), 2047, 1).astype(np.int64))]
    for r, t in ((0, 0), (11, 50), (77, 99), (200, 33)):          # real, sampled from the measured DVS-Gesture counts
        out.append((f"real row {r} t {t}", c["counts"][r, t].astype(np.int64)))
    return out, W


@cocotb.test()
async def x_matches_golden_for_every_vector(dut):
    for s in ("ev_valid_i", "ev_addr_i", "wipe_i", "wr_en_i", "wr_macro_i", "wr_addr_i", "wr_data_i", "start_i"):
        getattr(dut, s).value = 0
    await start_clock(dut); await reset(dut)
    vecs, W = vectors()
    await write_weights(dut, W)
    log = {}
    for name, counts in vecs:
        x, st = await mvm(dut, counts)
        ref = G.IM.snn_forward(counts[None, :], W, np.full(20, 1 << 40, np.int64)).X[0]       # golden X of this single count vector
        assert x == list(ref), f"g={G_ROWS}: {name}: X differs from int_model (first diff at neuron {int(np.argmax(np.array(x) != ref))})"
        nz_rows = sum(1 for b in range(11) if ((counts >> b) & 1).any())
        exp_rows = nz_rows if SKIP else 11
        assert st["rows_read"] == exp_rows and st["rows_skipped"] == 11 - exp_rows, f"{name}: skip accounting {st}"
        assert st["reads_allcols"] == exp_rows * NG and st["reads_plane"] == exp_rows * NG * 8 and st["reads_issued"] == exp_rows * NG * PASSES
        log[name] = dict(X=x, stats=st)
    assert int(dut.assert_fail_o.value) == 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(g=G_ROWS, cols=COLS, skip=SKIP, vectors=log)))
