"""Shared cocotb helpers. The golden model is IMPORTED (tb/common/golden.py -> int_model.py / events.py); nothing here re-implements it."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tb.common import golden as G  # noqa: E402,F401

import cocotb  # noqa: E402
from cocotb.clock import Clock  # noqa: E402
from cocotb.triggers import FallingEdge, RisingEdge  # noqa: E402

T = G.T


async def start_clock(dut, period_ns: int = 10):
    cocotb.start_soon(Clock(dut.clk_i, period_ns, unit="ns").start())


async def reset(dut, cycles: int = 3):
    dut.rst_n_i.value = 0
    await ticks(dut, cycles)
    dut.rst_n_i.value = 1
    await ticks(dut, 2)


async def ticks(dut, n: int = 1):
    for _ in range(n):
        await RisingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)      # inputs are driven (and outputs read) in the middle of the cycle, away from the active edge


def to_signed(v: int, width: int) -> int:
    v = int(v) & ((1 << width) - 1)
    return v - (1 << width) if v >> (width - 1) else v


def unpack_signed(vec: int, n: int, width: int) -> list[int]:
    return [to_signed((int(vec) >> (i * width)) & ((1 << width) - 1), width) for i in range(n)]


def weights_to_macro_words(W: np.ndarray) -> np.ndarray:
    """int8 W [20,512] -> uint32 words [5 macros, 512 addresses]; word bit (j%4)*8+k = plane k of neuron 4m + j%4 (the Phase 0 export layout).
    Built from the two's-complement planes, exactly as the sign-bit convention defines them."""
    u = W.astype(np.int64) & 0xFF                      # two's-complement byte of each weight
    words = np.zeros((5, 512), np.uint64)
    for j in range(20):
        for k in range(8):
            words[j // 4] |= (((u[j] >> k) & 1).astype(np.uint64)) << np.uint64((j % 4) * 8 + k)
    return words.astype(np.uint32)


async def write_weights(dut, W: np.ndarray, port: str = "direct"):
    """Load a weight image through the macro write port (mvm_unit) ."""
    words = weights_to_macro_words(W)
    for m in range(5):
        for a in range(512):
            dut.wr_en_i.value = 1
            dut.wr_macro_i.value = m
            dut.wr_addr_i.value = a
            dut.wr_data_i.value = int(words[m, a])
            await ticks(dut)
    dut.wr_en_i.value = 0
    await ticks(dut)


async def write_weights_flat(dut, W):          # kept for API symmetry with write_weights
    await write_weights(dut, W)
