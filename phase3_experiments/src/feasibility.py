import json, os, numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(os.path.dirname(HERE), 'phase1_firing_characterization', 'firing_rate_summary.json')
S = json.load(open(DATA)); dv = S['dvsgesture_frozen']; nm = S['nmnist']
n, T, N, n_in = 20, 100, 10, 512
ev = dv['n_events']['mean']; Ne = dv['N_e']['mean']; sp = dv['spikes_per_sample']['mean']

print("=" * 76); print("1. ANALOG INTEGRATION LEAK BUDGET  (Idea A: V_mem on the column)")
print("=" * 76)
print(f"events/sample={ev:,.0f}   N_e={Ne:,.0f} events/timestep")
# DVS-Gesture recordings ~6 s per gesture
for rate_lbl, tstep in [("chip-rate, 1 event/cycle @100MHz", Ne * 10e-9),
                        ("chip-rate @1GHz", Ne * 1e-9),
                        ("sensor real-time (~6 s/sample)", 6.0 / T)]:
    print(f"\n  timestep duration, {rate_lbl}: {tstep * 1e6:,.1f} us")
    for C_fF, Ileak_pA in [(50, 1), (100, 1), (100, 10), (500, 10)]:
        droop = (Ileak_pA * 1e-12) * tstep / (C_fF * 1e-15)
        flag = "OK" if droop < 0.05 else ("MARGINAL" if droop < 0.2 else "FAILS")
        print(f"    C={C_fF:4d}fF Ileak={Ileak_pA:3d}pA -> droop {droop * 1e3:10.2f} mV   {flag}")
print("\n  (fails if droop is a large fraction of a ~0.2-0.5 V signal swing)")

print("\n" + "=" * 76); print("2. BURST-ACCUMULATE HYBRID: conversions vs burst size B")
print("=" * 76)
print(f"{'B (events/burst)':>18s} {'conv/sample':>13s} {'vs 8.14M SRAM reads':>22s} {'burst dur @100MHz':>19s}")
for B in [1, 16, 64, 256, 1024, int(Ne)]:
    conv = (ev / B) * n
    print(f"{B:>18,d} {conv:>13,.0f} {ev * n / conv:>21,.0f}x {B * 10e-9 * 1e6:>17.2f} us")

print("\n" + "=" * 76); print("3. ARRAY SHAPES AND UTILIZATION (128x128 macro assumed)")
print("=" * 76)
for lbl, rows, cols in [("SNN weights  W_s (int8 -> 8 cells/weight)", n_in, n * 8),
                        ("SNN weights  W_s (1 cell/weight, MLC)", n_in, n),
                        ("Class HV  time-unrolled", n * T, N),
                        ("Class HV  time-unrolled, ASL-DVS", n * T, 24),
                        ("Class HV  FACTORIZED (Idea C): f + g", n + T, N)]:
    macros_r = int(np.ceil(rows / 128)); macros_c = int(np.ceil(cols / 128))
    util = rows * cols / (macros_r * 128 * macros_c * 128)
    print(f"  {lbl:42s} {rows:5d} x {cols:4d}  -> {macros_r}x{macros_c} macro(s), util {100 * util:5.1f}%")
print(f"\n  Class-HV storage: full {n * T * N:,} bits  vs factorized {(n + T) * N:,} bits "
      f"-> {n * T * N / ((n + T) * N):.1f}x smaller")

print("\n" + "=" * 76); print("4. ROW UTILIZATION PER ACCESS IN THE QUERY ARRAY")
print("=" * 76)
print(f"  per timestep: {n} of {n * T} rows addressable = {100 * n / (n * T):.1f}%; "
      f"spike-gated -> {dv['global_firing_rate'] * n:.1f} rows = {100 * dv['global_firing_rate'] * n / (n * T):.2f}%")
print(f"  whole-sample analog accumulation: {sp:.0f} of {n * T} rows = {100 * sp / (n * T):.1f}% -> "
      f"{N} conversions instead of {T * N:,}")
