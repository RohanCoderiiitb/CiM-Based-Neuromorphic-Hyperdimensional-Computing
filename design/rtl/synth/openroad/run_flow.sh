#!/bin/bash
# run_flow.sh BUILD - the OpenROAD flow, one process per stage (each stage reads the previous stage's database). OPENROAD=<binary> (default: openroad on PATH).
set -u
B=${1:-full}
cd "$(dirname "$0")/.."
OR=${OPENROAD:-openroad}
python3 openroad/sanitize_tech_lef.py
mkdir -p results/openroad/$B
for S in ${STAGES_LIST:-floorplan place cts groute}; do
  echo "== $S $(date +%T)"
  BUILD=$B STAGES=$S $OR -no_init -exit openroad/run_flow.tcl > results/openroad/$B/$S.log 2>&1
  if ! grep -q "STAGES DONE" results/openroad/$B/$S.log; then echo "STAGE $S FAILED: $(grep -m1 ERROR results/openroad/$B/$S.log)"; exit 1; fi
done
echo "FLOW DONE $(date +%T)"
