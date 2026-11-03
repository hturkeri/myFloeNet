"""Generalised 1D compressible pipe: friction, heat transfer, area change and
rotation (radial pumping), integrated along the length.

Governing equations per unit length (rotating frame, see docs/THEORY.md):

    dp/p - dT/T + dV/V = -dA/A
    dp + rho V dV      = -f rho V^2/(2D) dx + rho Omega^2 r dr
    cp dT + V dV       =  dq + Omega^2 r dr

which give  dV = V/(1-M^2) [ -dA/A - S2/p + S3/(cp T) ]  with
S2 = -f rho V^2/(2D) dx + rho Omega^2 r dr,  S3 = dq + Omega^2 r dr
(cf. Shapiro's influence coefficients; NACA TN 3150).
"""
from __future__ import annotations

import math

from ..compressible import LIN_EPS, flow_function_choked, mach_from_flow_function, pt_over_ps
from ..correlations import friction_factor_darcy, nusselt_pipe
from ..numerics import brentq
from ..params import ParamSpec
from .base import COMMON_FLOW, COMMON_ROT, TwoPortMass, register

_CHOKE_M = 0.995


@register
class Pipe(TwoPortMass):
    type_name = "pipe"
    label = "Pipe / Channel"
    symbol = "pipe"
    description = ("Compressible 1D pipe marching solution with Colebrook friction, Gnielinski heat "
                   "transfer, linear diameter change and rotation (radial pumping, rothalpy).")
    PARAMS = [
        ParamSpec("n_pipes", "Number of pipes", 1, kind="int", minimum=1, group="Geometry"),
        ParamSpec("length", "Length", 0.1, unit="length", minimum=1e-6, group="Geometry"),
        ParamSpec("diameter", "Diameter (port a)", 10e-3, unit="length", minimum=1e-6, group="Geometry",
                  tip="Hydraulic diameter at port a."),
        ParamSpec("diameter_b", "Diameter (port b, 0 = same)", 0.0, unit="length", minimum=0.0, group="Geometry"),
        ParamSpec("roughness", "Sand-grain roughness", 0.0, unit="small_length", minimum=0.0, group="Geometry"),
        ParamSpec("K_in", "Inlet loss K", 0.5, minimum=0.0, group="Loss",
                  tip="Sharp inlet ~0.5, rounded ~0.05. Exit dynamic head is always dumped."),
        ParamSpec("f_mult", "Friction multiplier", 1.0, minimum=0.0, group="Loss"),
        ParamSpec("heat_mode", "Wall heat transfer", "adiabatic", kind="choice",
                  choices=(("adiabatic", "Adiabatic"), ("wall_T", "Fixed wall temperature")), group="Heat transfer"),
        ParamSpec("T_wall", "Wall temperature", 600.0, unit="temperature", group="Heat transfer",
                  visible_if=("heat_mode", "wall_T")),
        ParamSpec("htc_mult", "HTC multiplier", 1.0, minimum=0.0, group="Heat transfer",
                  visible_if=("heat_mode", "wall_T")),
        ParamSpec("n_seg", "Number of segments", 12, kind="int", minimum=2, group="Numerics"),
    ] + COMMON_ROT + COMMON_FLOW

    def __init__(self, params=None):
        super().__init__(params)
        self._cache = {}

    # ------------------------------------------------------------------
    def _geom(self, reverse):
        L = self.p["length"]
        Da = self.p["diameter"]
        Db = self.p["diameter_b"] if self.p["diameter_b"] > 0 else Da
        return (L, Db, Da) if reverse else (L, Da, Db)

    def _march(self, ctx, m1, pt_in, Tt_in, D1, D2, L, r1, r2, omega, profile=False):
        """March one pipe with mass flow m1. Returns (p_exit, T_exit, V_exit, M_exit, ok, prof)."""
        gas = ctx.gas
        R = gas.R
        A1 = math.pi * D1 * D1 / 4.0
        g = gas.gamma(Tt_in)
        Kin = self.p["K_in"]
        base = A1 / math.sqrt(R * Tt_in)
        ffc = flow_function_choked(g)
        ff1 = m1 / (base * pt_in)
        if ff1 >= ffc:
            return None
        M = mach_from_flow_function(ff1, g)
        ps1 = pt_in / pt_over_ps(M, g)
        if Kin > 0.0:
            pt_a = pt_in - Kin * (pt_in - ps1)
            if pt_a <= 0.0:
                return None
            ff = m1 / (base * pt_a)
            if ff >= ffc:
                return None
            M = mach_from_flow_function(ff, g)
            ps1 = pt_a / pt_over_ps(M, g)
        T = Tt_in / (1.0 + 0.5 * (g - 1.0) * M * M)
        p = ps1
        V = M * math.sqrt(g * R * T)
        n = max(int(self.p["n_seg"]), 2)
        dx = L / n
        dD = (D2 - D1) / L
        dr = (r2 - r1) / L
        fm = self.p["f_mult"]
        rough = self.p["roughness"]
        heat = self.p["heat_mode"] == "wall_T"
        Tw = self.p["T_wall"]
        hm = self.p["htc_mult"]
        om2 = omega * omega
        prof = {"x": [0.0], "p": [p], "T": [T], "M": [M]} if profile else None

        def rhs(x, p_, T_, V_):
            D = D1 + dD * x
            A = math.pi * D * D / 4.0
            dAdx = math.pi * D * dD / 2.0
            r = r1 + dr * x
            rho = p_ / (R * T_)
            mu = gas.mu(T_)
            Re = rho * abs(V_) * D / mu
            f = fm * friction_factor_darcy(Re, rough / D)
            cp = gas.cp(T_)
            gam = cp / (cp - R)
            M2 = V_ * V_ / (gam * R * T_)
            q = 0.0
            if heat and m1 > 0:
                Pr = cp * mu / gas.k(T_)
                Nu = nusselt_pipe(Re, Pr)
                h = hm * Nu * gas.k(T_) / D
                Taw = T_ + V_ * V_ / (2.0 * cp)
                q = h * math.pi * D * (Tw - Taw) / m1
            cent = om2 * r * dr
            S2 = -f * rho * V_ * V_ / (2.0 * D) + rho * cent
            S3 = q + cent
            dV = V_ / (1.0 - M2) * (-dAdx / A - S2 / p_ + S3 / (cp * T_))
            dp = S2 - rho * V_ * dV
            dT = (S3 - V_ * dV) / cp
            return dp, dT, dV, M2

        x = 0.0
        for _ in range(n):
            # RK2 (Heun) step
            k1 = rhs(x, p, T, V)
            if k1[3] >= _CHOKE_M ** 2:
                return None
            p2, T2, V2 = p + dx * k1[0], T + dx * k1[1], V + dx * k1[2]
            if p2 <= 0 or T2 <= 0:
                return None
            k2 = rhs(x + dx, p2, T2, V2)
            p += 0.5 * dx * (k1[0] + k2[0])
            T += 0.5 * dx * (k1[1] + k2[1])
            V += 0.5 * dx * (k1[2] + k2[2])
            x += dx
            if p <= 0 or T <= 0:
                return None
            gam = gas.gamma(T)
            Mx = V / math.sqrt(gam * R * T)
            if Mx >= _CHOKE_M:
                return None
            if profile:
                prof["x"].append(x)
                prof["p"].append(p)
                prof["T"].append(T)
                prof["M"].append(Mx)
        cp = gas.cp(T)
        return p, T, V, V / math.sqrt(gas.gamma(T) * R * T), T + V * V / (2.0 * cp), prof

    def forward(self, ctx, inl, pt_eff, Tt_eff, dn, r_in, r_out, reverse):
        L, D1, D2 = self._geom(reverse)
        om = ctx.omega(self.p["rotor"])
        npipe = max(self.p["n_pipes"], 1)
        pt_in, Tt_in = inl.pt, inl.Tt_rel
        A1 = math.pi * D1 * D1 / 4.0
        g = inl.gamma
        m_hi = A1 * pt_in * flow_function_choked(g) / math.sqrt(inl.R * Tt_in) * (1.0 - 1e-9)

        res0 = self._march(ctx, 1e-14 * m_hi, pt_in, Tt_in, D1, D2, L, r_in, r_out, om)
        p0 = res0[0] if res0 else pt_eff
        pdn = dn.p
        if p0 <= pdn:
            return 0.0, {"v_jet": 0.0, "outputs": {"Mach exit": 0.0}}
        lin = (p0 - pdn) / p0 < LIN_EPS
        p_target = p0 * (1.0 - LIN_EPS) if lin else pdn

        def g_of_m(m):
            r = self._march(ctx, m, pt_in, Tt_in, D1, D2, L, r_in, r_out, om)
            if r is None:
                return -p_target
            return r[0] - p_target

        key = (reverse,)
        m_guess = self._cache.get(key)
        m1 = None
        if m_guess is not None and 0 < m_guess < m_hi:
            # secant iterations from the previous solution
            a, fa = m_guess, g_of_m(m_guess)
            b = a * (1.0 - 1e-4) if fa < 0 else a * (1.0 + 1e-4)
            b = min(b, m_hi)
            fb = g_of_m(b)
            for _ in range(8):
                if fb == fa or fb <= -p_target or fa <= -p_target:
                    break
                c = b - fb * (b - a) / (fb - fa)
                if not (0.0 < c < m_hi):
                    break
                a, fa = b, fb
                b, fb = c, g_of_m(c)
                if abs(fb) < 1e-11 * p_target and fb > -p_target:
                    m1 = b
                    break
        if m1 is None:
            m1 = brentq(g_of_m, 0.0, m_hi, fa=p0 - p_target, xtol=1e-18, rtol=1e-12)
        self._cache[key] = m1
        r = self._march(ctx, m1, pt_in, Tt_in, D1, D2, L, r_in, r_out, om)
        if r is None:
            # root sits on the choking boundary: step back to the last feasible state
            mm = m1
            for _ in range(80):
                mm *= (1 - 1e-7)
                r = self._march(ctx, mm, pt_in, Tt_in, D1, D2, L, r_in, r_out, om)
                if r is not None:
                    break
            m1 = mm
        choked = r is None or (r[0] - p_target) > 1e-6 * p_target
        m = m1 * ((p0 - pdn) / (p0 * LIN_EPS) if lin else 1.0)
        if r is None:
            return m * npipe, {"v_jet": 0.0, "choked": True, "outputs": {"choked": True}}
        p_e, T_e, V_e, M_e, Tt_e, _ = r
        rho = p_e / (inl.R * T_e)
        Re = rho * V_e * D2 / ctx.gas.mu(T_e)
        return m * npipe, {"v_jet": V_e, "choked": choked, "Tt_rel_exit": Tt_e,
                           "outputs": {"Mach exit": M_e, "Re exit": Re, "p exit": p_e,
                                       "Tt_rel exit": Tt_e, "choked": choked}}

    def profile(self, ctx, sa, sb, res):
        """Return axial distribution for plotting (forward direction of res)."""
        reverse = res.mdot < 0
        up = sb if reverse else sa
        r_in, r_out = self.radii(reverse)
        om, inl, pt_eff, Tt_eff = self._drive(ctx, up, r_in, r_out, reverse=reverse)
        L, D1, D2 = self._geom(reverse)
        m1 = abs(res.mdot) / max(self.p["n_pipes"], 1)
        r = self._march(ctx, m1, inl.pt, inl.Tt_rel, D1, D2, L, r_in, r_out, om, profile=True)
        return r[5] if r else None
