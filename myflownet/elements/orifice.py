"""Orifice / hole / nozzle element (stationary or rotating)."""
from __future__ import annotations

import math

from ..compressible import isentropic_mdot, jet_velocity, critical_pr
from ..correlations import cd_corner_radius, cd_length
from ..params import ParamSpec
from .base import COMMON_FLOW, COMMON_ROT, TwoPortMass, register


@register
class Orifice(TwoPortMass):
    type_name = "orifice"
    label = "Orifice / Hole"
    symbol = "orifice"
    description = ("Compressible isentropic orifice with discharge coefficient. Covers stationary holes, "
                   "pre-swirl nozzles (exit angle) and rotating receiver/radial holes (rotor + radii).")
    PARAMS = [
        ParamSpec("n_holes", "Number of holes", 1, kind="int", minimum=1, group="Geometry"),
        ParamSpec("diameter", "Hole diameter", 5e-3, unit="length", minimum=0.0, group="Geometry"),
        ParamSpec("area_override", "Total area (override)", 0.0, unit="area", minimum=0.0, group="Geometry",
                  tip="If > 0 this total flow area is used instead of n·π·d²/4."),
        ParamSpec("cd_mode", "Cd model", "constant", kind="choice",
                  choices=(("constant", "Constant Cd"), ("mcgreehan", "Sharp-edged + McGreehan & Schotsch")),
                  group="Discharge coefficient"),
        ParamSpec("cd", "Cd", 0.65, minimum=0.01, maximum=1.0, group="Discharge coefficient",
                  visible_if=("cd_mode", "constant")),
        ParamSpec("cd0", "Base Cd (sharp, thin)", 0.61, minimum=0.01, maximum=1.0, group="Discharge coefficient",
                  visible_if=("cd_mode", "mcgreehan")),
        ParamSpec("length", "Hole length L", 0.0, unit="length", minimum=0.0, group="Discharge coefficient",
                  visible_if=("cd_mode", "mcgreehan")),
        ParamSpec("corner_radius", "Inlet corner radius", 0.0, unit="length", minimum=0.0,
                  group="Discharge coefficient", visible_if=("cd_mode", "mcgreehan")),
        ParamSpec("cd_rev", "Reverse-flow Cd (0 = same)", 0.0, minimum=0.0, maximum=1.0,
                  group="Discharge coefficient"),
    ] + COMMON_ROT + COMMON_FLOW

    def area(self) -> float:
        if self.p["area_override"] > 0.0:
            return self.p["area_override"]
        return self.p["n_holes"] * math.pi * self.p["diameter"] ** 2 / 4.0

    def cd_value(self, reverse: bool) -> float:
        if reverse and self.p["cd_rev"] > 0.0:
            return self.p["cd_rev"]
        if self.p["cd_mode"] == "mcgreehan":
            d = max(self.p["diameter"], 1e-9)
            cd = cd_corner_radius(self.p["cd0"], self.p["corner_radius"] / d)
            # effective length reduced by the radius (McGreehan & Schotsch practice)
            L_eff = max(self.p["length"] - self.p["corner_radius"], 0.0)
            return cd_length(cd, L_eff / d)
        return self.p["cd"]

    def forward(self, ctx, inl, pt_eff, Tt_eff, dn, r_in, r_out, reverse):
        A = self.area()
        cd = self.cd_value(reverse)
        g = inl.gamma
        m_id, choked = isentropic_mdot(pt_eff, Tt_eff, dn.p, A, g, inl.R)
        m = cd * m_id
        pr = dn.p / pt_eff if pt_eff > 0 else 1.0
        v = jet_velocity(Tt_eff, pr, g, inl.cp)   # sqrt(2 dp / rho) -> 0 smoothly as pr -> 1
        a_star = math.sqrt(g * inl.R * Tt_eff * max(pr, critical_pr(g)) ** ((g - 1) / g))
        nh = max(self.p["n_holes"], 1)
        d = self.p["diameter"] if self.p["area_override"] <= 0 else math.sqrt(4 * A / (math.pi * nh))
        mu = ctx.gas.mu(Tt_eff)
        Re = 4.0 * (m / nh) / (math.pi * max(d, 1e-9) * mu)
        return m, {"v_jet": v, "choked": choked,
                   "outputs": {"Cd": cd, "Area": A, "PR (pt/ps)": pt_eff / dn.p if dn.p > 0 else 0.0,
                               "Mach jet": v / a_star if a_star > 0 else 0.0, "Re": Re,
                               "choked": choked}}
