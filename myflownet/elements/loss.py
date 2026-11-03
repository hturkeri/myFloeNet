"""Loss-coefficient (K) restriction: bends, valves, sudden contractions, generic
handbook losses (Idelchik, Miller)."""
from __future__ import annotations

import math

from ..compressible import (LIN_EPS, flow_function_mach, mach_from_flow_function, pt_over_ps,
                            flow_function_choked, jet_velocity)
from ..numerics import brentq, bisect_feasible
from ..params import ParamSpec
from .base import COMMON_FLOW, COMMON_ROT, TwoPortMass, register


@register
class KLoss(TwoPortMass):
    type_name = "kloss"
    label = "K-Loss"
    symbol = "kloss"
    description = ("Total-pressure loss K × dynamic head. Default (Miller §7.7, Flow Simulator, Nart Eq. 7): "
                   "pt,in − pt,ex = K·½ρV² of the exit, i.e. K·M² + (2/γ)(PR_ex − pt,in/ps,ex) = 0; "
                   "alternative: K·(pt − ps) at the inlet station. Incompressible limit: Cd = 1/sqrt(1+K). "
                   "A plenum downstream dumps the exit head; a momentum chamber carries it on.")
    PARAMS = [
        ParamSpec("n_paths", "Number of parallel paths", 1, kind="int", minimum=1, group="Geometry"),
        ParamSpec("diameter", "Diameter", 10e-3, unit="length", minimum=0.0, group="Geometry"),
        ParamSpec("area_override", "Total area (override)", 0.0, unit="area", minimum=0.0, group="Geometry"),
        ParamSpec("K", "Loss coefficient K (fwd)", 1.0, minimum=0.0, group="Loss",
                  tip="Based on the dynamic head at the element area (Idelchik / Miller definition)."),
        ParamSpec("K_rev", "Loss coefficient K (rev, <0 = same)", -1.0, group="Loss"),
        ParamSpec("K_def", "Compressible K definition", "exit", kind="choice",
                  choices=(("exit", "Exit ½ρV² (Miller / Flow Simulator)"), ("inlet", "Inlet pt − ps")),
                  group="Loss",
                  tip="exit: pt,in − pt,ex = K·½ρV²_ex, solved as K·M² + (2/γ)(PR_ex − pt,in/ps,ex) = 0 "
                      "(Miller §7.7; Nart, FlowNet Eq. 7).  inlet: Δpt = K·(pt − ps) at the inlet station."),
    ] + COMMON_ROT + COMMON_FLOW

    def area(self):
        if self.p["area_override"] > 0:
            return self.p["area_override"]
        return self.p["n_paths"] * math.pi * self.p["diameter"] ** 2 / 4.0

    def forward(self, ctx, inl, pt_eff, Tt, dn, r_in, r_out, reverse):
        if self.p["K_def"] == "exit":
            return self._forward_exit(ctx, inl, pt_eff, Tt, dn, reverse)
        return self._forward_inlet(ctx, inl, pt_eff, Tt, dn, reverse)

    def _forward_exit(self, ctx, inl, pt1, Tt, dn, reverse):
        """K on the exit dynamic pressure (incompressible form ½ρV² = γ/2·ps·M²):
        pt1 - pt_ex = K·γ/2·ps_ex·M_ex²   ->   K·M² + (2/γ)(PR_ex(M) - pt1/ps_ex) = 0."""
        K = self.p["K_rev"] if (reverse and self.p["K_rev"] >= 0) else self.p["K"]
        A = self.area()
        g, R = inl.gamma, inl.R
        pdn = dn.p
        if pt1 <= pdn or A <= 0:
            return 0.0, {"v_jet": 0.0, "outputs": {"K": K, "Mach exit": 0.0}}
        lin = (1.0 - pdn / pt1) < LIN_EPS
        p_target = pt1 * (1.0 - LIN_EPS) if lin else pdn
        ratio = pt1 / p_target
        f = lambda M: K * M * M + (2.0 / g) * (pt_over_ps(M, g) - ratio)
        if f(1.0) <= 0.0:
            M, choked = 1.0, True
            pt_ex = pt1 / (1.0 + K * g / (2.0 * pt_over_ps(1.0, g)))
        else:
            M = brentq(f, 0.0, 1.0, fa=f(0.0), xtol=1e-15, rtol=1e-14)
            choked = False
            pt_ex = p_target * pt_over_ps(M, g)
        m = A * pt_ex / math.sqrt(R * Tt) * flow_function_mach(M, g)
        if lin:
            scale = (1.0 - pdn / pt1) / LIN_EPS
            m *= scale
            M *= scale          # velocity scales with the flow in the linearised zone
            pt_ex = pt1 - scale * (pt1 - pt_ex)
        Ts = Tt / (1.0 + 0.5 * (g - 1.0) * M * M)
        v = M * math.sqrt(g * R * Ts)
        return m, {"v_jet": v, "choked": choked,
                   "outputs": {"K": K, "Mach exit": M, "Δpt": pt1 - pt_ex, "choked": choked}}

    def _forward_inlet(self, ctx, inl, pt_eff, Tt, dn, reverse):
        K = self.p["K_rev"] if (reverse and self.p["K_rev"] >= 0) else self.p["K"]
        A = self.area()
        g, R = inl.gamma, inl.R
        pt1 = pt_eff
        pdn = dn.p
        if pt1 <= pdn or A <= 0:
            return 0.0, {"v_jet": 0.0, "outputs": {"K": K, "Mach": 0.0}}
        base = A / math.sqrt(R * Tt)
        ffc = flow_function_choked(g)

        def states(m):
            ff1 = m / (base * pt1)
            if ff1 >= ffc:
                return None
            M1 = mach_from_flow_function(ff1, g)
            ps1 = pt1 / pt_over_ps(M1, g)
            pt2 = pt1 - K * (pt1 - ps1)
            if pt2 <= 0:
                return None
            ff2 = m / (base * pt2)
            if ff2 >= ffc:
                return None
            M2 = mach_from_flow_function(ff2, g)
            return M1, M2, pt2 / pt_over_ps(M2, g), pt2

        m_choke_hi = base * pt1 * ffc
        m_max = bisect_feasible(lambda m: states(m) is not None, 0.0, m_choke_hi * (1 - 1e-12), iters=70)
        s_max = states(m_max)
        lin = (1.0 - pdn / pt1) < LIN_EPS
        p_target = pt1 * (1.0 - LIN_EPS) if lin else pdn
        if s_max is not None and s_max[2] >= p_target:
            m, choked = m_max, True
        else:
            f = lambda m: states(m)[2] - p_target
            m = brentq(f, 0.0, m_max, fa=pt1 - p_target, xtol=1e-16, rtol=1e-13)
            choked = False
        if lin:
            m *= (1.0 - pdn / pt1) / LIN_EPS
        st = states(m) if m > 0 else (0.0, 0.0, pt1, pt1)   # evaluated at the actual (scaled) flow
        M2 = st[1] if st else 1.0
        Ts2 = Tt / (1 + 0.5 * (g - 1) * M2 * M2)
        v = M2 * math.sqrt(g * R * Ts2)
        m_ideal = base * pt1 * math.sqrt(max(0.0, 2 * g / (g - 1) * (
            (max(pdn / pt1, (2 / (g + 1)) ** (g / (g - 1)))) ** (2 / g)
            - (max(pdn / pt1, (2 / (g + 1)) ** (g / (g - 1)))) ** ((g + 1) / g))))
        return m, {"v_jet": v, "choked": choked,
                   "outputs": {"K": K, "Mach": M2, "Cd equiv.": m / m_ideal if m_ideal > 0 else 0.0,
                               "Δpt": pt1 - (st[3] if st else pt1), "choked": choked}}
