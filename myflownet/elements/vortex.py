"""Pressure-type elements: free/forced vortex and the rotor-stator cavity.

These elements do not have a mass-flow characteristic; they impose the static
pressure ratio p_b/p_a produced by the radial equilibrium of the swirling
flow, dp/dr = rho V_theta^2 / r.  Their mass flow is an additional unknown of
the network (augmented Newton system), as in Altair Flow Simulator's vortex
elements.
"""
from __future__ import annotations

import math

from ..correlations import daily_nece_cm, disc_local_cf, free_disc_cm
from ..numerics import brentq
from ..params import ParamSpec
from .base import Element, ElementResult, register


def _source_vtheta(elem, ctx, up, r_up, src, Kfix, om_e):
    """Absolute tangential velocity at r_up for the chosen swirl source."""
    if src == "fixed":
        return Kfix * om_e * r_up
    return up.vtheta(r_up)


@register
class Vortex(Element):
    type_name = "vortex"
    label = "Vortex (free / forced)"
    category = "pressure"
    symbol = "vortex"
    description = ("Radial pressure change of a free (r·Vθ = const) or forced (Vθ = K·Ω·r) vortex, "
                   "isentropic.  Optional rotor work for forced vortices (Euler equation).")
    PARAMS = [
        ParamSpec("vortex_type", "Vortex type", "forced", kind="choice",
                  choices=(("forced", "Forced (Vθ = KΩr)"), ("free", "Free (r·Vθ = const)")), group="Vortex"),
        ParamSpec("rotor", "Reference rotor", 1, kind="rotor", group="Vortex"),
        ParamSpec("r_a", "Radius at port a", 0.1, unit="length", minimum=0.0, group="Vortex"),
        ParamSpec("r_b", "Radius at port b", 0.2, unit="length", minimum=0.0, group="Vortex"),
        ParamSpec("swirl_source", "Swirl source", "fixed", kind="choice",
                  choices=(("fixed", "Fixed K"), ("upstream", "Upstream chamber")), group="Vortex"),
        ParamSpec("K", "Swirl ratio K", 1.0, group="Vortex", visible_if=("swirl_source", "fixed")),
        ParamSpec("work", "Temperature change", "rotor", kind="choice",
                  choices=(("rotor", "Rotor work (Euler)"), ("none", "None (Tt const)")), group="Vortex",
                  tip="Rotor work: ΔTt = Ω·Δ(r·Vθ)/cp, e.g. co-rotating cavity (K=1) heats on outflow."),
        ParamSpec("heat_W", "Heat added", 0.0, unit="power", group="Vortex"),
    ]

    def port_radii(self):
        return self.p["r_a"], self.p["r_b"]

    def evaluate(self, ctx, sa, sb, mdot=None):
        mdot = 0.0 if mdot is None else mdot
        rev = mdot < 0.0
        up, dn = (sb, sa) if rev else (sa, sb)
        r_up, r_dn = (self.p["r_b"], self.p["r_a"]) if rev else (self.p["r_a"], self.p["r_b"])
        om = ctx.omega(self.p["rotor"])
        gas = ctx.gas
        cp = gas.cp(up.Tt)
        vt_up = _source_vtheta(self, ctx, up, r_up, self.p["swirl_source"], self.p["K"], om)
        Ts_up = max(up.Tt - vt_up * vt_up / (2 * cp), 0.2 * up.Tt)
        if self.p["vortex_type"] == "free":
            C = r_up * vt_up
            vt_dn = C / r_dn if r_dn > 0 else 0.0
            dTs = (C * C / (2 * cp)) * ((1 / r_up ** 2 if r_up > 0 else 0.0) - (1 / r_dn ** 2 if r_dn > 0 else 0.0))
            K_used = vt_up / (om * r_up) if om * r_up != 0 else 0.0
        else:
            K_used = vt_up / (om * r_up) if (om * r_up) != 0 else (self.p["K"] if self.p["swirl_source"] == "fixed" else 0.0)
            w = K_used * om
            vt_dn = w * r_dn
            dTs = w * w * (r_dn ** 2 - r_up ** 2) / (2 * cp)
        collapse = Ts_up + dTs < 0.3 * Ts_up
        Ts_dn = max(Ts_up + dTs, 0.3 * Ts_up)
        g = gas.gamma(0.5 * (Ts_up + Ts_dn))
        ln_pr = (g / (g - 1.0)) * math.log(Ts_dn / Ts_up)   # ln(p_dn / p_up)
        # energy
        dTt = 0.0
        if self.p["work"] == "rotor" and self.p["vortex_type"] == "forced":
            dTt = om * (r_dn * vt_dn - r_up * vt_up) / cp
        m = abs(mdot)
        heat = self.p["heat_W"]
        Tt_out = up.Tt + dTt + (heat / (m * cp) if m > 1e-12 else 0.0)
        res = ElementResult(mdot=mdot, Tt_out=Tt_out, rvt_out=r_dn * vt_dn, r_out=r_dn,
                            log_pr=-ln_pr if rev else ln_pr)
        res.outputs = {"K": K_used, "Vθ in": vt_up, "Vθ out": vt_dn, "p_dn/p_up": math.exp(ln_pr),
                       "ΔTt": dTt}
        if collapse:
            res.outputs["warning"] = "static temperature collapse (vortex would choke) - clipped"
        return res


@register
class RotorStatorCavity(Element):
    type_name = "cavity"
    label = "Rotor-Stator Cavity"
    category = "pressure"
    symbol = "cavity"
    description = ("1D radial march of a rotating-disc cavity: angular-momentum balance with rotor and "
                   "stator (or second rotor) wall shear, radial equilibrium dp/dr = ρVθ²/r and rotor "
                   "windage heating.  Wall friction is calibrated to Daily & Nece (1960) and to the "
                   "closed-cavity core swirl ratio.")
    PARAMS = [
        ParamSpec("rotor", "Rotor (disc)", 1, kind="rotor", group="Geometry"),
        ParamSpec("r_a", "Radius at port a", 0.10, unit="length", minimum=0.0, group="Geometry"),
        ParamSpec("r_b", "Radius at port b", 0.25, unit="length", minimum=0.0, group="Geometry"),
        ParamSpec("gap", "Axial gap s", 5e-3, unit="length", minimum=1e-6, group="Geometry"),
        ParamSpec("second_wall", "Opposite wall", "stator", kind="choice",
                  choices=(("stator", "Stator (rotor-stator)"), ("rotor", "Rotor (co-rotating)")), group="Geometry"),
        ParamSpec("friction_model", "Wall friction", "daily_nece", kind="choice",
                  choices=(("daily_nece", "Daily & Nece"), ("free_disc", "Free disc")),
                  group="Friction"),
        ParamSpec("K0", "Closed-cavity core swirl K₀", 0.426, minimum=0.05, maximum=0.95, group="Friction",
                  tip="Sets the stator/rotor friction ratio so that a cavity without throughflow "
                      "reaches this core swirl ratio (Daily & Nece: ~0.4-0.44; Owen & Rogers: 0.426)."),
        ParamSpec("cf_rotor_mult", "Rotor friction multiplier", 1.0, minimum=0.0, group="Friction"),
        ParamSpec("cf_stator_mult", "Stator friction multiplier", 1.0, minimum=0.0, group="Friction"),
        ParamSpec("swirl_source", "Inlet swirl", "upstream", kind="choice",
                  choices=(("upstream", "Upstream chamber"), ("fixed", "Fixed K")), group="Swirl"),
        ParamSpec("K_in", "Inlet swirl ratio", 0.0, group="Swirl", visible_if=("swirl_source", "fixed")),
        ParamSpec("dT_max", "Max windage ΔT", 300.0, unit="temperature_diff", minimum=1.0, group="Numerics",
                  tip="Windage temperature rise is saturated smoothly towards this value as throughflow → 0."),
        ParamSpec("n_seg", "Radial segments", 20, kind="int", minimum=2, group="Numerics"),
        ParamSpec("heat_W", "Heat added", 0.0, unit="power", group="Numerics"),
    ]

    def port_radii(self):
        return self.p["r_a"], self.p["r_b"]

    def _cal(self, rho, mu, om):
        b = max(self.p["r_a"], self.p["r_b"])
        K0 = self.p["K0"]
        ms = ((1.0 - K0) / K0) ** 1.8 if self.p["second_wall"] == "stator" else 1.0
        if self.p["friction_model"] == "daily_nece" and om != 0:
            Re = rho * abs(om) * b * b / mu
            G = self.p["gap"] / max(b, 1e-9)
            cm_dn, _ = daily_nece_cm(Re, G)
            cm_model = free_disc_cm(Re) * (1.0 - K0) ** 1.8 if self.p["second_wall"] == "stator" else cm_dn
            c = cm_dn / max(cm_model, 1e-12)
        else:
            c = 1.0
        return c, ms

    def march(self, ctx, up, mdot_abs, r_up, r_dn, profile=False):
        gas = ctx.gas
        R = gas.R
        om = ctx.omega(self.p["rotor"])
        n = max(int(self.p["n_seg"]), 2)
        Tt = up.Tt
        cp = gas.cp(Tt)
        if self.p["swirl_source"] == "fixed":
            V = self.p["K_in"] * om * r_up
        else:
            V = up.vtheta(r_up)
        p = 1.0   # march relative pressure (p/p_up)
        Ts = max(Tt - V * V / (2 * cp), 0.2 * Tt)
        rho0 = up.p / (R * Ts)
        mu0 = gas.mu(Ts)
        cal, ms = self._cal(rho0, mu0, om)
        cr = cal * self.p["cf_rotor_mult"]
        cs = cal * ms * self.p["cf_stator_mult"]
        co = self.p["second_wall"] == "rotor"
        dTmax = self.p["dT_max"]
        m = mdot_abs
        rs = [r_up + (r_dn - r_up) * i / n for i in range(n + 1)]
        T_rot_tot = T_st_tot = W_tot = 0.0
        prof = {"r": [r_up], "K": [V / (om * r_up) if om * r_up else 0.0], "p_rel": [1.0], "Tt": [Tt]} if profile else None
        V_in = V
        for i in range(n):
            r1, r2 = rs[i], rs[i + 1]
            rm = 0.5 * (r1 + r2)
            dr = abs(r2 - r1)
            Ts = max(Tt - V * V / (2 * cp), 0.2 * Tt)
            rho = up.p * p / (R * Ts)
            mu = gas.mu(Ts)
            area_fac = 2.0 * math.pi * rm * rm * dr

            def torques(V2):
                Vm = V2 * rm / r2 if r2 > 0 else 0.0
                vr = om * rm - Vm
                Re_r = rho * abs(vr) * rm / mu
                tr = 0.5 * rho * cr * disc_local_cf(Re_r) * vr * abs(vr)
                if co:
                    ts = -tr      # second rotating face acts like the rotor
                else:
                    Re_s = rho * abs(Vm) * rm / mu
                    ts = 0.5 * rho * cs * disc_local_cf(Re_s) * Vm * abs(Vm)
                return area_fac * tr, area_fac * ts

            def gfun(V2):
                tr, ts = torques(V2)
                return m * (r2 * V2 - r1 * V) - (tr - ts)

            vmax = 2.0 * max(abs(om) * r2, abs(V) * r1 / max(r2, 1e-9), 1.0)
            lo, hi = -vmax, vmax
            glo, ghi = gfun(lo), gfun(hi)
            k = 0
            while (glo > 0) == (ghi > 0) and k < 30:
                lo, hi = 2 * lo, 2 * hi
                glo, ghi = gfun(lo), gfun(hi)
                k += 1
            V2 = brentq(gfun, lo, hi, fa=glo, fb=ghi, xtol=1e-12, rtol=1e-12)
            tr, ts = torques(V2)
            W = om * tr * (2.0 if co else 1.0)
            T_rot_tot += tr * (2.0 if co else 1.0)
            T_st_tot += ts if not co else 0.0
            W_tot += W
            dT = W / (m * cp + abs(W) * n / dTmax) if (m * cp + abs(W) * n / dTmax) > 0 else 0.0
            Vm = 0.5 * (V + V2)
            Tt_new = Tt + dT
            Tsm = max(0.5 * (Tt + Tt_new) - Vm * Vm / (2 * cp), 0.2 * Tt)
            if r1 > 0 and r2 > 0:
                p *= math.exp(Vm * Vm / (R * Tsm) * math.log(r2 / r1))
            V, Tt = V2, Tt_new
            cp = gas.cp(Tt)
            if profile:
                prof["r"].append(r2)
                prof["K"].append(V / (om * r2) if om * r2 else 0.0)
                prof["p_rel"].append(p)
                prof["Tt"].append(Tt)
        info = {"V_in": V_in, "V_out": V, "Tt_out": Tt, "ln_pr": math.log(p), "T_rot": T_rot_tot,
                "T_stat": T_st_tot, "W": W_tot, "cal": cal}
        return info, prof

    def evaluate(self, ctx, sa, sb, mdot=None, profile=False):
        mdot = 0.0 if mdot is None else mdot
        rev = mdot < 0.0
        up, dn = (sb, sa) if rev else (sa, sb)
        r_up, r_dn = (self.p["r_b"], self.p["r_a"]) if rev else (self.p["r_a"], self.p["r_b"])
        info, prof = self.march(ctx, up, abs(mdot), r_up, r_dn, profile=profile)
        gas = ctx.gas
        om = ctx.omega(self.p["rotor"])
        cp = gas.cp(info["Tt_out"])
        m = abs(mdot)
        heat = self.p["heat_W"]
        Tt_out = info["Tt_out"] + (heat / (m * cp) if m > 1e-12 else 0.0)
        res = ElementResult(mdot=mdot, Tt_out=Tt_out, rvt_out=r_dn * info["V_out"], r_out=r_dn,
                            log_pr=-info["ln_pr"] if rev else info["ln_pr"])
        b = max(self.p["r_a"], self.p["r_b"])
        Ts = up.Tt - info["V_in"] ** 2 / (2 * gas.cp(up.Tt))
        rho = up.p / (gas.R * max(Ts, 1.0))
        mu = gas.mu(max(Ts, 1.0))
        Re_phi = rho * abs(om) * b * b / mu
        Cw = m / (mu * b)
        lamT = Cw / Re_phi ** 0.8 if Re_phi > 0 else 0.0
        cm_dn, regime = daily_nece_cm(Re_phi, self.p["gap"] / max(b, 1e-9))
        res.outputs = {
            "K in": info["V_in"] / (om * r_up) if om * r_up else 0.0,
            "K out": info["V_out"] / (om * r_dn) if om * r_dn else 0.0,
            "p_dn/p_up": math.exp(info["ln_pr"]),
            "Rotor torque": info["T_rot"], "Stator torque": info["T_stat"],
            "Windage power": info["W"], "ΔTt": Tt_out - up.Tt,
            "Re_φ": Re_phi, "Cw": Cw, "λ_T": lamT, "G": self.p["gap"] / max(b, 1e-9),
            "Cm Daily-Nece": cm_dn, "DN regime": regime, "friction cal.": info["cal"],
        }
        if prof is not None:
            res.profile = prof
        return res
