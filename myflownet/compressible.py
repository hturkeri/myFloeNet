"""Compressible-flow utility functions (calorically perfect within one call).

Notation: pt, Tt total quantities; ps static pressure; g = gamma; R gas constant.
"""
from __future__ import annotations

import math

# Width of the linearised zone used near zero pressure difference.  Inside
# 1 - pr < LIN_EPS the sqrt-type characteristic is replaced by a straight line
# so that dm/dp stays finite (needed by the Newton solver).
LIN_EPS = 2.0e-5


def critical_pr(g: float) -> float:
    """Critical static/total pressure ratio for choking (M=1)."""
    return (2.0 / (g + 1.0)) ** (g / (g - 1.0))


def flow_function_pr(pr: float, g: float) -> float:
    """Psi(pr) such that m = A * pt / sqrt(R*Tt) * Psi, for isentropic
    expansion from (pt,Tt) to static pressure ratio pr = ps/pt (pr >= pr*)."""
    if pr >= 1.0:
        return 0.0
    val = (pr ** (2.0 / g) - pr ** ((g + 1.0) / g)) * 2.0 * g / (g - 1.0)
    return math.sqrt(max(val, 0.0))


def flow_function_choked(g: float) -> float:
    return math.sqrt(g) * (2.0 / (g + 1.0)) ** ((g + 1.0) / (2.0 * (g - 1.0)))


def flow_function_mach(M: float, g: float) -> float:
    """m*sqrt(R*Tt)/(A*pt) as function of Mach number."""
    return math.sqrt(g) * M * (1.0 + 0.5 * (g - 1.0) * M * M) ** (-(g + 1.0) / (2.0 * (g - 1.0)))


def mach_from_flow_function(ff: float, g: float, supersonic: bool = False) -> float:
    """Invert flow_function_mach. Returns 1.0 if ff exceeds the choked value."""
    ffc = flow_function_choked(g)
    if ff >= ffc:
        return 1.0
    if ff <= 0.0:
        return 0.0
    lo, hi = (1.0, 50.0) if supersonic else (0.0, 1.0)
    # Newton with bisection safeguard
    M = 0.5 * ff / ffc if not supersonic else 2.0
    for _ in range(100):
        f = flow_function_mach(M, g) - ff
        if (f > 0) != supersonic:
            hi = M
        else:
            lo = M
        # derivative
        t = 1.0 + 0.5 * (g - 1.0) * M * M
        dfdM = flow_function_mach(M, g) * (1.0 / max(M, 1e-12) - (g + 1.0) * M / (2.0 * t))
        Mn = M - f / dfdM if dfdM != 0 else 0.5 * (lo + hi)
        if not (lo < Mn < hi):
            Mn = 0.5 * (lo + hi)
        if abs(Mn - M) < 1e-13:
            M = Mn
            break
        M = Mn
    return M


def pt_over_ps(M: float, g: float) -> float:
    return (1.0 + 0.5 * (g - 1.0) * M * M) ** (g / (g - 1.0))


def Tt_over_Ts(M: float, g: float) -> float:
    return 1.0 + 0.5 * (g - 1.0) * M * M


def isentropic_mdot(pt: float, Tt: float, ps_back: float, area: float, g: float, R: float,
                    lin_eps: float = LIN_EPS) -> tuple[float, bool]:
    """Ideal (Cd=1) mass flow from total state (pt,Tt) through area to back
    static pressure ps_back.  Returns (mdot >= 0, choked)."""
    if pt <= 0.0 or area <= 0.0 or ps_back >= pt:
        return 0.0, False
    pr = ps_back / pt
    prc = critical_pr(g)
    base = area * pt / math.sqrt(R * Tt)
    if pr <= prc:
        return base * flow_function_pr(prc, g), True
    if 1.0 - pr < lin_eps:
        # linear zone: psi(1-eps) * (1-pr)/eps
        psi = flow_function_pr(1.0 - lin_eps, g)
        return base * psi * (1.0 - pr) / lin_eps, False
    return base * flow_function_pr(pr, g), False


def jet_velocity(Tt: float, pr: float, g: float, cp: float) -> float:
    """Isentropic jet velocity for static/total ratio pr (clipped at critical)."""
    pr = max(pr, critical_pr(g))
    pr = min(pr, 1.0)
    Ts = Tt * pr ** ((g - 1.0) / g)
    return math.sqrt(max(2.0 * cp * (Tt - Ts), 0.0))


def pr_from_psi(psi: float, g: float) -> float:
    """Inverse of flow_function_pr on the subsonic branch [pr*, 1].
    Returns pr; if psi exceeds the choked value returns pr* (caller checks)."""
    prc = critical_pr(g)
    psic = flow_function_pr(prc, g)
    if psi >= psic:
        return prc
    if psi <= 0.0:
        return 1.0
    lo, hi = prc, 1.0
    # use the linearised zone consistently with isentropic_mdot
    psi_eps = flow_function_pr(1.0 - LIN_EPS, g)
    if psi < psi_eps:
        return 1.0 - LIN_EPS * psi / psi_eps
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if flow_function_pr(mid, g) > psi:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return 0.5 * (lo + hi)
