"""Path bootstrap. Import this first in every entry-point.

Makes the (unmodified, copied) float model importable as `neurohdc`, and the
fixed-point package importable as `fixedpoint`. Defines the Phase-0 directory
constants so no script hard-codes a location.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(MODEL_DIR)                       # phase0_fixedpoint_reference/
FLOAT_SRC = os.path.join(MODEL_DIR, "neurohdc")         # verbatim copy of phase2 src
CKPT_DIR = os.path.join(ROOT, "artifacts", "checkpoints")
REF_RASTER_DIR = os.path.join(ROOT, "artifacts", "reference_rasters")
OUT_DIR = os.path.join(ROOT, "artifacts", "phase0")
VECTOR_DIR = os.path.join(ROOT, "tb", "vectors")
DOCS_DIR = os.path.join(ROOT, "docs")

for p in (FLOAT_SRC, MODEL_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)
