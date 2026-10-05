"""Read counts per inference vs group size g, from 1E's golden count vectors (Phase 0 data, the same pattern scaleup.energy_inference uses): group reads issued (plane skipping on), reads with at least one active
row (the only ones that need the sense front-end if the a = 0 reads are skipped), and active rows per non-zero read. Usage: python -m sense.reads"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

import paths as RP


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "03_rtl" / "tb" / "common"))
    import golden as GD
    man, c, s, W = GD.load_dataset("dvsgesture", 0)
    counts = c["counts"].astype(np.int64)
    n_s, T_ts, n_addr = counts.shape
    bits = ((counts[..., None] >> np.arange(11)) & 1).astype(np.uint8)
    out = {}
    for g in (4, 8, 16, 32):
        A = bits.reshape(n_s, T_ts, n_addr // g, g, 11).sum(axis=3, dtype=np.int16)
        row_nz = (A.sum(axis=2) > 0)
        issued = row_nz.sum(axis=(1, 2)) * (n_addr // g)
        nz = (A > 0).sum(axis=(1, 2, 3)); act = A.sum(axis=(1, 2, 3))
        out[str(g)] = dict(reads_issued=float(issued.mean()), reads_nonzero=float(nz.mean()), active_rows=float(act.mean()), mean_active_per_nonzero=float(act.mean() / nz.mean()),
                           max_active_per_read=int(A.max()), a_hist=[float(((A == k).sum(axis=(1, 2, 3))).mean()) for k in range(0, int(A.max()) + 1)], cycles_all_reads=float(409028 + issued.mean()), cycles_skip_zero=float(409028 + nz.mean()))
        print(g, out[str(g)])
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "read_counts.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
