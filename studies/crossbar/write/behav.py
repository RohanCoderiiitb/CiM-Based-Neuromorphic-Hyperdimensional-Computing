"""1D-i: the BEHAVIOURAL switching device (not the compact model). Every threshold here is a SWEPT parameter; 1D-ii replaces them with the compact model's own dynamics.

A device holds its resistance until |V across it| has exceeded a threshold `vth` continuously for longer than `tmin`; it then moves toward the other state with time
constant `tsw` (pol = +1: toward LRS on positive V(t,b), pol = -1: toward HRS on negative V). The timer resets when |V| drops below threshold before it fires; once it
has fired the switch is LATCHED and completes even though the switched device's own voltage then falls (it is transistor-limited) - "moves toward the other state". Conductance interpolates linearly between the 1A states
(541.82 / 218,586 ohm at the read bias) with the state variable s in [0, 1] (s = 1: LRS). Implemented with B-sources on two 1 F state capacitors (u = timer, s = state)
so that it runs inside the same ngspice deck as the BSIM4 access transistors.
"""
from __future__ import annotations

G_LRS = 1.0 / 541.82        # S [SIM, 1A]
G_HRS = 1.0 / 218586.0      # S [SIM, 1A]
V_SMOOTH = 2e-3             # V   [CHOICE] width of the smooth threshold (tanh)
T_RESET = 1e-9              # s   [CHOICE] timer reset constant once |V| falls below vth


def subckt_lines() -> list[str]:
    return [
        ".subckt bdev t b u s vth=1 tmin=100n tsw=2n pol=1",
        f"Bsp sp 0 V = 0.5*(1+tanh((pol*v(t,b)-vth)/{V_SMOOTH}))",
        "Cu u 0 1",
        f"Bu 0 u I = v(sp)/tmin*(1-v(q)) - (1-v(sp))*(1-v(q))*v(u)/{T_RESET}",
        "Bf f 0 V = 0.5*(1+tanh((v(u)-1)/0.01))",
        "Cq q 0 1",
        "Bq 0 q I = v(f)*(1-v(q))/1e-10",
        "Cs s 0 1",
        "Bs 0 s I = v(q)*(pol>0 ? (1-v(s)) : -v(s))/tsw",
        f"Bd t b I = v(t,b)*({G_HRS:.12g} + ({G_LRS - G_HRS:.12g})*min(max(v(s),0),1))",
        "Rsp sp 0 1e9", "Rf f 0 1e9", "Rq q 0 1e12",
        ".ends bdev",
    ]
