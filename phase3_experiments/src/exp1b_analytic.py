"""
Sub-experiment 1b (analytic, no training): storage / array-shape /
utilization / row-activation / per-timestep-traffic comparison between the
baseline (unstructured Wc) and the rank-R factorized class hypervector, for
each R the training sweep covers.

Uses the measured k_t mean (7.51, from
../phase1_firing_characterization/firing_rate_summary.json,
dvsgesture_frozen.k_t_distribution.mean) for the "rows activated per access"
row, per the task's explicit instruction not to assume a number.

States explicitly, per the task, whether the factorized version reduces
per-timestep memory TRAFFIC or only STORAGE -- computed, not assumed.
"""
import json
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P1_DATA = os.path.join(os.path.dirname(ROOT), "phase1_firing_characterization", "firing_rate_summary.json")
ART = os.path.join(ROOT, "artifacts")

n, T, N = 20, 100, 10
MACRO = 128

S = json.load(open(P1_DATA))
k_t_mean = S["dvsgesture_frozen"]["k_t_distribution"]["mean"]  # measured, 7.509...


def macros_and_util(rows, cols, macro=MACRO):
    mr = int(np.ceil(rows / macro)); mc = int(np.ceil(cols / macro))
    util = rows * cols / (mr * macro * mc * macro)
    return mr, mc, util


def main():
    rows_out = []

    # --- baseline ---
    base_bits = n * T * N
    base_rows, base_cols = n * T, N
    mr, mc, util = macros_and_util(base_rows, base_cols)
    base_rows_active = k_t_mean  # measured: active neurons per timestep, out of n*T addressable rows this access
    base_bits_per_timestep = N * n  # eq. (21): N classes x n-bit slice read every timestep
    rows_out.append(dict(
        config="baseline (unstructured Wc)", R=None,
        class_hv_storage_bits=base_bits,
        query_array_rows=base_rows, query_array_cols=base_cols,
        macros_r=mr, macros_c=mc, n_macros=mr * mc, macro_utilization_pct=100 * util,
        rows_activated_per_access=base_rows_active,
        rows_activated_pct=100 * base_rows_active / base_rows,
        per_timestep_bits_read=base_bits_per_timestep,
    ))

    # --- factorized, per R ---
    for R in [1, 2, 4, 8, 16]:
        fac_bits = R * (n + T) * N
        fac_rows, fac_cols = n, N * R  # stationary spike-gated array
        mr, mc, util = macros_and_util(fac_rows, fac_cols)
        fac_rows_active = k_t_mean  # same measured quantity: active neurons per timestep, out of n rows this time
        # Per-timestep traffic has TWO distinct components, per the task's formula
        # (N*R bits for the b-table, PLUS the array access) -- kept separate below,
        # not silently added into one number, because they are physically different
        # kinds of access: (a) an explicit SRAM read of that timestep's B-coefficient
        # row (N*R bits, genuinely a memory read, changes every timestep since b_i^r(t)
        # depends on t); (b) the crossbar's N*R partial-sum OUTPUTS that must be read
        # out of the (stationary, spike-gated) array this timestep -- not a classical
        # "SRAM bit read" (the array itself is resident, not re-read from memory), but
        # the natural per-timestep "how much has to move" quantity for that array.
        b_table_bits = N * R
        array_output_values = N * R
        fac_bits_per_timestep = b_table_bits + array_output_values  # matches the task's literal formula
        rows_out.append(dict(
            config=f"factorized R={R}", R=R,
            class_hv_storage_bits=fac_bits,
            query_array_rows=fac_rows, query_array_cols=fac_cols,
            macros_r=mr, macros_c=mc, n_macros=mr * mc, macro_utilization_pct=100 * util,
            rows_activated_per_access=fac_rows_active,
            rows_activated_pct=100 * fac_rows_active / fac_rows,
            per_timestep_bits_read=fac_bits_per_timestep,
            b_table_bits_per_timestep=b_table_bits,
            array_output_values_per_timestep=array_output_values,
        ))

    df = pd.DataFrame(rows_out)
    os.makedirs(f"{ART}/tables", exist_ok=True)
    df.to_csv(f"{ART}/tables/exp1b_analytic.csv", index=False)
    print(df.to_string(index=False))

    print("\n--- storage vs traffic, explicit (crossover at R = n/2 = 10) ---")
    for R in [1, 2, 4, 8, 16]:
        storage_ratio = base_bits / (R * (n + T) * N)
        base_traffic = base_bits_per_timestep
        fac_traffic = 2 * N * R  # b-table (N*R) + array output (N*R)
        traffic_ratio = base_traffic / fac_traffic
        direction = "REDUCES" if fac_traffic < base_traffic else ("INCREASES" if fac_traffic > base_traffic else "unchanged")
        print(f"R={R:2d}: storage {storage_ratio:6.2f}x smaller | "
              f"per-timestep traffic baseline={base_traffic} vs factorized={fac_traffic} "
              f"-> factorized {direction} per-timestep traffic ({traffic_ratio:.2f}x baseline)")

    with open(f"{ART}/tables/exp1b_summary.json", "w") as f:
        json.dump(dict(k_t_mean_used=k_t_mean, rows=rows_out), f, indent=2)
    print(f"\nwrote {ART}/tables/exp1b_analytic.csv and exp1b_summary.json")


if __name__ == "__main__":
    main()
