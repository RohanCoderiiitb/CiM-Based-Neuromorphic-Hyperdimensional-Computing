"""Data-derived WORST-CASE bounds and bit-width helpers (sizing from measurement is in measure.py)."""
import numpy as np


def bits_unsigned(max_val: int) -> int:
    return max(1, int(max_val).bit_length())


def bits_signed(lo: int, hi: int) -> int:
    """Smallest two's-complement width holding every integer in [lo, hi]."""
    b = 1
    while not (-(1 << (b - 1)) <= lo and hi <= (1 << (b - 1)) - 1):
        b += 1
    return b


def chunk_max(n_events: np.ndarray, T: int = 100) -> np.ndarray:
    """Equal-event-count binning (bin = k*T//n) gives bins of size floor(n/T) or ceil(n/T)."""
    n = np.asarray(n_events, dtype=np.int64)
    return (n + T - 1) // T


def worst_case(W: np.ndarray, thresh_int: np.ndarray, n_events: np.ndarray, T: int = 100) -> dict:
    """Bounds valid for ANY input with the given per-sample event totals."""
    c_max = int(chunk_max(n_events, T).max())               # one address could receive every event of a bin
    Wi = W.astype(np.int64)
    pos = int(Wi.max())
    neg = int(Wi.min())
    x_hi, x_lo = c_max * max(pos, 0), c_max * min(neg, 0)
    v_hi = int(np.max(thresh_int)) - 1 + x_hi               # V<thresh held in the register, then + X
    v_lo = x_lo * T                                         # at most T consecutive non-firing steps
    return dict(c_max=c_max, x_lo=x_lo, x_hi=x_hi, vp_lo=v_lo, vp_hi=v_hi,
                w_count=bits_unsigned(c_max), w_x=bits_signed(x_lo, x_hi), w_v=bits_signed(v_lo, v_hi))
