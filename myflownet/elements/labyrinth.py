"""Labyrinth (knife-edge) seal: tooth-by-tooth march or Martin-Egli bulk model."""
from __future__ import annotations

import math

from ..compressible import LIN_EPS, critical_pr, flow_function_pr
from ..correlations import (carryover_hodkinson, carryover_vermes, cd_chaplygin,
                            martin_flow_function)
from ..numerics import brentq
from ..params import ParamSpec
from .base import COMMON_FLOW, COMMON_ROT, TwoPortMass, register


@register
class Labyrinth(TwoPortMass):
    type_name = "labyrinth"
    label = "Labyrinth Seal"
    symbol = "labyrinth"
    description = ("Straight-through labyrinth seal. Tooth-by-tooth model (St-Venant or Neumann tooth "
                   "equation, Chaplygin or constant Cd, Vermes/Hodkinson carry-over) with choking of the "
                   "last tooth, or the classical Martin-Egli bulk formula.")
    PARAMS = [
        ParamSpec("n_teeth", "Number of teeth", 4, kind="int", minimum=1, group="Geometry"),
        ParamSpec("radius", "Tooth tip radius", 0.15, unit="length", minimum=1e-6, group="Geometry"),
        ParamSpec("clearance", "Radial clearance", 0.3e-3, unit="length", minimum=1e-7, group="Geometry"),
        ParamSpec("pitch", "Tooth pitch s", 4e-3, unit="length", minimum=1e-6, group="Geometry"),
        ParamSpec("tip_width", "Tooth tip width w", 0.3e-3, unit="length", minimum=0.0, group="Geometry"),
        ParamSpec("model", "Model", "tbt", kind="choice",
                  choices=(("tbt", "Tooth-by-tooth"), ("martin_egli", "Martin-Egli (bulk)")), group="Model"),
        ParamSpec("tooth_eq", "Tooth equation", "st_venant", kind="choice",
                  choices=(("st_venant", "St-Venant (isentropic)"), ("neumann", "Neumann (p² form)")),
                  group="Model", visible_if=("model", "tbt")),
        ParamSpec("cd_model", "Tooth Cd", "chaplygin", kind="choice",
                  choices=(("chaplygin", "Chaplygin (pressure-ratio dependent)"), ("constant", "Constant")),
                  group="Model"),
        ParamSpec("cd", "Constant Cd", 0.71, minimum=0.05, maximum=1.0, group="Model",
                  visible_if=("cd_model", "constant")),
        ParamSpec("carryover", "Carry-over factor", "vermes", kind="choice",
                  choices=(("vermes", "Vermes (1961)"), ("hodkinson", "Hodkinson (1939)"), ("none", "None (μ = 1)")),
                  group="Model"),
        ParamSpec("cd_mult", "Flow multiplier", 1.0, minimum=0.0, group="Model",
                  tip="Calibration factor (honeycomb lands, rotation, stepped seals)."),
        ParamSpec("wet_area_factor", "Wetted-area factor", 1.5, minimum=0.0, group="Swirl / windage",
                  tip="Wetted area per side = factor · 2πr · n·s (accounts for tooth flanks and cavity walls)."),
        ParamSpec("dT_max", "Max windage ΔT", 200.0, unit="temperature_diff", minimum=1.0, group="Swirl / windage"),
    ] + COMMON_ROT + COMMON_FLOW

    def port_radii(self):
        ra, rb = self.p["r_a"], self.p["r_b"]
        if ra <= 0.0 and rb <= 0.0:
            return self.p["radius"], self.p["radius"]
        return ra, rb

    def area(self):
        c = self.p["clearance"]
        return 2.0 * math.pi * (self.p["radius"] + 0.5 * c) * c

    def carry(self):
        mode = self.p["carryover"]
        if mode == "vermes":
            return carryover_vermes(self.p["pitch"], self.p["tip_width"], self.p["clearance"])
        if mode == "hodkinson":
            return carryover_hodkinson(self.p["n_teeth"], self.p["pitch"], self.p["clearance"])
        return 1.0

    # ------------------------------------------------------------------
    def _tooth_pr(self, X, p_up, g, mu_c):
        """Solve one tooth for p_dn/p_up given X = mdot sqrt(RT)/(A p_up).
        Returns (pr, choked_flag) or None if the flow exceeds the choked capacity."""
        mult = self.p["cd_mult"]
        prc = critical_pr(g)
        neumann = self.p["tooth_eq"] == "neumann" and self.p["model"] == "tbt"

        def psi(pr):
            if neumann:
                return math.sqrt(max(1.0 - pr * pr, 0.0))
            return flow_function_pr(pr, g)

        def cdv(pr):
            if self.p["cd_model"] == "constant":
                return self.p["cd"]
            return cd_chaplygin(1.0, pr, g)

        def cap(pr):
            return mult * mu_c * cdv(pr) * psi(pr)

        cmax = cap(prc)
        if X > cmax * (1.0 + 1e-12):
            return None
        if X >= cmax:
            return prc, True
        if X <= 0.0:
            return 1.0, False
        pr = brentq(lambda q: cap(q) - X, prc, 1.0, fa=cmax - X, fb=-X, xtol=1e-15, rtol=1e-13)
        return pr, False

    def _march(self, m, p0, T, R, g, mu_c, record=False):
        A = self.area()
        n = self.p["n_teeth"]
        p = p0
        hist = [p0]
        choked = False
        for i in range(n):
            X = m * math.sqrt(R * T) / (A * p)
            r = self._tooth_pr(X, p, g, 1.0 if i == 0 else mu_c)
            if r is None:
                return None
            pr, ch = r
            if ch and i < n - 1:
                return None   # an upstream tooth cannot choke in a straight seal march
            choked = ch
            p *= pr
            hist.append(p)
        return p, choked, hist

    def forward(self, ctx, inl, pt_eff, Tt_eff, dn, r_in, r_out, reverse):
        g, R = inl.gamma, inl.R
        T = Tt_eff
        p0 = pt_eff
        pdn = dn.p
        A = self.area()
        mu_c = self.carry()
        out = {"Area": A, "carry-over μ": mu_c}
        if p0 <= pdn:
            return 0.0, {"v_jet": 0.0, "outputs": out}
        lin = (1.0 - pdn / p0) < LIN_EPS
        p_target = p0 * (1.0 - LIN_EPS) if lin else pdn
        if self.p["model"] == "martin_egli":
            cd = (self.p["cd"] if self.p["cd_model"] == "constant"
                  else cd_chaplygin(1.0, (p_target / p0) ** (1.0 / self.p["n_teeth"]), g))
            m = (self.p["cd_mult"] * cd * mu_c * A * p0 / math.sqrt(R * T)
                 * martin_flow_function(p_target / p0, self.p["n_teeth"]))
            choked = False
            hist = None
        else:
            prc = critical_pr(g)
            cdmax = self.p["cd"] if self.p["cd_model"] == "constant" else cd_chaplygin(1.0, prc, g)
            m_hi = self.p["cd_mult"] * cdmax * A * p0 / math.sqrt(R * T) * flow_function_pr(prc, g) * 1.000001

            def f(m):
                r = self._march(m, p0, T, R, g, mu_c)
                if r is None:
                    return -p_target
                return r[0] - p_target

            m = brentq(f, 0.0, m_hi, fa=p0 - p_target, xtol=1e-18, rtol=1e-12)
            r = self._march(m, p0, T, R, g, mu_c)
            if r is None:
                mm = m
                for _ in range(80):
                    mm *= (1 - 1e-7)
                    r = self._march(mm, p0, T, R, g, mu_c)
                    if r is not None:
                        break
                m = mm
            choked = bool(r and (r[1] or r[0] - p_target > 1e-6 * p_target))
            hist = r[2] if r else None
        if lin:
            m *= (1.0 - pdn / p0) / LIN_EPS
        # jet velocity at the last tooth (for reporting)
        rho = pdn / (R * T)
        v = m / (rho * A) if rho > 0 else 0.0
        out.update({"choked": choked, "PR overall": p0 / pdn,
                    "Flow param m√T/(A·p)": m * math.sqrt(T) / (A * p0) if p0 > 0 else 0.0})
        info = {"v_jet": v, "choked": choked, "outputs": out}
        if hist:
            info["tooth_p"] = hist
        return m, info

    def _exit_state(self, ctx, res, info, inl, Tt_eff, up, dn, r_in, r_out, om, m):
        """Swirl development and windage from rotor/stator wall friction:
        m r (V2 - V1) = r A (tau_rotor - tau_stator),  W = Omega r A tau_rotor."""
        if "tooth_p" in info:
            res.profile = {"tooth": list(range(len(info["tooth_p"]))), "p": info["tooth_p"]}
        if self.p["swirl_out"] != "auto":
            return super()._exit_state(ctx, res, info, inl, Tt_eff, up, dn, r_in, r_out, om, m)
        gas = ctx.gas
        cp = inl.cp
        r = r_out
        V1 = inl.vtheta * (r_in / r_out if r_out > 0 else 1.0)
        U = om * r
        L = self.p["n_teeth"] * self.p["pitch"]
        A = self.p["wet_area_factor"] * 2.0 * math.pi * r * L
        Ts = max(up.Tt - V1 * V1 / (2 * cp), 0.3 * up.Tt)
        rho = 0.5 * (up.p + dn.p) / (gas.R * Ts)
        mu = gas.mu(Ts)
        dh = 2.0 * self.p["clearance"]

        def tau(v):
            Re = rho * abs(v) * dh / mu
            cf = max(0.079 * max(Re, 1.0) ** -0.25, 16.0 / max(Re, 1.0)) if Re > 0 else 0.0
            return 0.5 * rho * cf * v * abs(v)

        def gfun(V2):
            return m * (V2 - V1) - A * (tau(U - V2) - tau(V2))

        vmax = 2.0 * max(abs(U), abs(V1), 1.0)
        lo, hi = -vmax, vmax
        glo, ghi = gfun(lo), gfun(hi)
        k = 0
        while (glo > 0) == (ghi > 0) and k < 30:
            lo, hi = 2 * lo, 2 * hi
            glo, ghi = gfun(lo), gfun(hi)
            k += 1
        V2 = brentq(gfun, lo, hi, fa=glo, fb=ghi, xtol=1e-10, rtol=1e-12) if (glo > 0) != (ghi > 0) else V1
        W = om * r * A * tau(U - V2)
        dTmax = self.p["dT_max"]
        den = m * cp + abs(W) / dTmax
        dTt = W / den if den > 0 else 0.0
        heat = self.p["heat_W"]
        res.Tt_out = up.Tt + dTt + (heat / (m * cp) if m > 1e-12 else 0.0)
        res.rvt_out = r * V2
        res.outputs["Vθ_exit"] = V2
        res.outputs["Windage power"] = W
        res.outputs["ΔTt windage"] = dTt
