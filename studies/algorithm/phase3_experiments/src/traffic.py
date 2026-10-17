import json, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(os.path.dirname(HERE), 'phase1_firing_characterization', 'firing_rate_summary.json')
S = json.load(open(DATA))
dv = S['dvsgesture_frozen']; nm = S['nmnist']
n, T, N, n_in, wbits = 20, 100, 10, 512, 8

print("=" * 74)
print("WHERE DOES NEUROHDC'S MEMORY TRAFFIC ACTUALLY GO? (per sample)")
print("=" * 74)
for lbl, d, Ncls in [("DVS-Gesture", dv, 10), ("N-MNIST", nm, 10)]:
    ev = d['n_events']['mean']; sp = d['spikes_per_sample']['mean']
    # SNN: eq.(20) - every event, ALL n neurons read one 8-bit weight from their own SRAM
    snn_reads = ev * n
    snn_bits = snn_reads * wbits
    # Query: eq.(21) - per timestep, per class, read n bits of class HV
    q_reads = T * Ncls
    q_bits = q_reads * n
    print(f"\n### {lbl}:  {ev:,.0f} events/sample")
    print(f"  SNN weight reads : {snn_reads:14,.0f} accesses   {snn_bits:14,.0f} bits")
    print(f"  Class-HV reads   : {q_reads:14,.0f} accesses   {q_bits:14,.0f} bits")
    print(f"  ---> SNN side is {snn_reads / q_reads:9,.0f}x the ACCESSES, "
          f"{snn_bits / q_bits:9,.0f}x the BITS")
    print(f"  ---> query is {100 * q_bits / (q_bits + snn_bits):.4f}% of total memory traffic")
    save = 0.625 * q_bits
    print(f"  ---> eliminating 100% of query traffic saves "
          f"{100 * q_bits / (q_bits + snn_bits):.4f}% of total;")
    print(f"       the 62.5% sparsity exploit saves {100 * save / (q_bits + snn_bits):.4f}% of total")

print("\n" + "=" * 74)
print("CROSSBAR: does the ADC floor cap the sparsity win?  (A1, per inference)")
print("=" * 74)
r = dv['global_firing_rate']
rows_act = dv['spikes_per_sample']['mean']  # 751 of 2000 over the whole sample
print(f"Per-timestep scheme  : {T} steps x {N} cols = {T * N:,} ADC conversions")
print(f"   rows activated    : {r * n:.1f} of {n} per step  -> array energy scales {r:.3f}x")
print(f"   ADC energy        : scales 1.000x  (conversion count independent of sparsity)")
for adc_frac in [0.3, 0.5, 0.6, 0.7]:
    tot = adc_frac * 1.0 + (1 - adc_frac) * r
    print(f"   if ADC = {100 * adc_frac:2.0f}% of read energy -> total saving = {100 * (1 - tot):4.1f}%  "
          f"(not {100 * (1 - r):.1f}%)")
print(f"\nBuffered whole-vector scheme (one 2000-row MVM at the end):")
print(f"   ADC conversions   : {N} (one per class)  -> {T * N / N:,.0f}x fewer")
print(f"   rows activated    : {rows_act:.0f} of {n * T} ({100 * rows_act / (n * T):.1f}%)")
print(f"   BUT dynamic range : 0..{rows_act:.0f} -> ~{len(bin(int(rows_act))) - 2}-bit ADC, "
      f"analog sum over {rows_act:.0f} devices")
