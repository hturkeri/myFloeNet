"""Engineering correlations used by the element library.

Every function documents its source.  See docs/THEORY.md for the full list of
references.
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Pipe friction and heat transfer
# ---------------------------------------------------------------------------

def friction_factor_darcy(Re: float, rel_rough: float = 0.0) -> float:
    """Darcy friction factor.

    * laminar  (Re < 2300): f = 64/Re
    * turbulent (Re > 4000): Colebrook-White (1939), solved iteratively,
      started from Haaland (1983)
    * 2300..4000: linear blend
    """
    Re = max(Re, 1.0)
    if Re < 2300.0:
        return 64.0 / Re

    def turb(Re_):
        # Haaland initial guess
        a = -1.8 * math.log10((rel_rough / 3.7) ** 1.11 + 6.9 / Re_)
        x = a  # x = 1/sqrt(f)
        for _ in range(30):
            rhs = -2.0 * math.log10(rel_rough / 3.7 + 2.51 * x / Re_)
            if abs(rhs - x) < 1e-12:
                x = rhs
                break
            x = rhs
        return 1.0 / (x * x)

    if Re > 4000.0:
        return turb(Re)
    w = (Re - 2300.0) / 1700.0
    return (1.0 - w) * 64.0 / 2300.0 + w * turb(4000.0)


def nusselt_pipe(Re: float, Pr: float, f_darcy: float | None = None) -> float:
    """Fully developed pipe Nusselt number.

    * laminar: 3.66 (uniform wall temperature)
    * turbulent: Gnielinski (1976), 3000 < Re < 5e6
    * blend in 2300..3000
    """
    Re = max(Re, 1.0)
    if Re < 2300.0:
        return 3.66

    def gn(Re_):
        f = friction_factor_darcy(Re_) if f_darcy is None else f_darcy
        return (f / 8.0) * (Re_ - 1000.0) * Pr / (1.0 + 12.7 * math.sqrt(f / 8.0) * (Pr ** (2.0 / 3.0) - 1.0))

    if Re >= 3000.0:
        return gn(Re)
    w = (Re - 2300.0) / 700.0
    return (1.0 - w) * 3.66 + w * gn(3000.0)


# ---------------------------------------------------------------------------
# Orifice discharge coefficient corrections
# ---------------------------------------------------------------------------

def cd_corner_radius(cd0: float, r_over_d: float) -> float:
    """McGreehan & Schotsch (1988) inlet corner-radius correction.

    Cd_r = 1 - f (1 - Cd0),  f = 0.008 + 0.992 exp(-5.5 r/d - 3.5 (r/d)^2)
    """
    if r_over_d <= 0.0:
        return cd0
    f = 0.008 + 0.992 * math.exp(-5.5 * r_over_d - 3.5 * r_over_d ** 2)
    return 1.0 - f * (1.0 - cd0)


def cd_length(cd: float, l_over_d: float) -> float:
    """McGreehan & Schotsch (1988) length-to-diameter correction.

    Cd_L = 1 - g (1 - Cd),  g = [1 + 1.3 exp(-1.606 (L/d)^2)] (0.435 + 0.021 L/d)
    (reattachment for L/d > ~0.5 raises Cd of a sharp-edged hole).
    """
    if l_over_d <= 0.0:
        return cd
    g = (1.0 + 1.3 * math.exp(-1.606 * l_over_d ** 2)) * (0.435 + 0.021 * l_over_d)
    return 1.0 - g * (1.0 - cd)


# ---------------------------------------------------------------------------
# Labyrinth seals
# ---------------------------------------------------------------------------

def carryover_vermes(pitch: float, tip_width: float, clearance: float) -> float:
    """Vermes (1961) kinetic-energy carry-over factor
    mu = 1/sqrt(1-alpha), alpha = 8.52 / ((s - w)/c + 7.23)."""
    alpha = 8.52 / ((pitch - tip_width) / max(clearance, 1e-12) + 7.23)
    alpha = min(alpha, 0.99)
    return 1.0 / math.sqrt(1.0 - alpha)


def carryover_hodkinson(n_teeth: int, pitch: float, clearance: float) -> float:
    """Hodkinson (1939) carry-over factor (as used by Egli-type models)
    gamma = 1/sqrt(1 - ((n-1)/n) * (c/s)/((c/s)+0.02))."""
    n = max(n_teeth, 1)
    cs = clearance / max(pitch, 1e-12)
    val = 1.0 - ((n - 1.0) / n) * cs / (cs + 0.02)
    return 1.0 / math.sqrt(max(val, 1e-6))


def cd_chaplygin(p_up: float, p_dn: float, g: float) -> float:
    """Chaplygin flow coefficient for a sharp tooth (used in Scharrer/
    Neumann-type tooth-by-tooth models, cf. Micio et al. GT2011-46402):
    Cd = pi / (pi + 2 - 5 phi + 2 phi^2), phi = (p_up/p_dn)^((g-1)/g) - 1."""
    phi = (max(p_up / max(p_dn, 1.0), 1.0)) ** ((g - 1.0) / g) - 1.0
    return math.pi / (math.pi + 2.0 - 5.0 * phi + 2.0 * phi * phi)


def martin_flow_function(pr_overall: float, n_teeth: int) -> float:
    """Martin (1908) / Egli (1935) labyrinth flow function
    phi = sqrt((1 - pr^2) / (n - ln pr)), pr = p_n/p_0."""
    pr = min(max(pr_overall, 1e-6), 1.0)
    return math.sqrt(max(1.0 - pr * pr, 0.0) / (n_teeth - math.log(pr)))


# ---------------------------------------------------------------------------
# Rotating discs
# ---------------------------------------------------------------------------

CF_LAM_FREE_DISC = 1.232   # tau = 1/2 rho cf V^2, cf = a Re_r^-0.5 (von Karman laminar)
CF_TURB_FREE_DISC = 0.0534  # cf = a Re_r^-0.2 -> Cm = 0.0729 Re^-0.2 per side (turbulent)


def disc_local_cf(Re_local: float) -> float:
    """Local skin-friction coefficient for a rotating-disc boundary layer,
    based on the relative tangential velocity.  Calibrated so that the
    integrated torque reproduces the free-disc moment coefficients
    Cm = 1.935 Re^-0.5 (laminar) and Cm = 0.0729 Re^-0.2 (turbulent), per side
    (von Karman 1921; Owen & Rogers 1989)."""
    Re = max(Re_local, 10.0)
    return max(CF_LAM_FREE_DISC * Re ** -0.5, CF_TURB_FREE_DISC * Re ** -0.2)


def daily_nece_cm(Re: float, G: float) -> tuple[float, int]:
    """Daily & Nece (1960) moment coefficient of an enclosed disc, ONE side,
    Cm = M / (0.5 rho Omega^2 b^5).  Returns (Cm, regime).  The largest of the
    four regime values is taken (common practice when the regime is unknown).

    I   laminar, merged layers:      pi / (G Re)
    II  laminar, separate layers:    1.85 G^0.1 Re^-0.5
    III turbulent, merged layers:    0.040 G^-1/6 Re^-1/4
    IV  turbulent, separate layers:  0.051 G^0.1 Re^-0.2
    """
    Re = max(Re, 1.0)
    G = max(G, 1e-4)
    vals = [
        math.pi / (G * Re),
        1.85 * G ** 0.1 * Re ** -0.5,
        0.040 * G ** (-1.0 / 6.0) * Re ** -0.25,
        0.051 * G ** 0.1 * Re ** -0.2,
    ]
    i = max(range(4), key=lambda k: vals[k])
    return vals[i], i + 1


def free_disc_cm(Re: float) -> float:
    """Free disc moment coefficient, one side (von Karman / Owen & Rogers)."""
    Re = max(Re, 1.0)
    return max(1.935 * Re ** -0.5, 0.0729 * Re ** -0.2)


def disc_pumping_mdot(mu: float, rho: float, r: float, omega: float, swirl: float,
                      model: str = "sultanian") -> float:
    """Disc pumping (entrainment) mass flow of one disc face up to radius r
    for a core rotating at swirl ratio Sf relative to the disc.

    sultanian:   m = 0.219 mu r Re^0.8 (1 - 0.51 Sf)(1 - Sf)^1.6
    owen_rogers: m = 0.1395 mu r Re^0.8 |1 - Sf|^1.6
    (forms as documented in the Altair Flow Simulator manual; Re = rho r^2 Omega/mu)
    """
    Re = rho * r * r * abs(omega) / max(mu, 1e-12)
    sf = min(max(swirl, 0.0), 1.0)
    if model == "owen_rogers":
        return 0.1395 * mu * r * Re ** 0.8 * abs(1.0 - sf) ** 1.6
    return 0.219 * mu * r * Re ** 0.8 * (1.0 - 0.51 * sf) * (1.0 - sf) ** 1.6
