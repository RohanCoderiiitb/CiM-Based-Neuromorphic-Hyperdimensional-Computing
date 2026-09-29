import json, os, numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(os.path.dirname(HERE), 'phase1_firing_characterization', 'firing_rate_summary.json')
S = json.load(open(DATA)); dv = S['dvsgesture_frozen']; nm = S['nmnist']
n, T, N = 20, 100, 10
print("=" * 78); print("LAYOUT COMPARISON UNDER A PARAMETRIC ACCESS-ENERGY MODEL")
print("E_access = E_fix + E_bit * width.  alpha = E_fix/E_bit = per-access overhead")
print("=" * 78)


def layouts(fa, sp):
    return {
        # name: (n_accesses, width_bits) per sample per class
        'A dense timestep-major (NeuroHDC ASIC)': (T, n),
        'B per-spike indexed bit access': (sp, 1),
        'C neuron-major, skip all-silent rows': (n * fa, T),
        'D neuron-major, dense (no skip)': (n, T),
        'E timestep-major + mask-gated bitline': (T, n),  # same accesses, gated bits
    }


def run(alphas=(0, 5, 20, 50, 200)):
    for label, d in [('DVS-Gesture s0', dv), ('N-MNIST', nm)]:
        fa = d['frac_active_neurons_mean']; sp = d['spikes_per_sample']['mean']; r = d['global_firing_rate']
        L = layouts(fa, sp)
        print(f"\n### {label}: r={r:.4f}, frac_active_neurons={fa:.4f}, spikes/sample={sp:.1f}")
        print(f"{'layout':42s} {'acc':>7s} {'width':>6s} | " + " ".join(f"a={a:<5g}" for a in alphas))
        base = None
        for name, (acc, w) in L.items():
            row = []
            for a in alphas:
                e = acc * (a + w)
                if name.startswith('E'):  # mask-gated: only k_t of n bitlines toggle
                    e = acc * (a + w * r)
                row.append(e)
            if base is None: base = row
            rel = " ".join(f"{row[i] / base[i]:5.2f}x" for i in range(len(row)))
            print(f"{name:42s} {acc:7.1f} {w:6d} | {rel}")
        print(f"{'':42s} {'':7s} {'':6s} | (relative to layout A; <1.00 = better)")


if __name__ == "__main__":
    run()

    print("\n" + "=" * 78)
    print("BREAK-EVEN: at what per-access overhead alpha does each layout beat dense-A?")
    print("=" * 78)
    for label, d in [('DVS-Gesture s0', dv), ('N-MNIST', nm)]:
        fa = d['frac_active_neurons_mean']; sp = d['spikes_per_sample']['mean']; r = d['global_firing_rate']
        # B: sp*(a+1) < T*(a+n)  ->  a(sp-T) < T*n - sp -> a < (T*n-sp)/(sp-T)
        aB = (T * n - sp) / (sp - T) if sp > T else np.inf
        # C: n*fa*(a+T) < T*(a+n) -> a(n*fa-T) < T*n - n*fa*T -> if n*fa<T: a > (T*n - n*fa*T)/(n*fa-T) [neg denom -> always]
        lhs_c = n * fa
        aC = (T * n - lhs_c * T) / (lhs_c - T)
        print(f"\n{label}:")
        print(f"  B (per-spike bit access) beats A only if alpha < {aB:.2f}  "
              f"-> {'IMPOSSIBLE (alpha<0 means never)' if aB < 0 else 'needs near-zero per-access overhead'}")
        print(f"  C (neuron-major+skip)   : denominator {lhs_c - T:+.1f} (negative) -> beats A for ALL alpha > {aC:.2f}")
        print(f"     i.e. C wins whenever alpha > {max(aC, 0):.1f}; at alpha=20 -> "
              f"{(lhs_c * (20 + T)) / (T * (20 + n)):.3f}x of A")
