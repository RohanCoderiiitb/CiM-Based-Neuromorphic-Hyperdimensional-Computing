#!/bin/zsh
# Build CACTI 7 (HP Labs, github.com/HewlettPackard/cacti, cloned to ~/.cache/cim_neurohdc/cacti_src) and run the three configs of this folder.
# Check ref_1kB first: it must reproduce gen_macros.CACTI (3,745 um^2, 0.632 pJ read, 15.5 uW leakage); only then use class_960b (or class_1024b).
set -e
C=$HOME/.cache/cim_neurohdc/cacti_src; D=${0:A:h}
[ -x $C/cacti ] || (cd $C && make -j8)
for f in ref_1kB class_960b class_1024b; do
  (cd $C && ./cacti -infile $D/$f.cfg) > $D/$f.out 2>&1 || true
  echo "== $f"; grep -E "Total dynamic read energy per access|Total dynamic write energy per access|Total leakage power of a bank|Cache height x width|Data array: Area|Access time \(ns\)|Cycle time \(ns\)|ERROR|rror" $D/$f.out | head -10
done
