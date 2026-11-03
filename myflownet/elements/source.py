"""Flow-source type elements whose flow does not depend on the pressures."""
from __future__ import annotations

import math

from ..correlations import disc_pumping_mdot
from ..params import ParamSpec
from .base import Element, ElementResult, register


class _SourceBase(Element):
    category = "mass"

    def _result(self, ctx, sa, sb, m, r_a, r_b):
        rev = m < 0
        up = sb if rev else sa
        r_up, r_dn = (r_b, r_a) if rev else (r_a, r_b)
        cp = ctx.gas.cp(up.Tt)
        heat = self.p.get("heat_W", 0.0)
        Tt = up.Tt + (heat / (abs(m) * cp) if abs(m) > 1e-12 else 0.0)
        vt_up = up.vtheta(r_up)
        rvt = r_up * vt_up
        return ElementResult(mdot=m, Tt_out=Tt, rvt_out=rvt, r_out=r_dn)


@register
class FixedFlow(_SourceBase):
    type_name = "fixedflow"
    label = "Fixed Flow"
    symbol = "fixedflow"
    description = "Prescribed mass flow from port a to port b (e.g. measured bleed, cooling demand)."
    PARAMS = [
        ParamSpec("mdot", "Mass flow (a → b)", 0.01, unit="massflow", group="Flow"),
        ParamSpec("r_a", "Radius at port a", 0.0, unit="length", minimum=0.0, group="Flow"),
        ParamSpec("r_b", "Radius at port b", 0.0, unit="length", minimum=0.0, group="Flow"),
        ParamSpec("heat_W", "Heat added", 0.0, unit="power", group="Flow"),
    ]

    def port_radii(self):
        return self.p["r_a"], self.p["r_b"]

    def evaluate(self, ctx, sa, sb, mdot=None):
        res = self._result(ctx, sa, sb, self.p["mdot"], self.p["r_a"], self.p["r_b"])
        res.outputs = {"prescribed": self.p["mdot"]}
        return res


@register
class DiscPumping(_SourceBase):
    type_name = "discpump"
    label = "Disc Pumping"
    symbol = "discpump"
    description = ("Boundary-layer pumping of a rotating disc face between two radii "
                   "(Sultanian 2018 / Owen & Rogers form), driven by the core swirl of chamber a.")
    PARAMS = [
        ParamSpec("rotor", "Rotor (disc)", 1, kind="rotor", group="Pumping"),
        ParamSpec("r_a", "Inner radius (port a)", 0.05, unit="length", minimum=0.0, group="Pumping"),
        ParamSpec("r_b", "Outer radius (port b)", 0.2, unit="length", minimum=0.0, group="Pumping"),
        ParamSpec("model", "Correlation", "sultanian", kind="choice",
                  choices=(("sultanian", "Sultanian"), ("owen_rogers", "Owen & Rogers")), group="Pumping"),
        ParamSpec("mult", "Flow multiplier", 1.0, minimum=0.0, group="Pumping"),
        ParamSpec("heat_W", "Heat added", 0.0, unit="power", group="Pumping"),
    ]

    def port_radii(self):
        return self.p["r_a"], self.p["r_b"]

    def evaluate(self, ctx, sa, sb, mdot=None):
        gas = ctx.gas
        om = ctx.omega(self.p["rotor"])
        Ts = sa.Tt
        rho = sa.p / (gas.R * Ts)
        mu = gas.mu(Ts)
        Sf = sa.vtheta(self.p["r_b"]) / (om * self.p["r_b"]) if om * self.p["r_b"] else 0.0
        m = self.p["mult"] * (disc_pumping_mdot(mu, rho, self.p["r_b"], om, Sf, self.p["model"])
                              - disc_pumping_mdot(mu, rho, self.p["r_a"], om, Sf, self.p["model"]))
        res = self._result(ctx, sa, sb, m, self.p["r_a"], self.p["r_b"])
        res.outputs = {"swirl Sf": Sf, "pumped": m}
        return res
