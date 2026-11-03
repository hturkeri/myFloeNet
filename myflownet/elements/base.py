"""Element base classes.

Conventions
-----------
* Every element connects port ``a`` to port ``b``.  The signed mass flow
  ``mdot`` is positive from a to b.
* Chambers carry static pressure ``p``, absolute total temperature ``Tt`` and
  a swirl ratio ``K`` (absolute tangential velocity / reference-rotor speed):
  V_theta(r) = K * Omega_ref * r.
* Mass-type elements return mdot(p_a, p_b, ...).  Pressure-type elements
  (vortices, cavities) receive mdot as an extra unknown and return the static
  pressure ratio p_b/p_a they impose.
* Elements return the exit state of the flow (absolute total temperature and
  angular momentum r*V_theta) so that the solver can mix it into the
  downstream chamber.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ..params import ParamSpec, merge_params


@dataclass
class ChamberState:
    p: float          # static pressure [Pa]
    Tt: float         # absolute total temperature [K]
    K: float          # swirl ratio relative to reference rotor
    omega_ref: float  # reference rotor speed [rad/s]
    r: float = 0.0    # chamber reference radius [m]
    is_boundary: bool = False
    vm: float = 0.0   # through-flow (meridional) speed of a momentum chamber [m/s]
    phi: float = 0.0  # direction of that velocity in the meridional plane [deg]

    def vtheta(self, r: float) -> float:
        return self.K * self.omega_ref * r


@dataclass
class Context:
    gas: object
    rotor_omega: dict           # rotor id -> rad/s (0 -> 0)

    def omega(self, rotor_id: int) -> float:
        if not rotor_id:
            return 0.0
        return self.rotor_omega.get(int(rotor_id), 0.0)


@dataclass
class InletState:
    """Flow state at the inlet of an element, in the element's frame."""
    ps: float
    pt: float        # driving total pressure (after DQ_IN)
    Tt_rel: float    # total temperature in the element frame
    Ts: float
    vtheta: float    # absolute tangential velocity at inlet radius
    w_theta: float   # relative tangential velocity
    r: float
    U: float         # blade speed at inlet radius
    gamma: float
    cp: float
    R: float
    rho: float


def recovered_total(ctx: Context, st: ChamberState, phi_dir: float) -> float:
    """Static pressure plus the part of a momentum chamber's through-flow head that
    is recovered in direction phi_dir (cos^2 projection, compressible):
        p * (1 + (vm cos(theta))^2 / (2 cp Ts))^(g/(g-1)),  theta = phi_dir - phi_chamber
    (Nart, FlowNet Eq. 10).  Used both as an element's driving pressure and, in
    the opposite direction, as the back pressure of a jet entering the chamber
    against its flow, so that the two are exactly consistent."""
    if st.vm <= 0.0:
        return st.p
    c = max(math.cos(math.radians(phi_dir - st.phi)), 0.0)
    if c == 0.0:
        return st.p
    gas = ctx.gas
    cp = gas.cp(st.Tt)
    vt = st.vtheta(st.r)
    Ts = max(st.Tt - (vt * vt + st.vm * st.vm) / (2.0 * cp), 0.2 * st.Tt)
    g = gas.gamma(st.Tt)
    return st.p * (1.0 + (st.vm * c) ** 2 / (2.0 * cp * Ts)) ** (g / (g - 1.0))


def back_pressure(ctx: Context, st: ChamberState, phi_jet: float) -> float:
    """Pressure an element jet (direction phi_jet) discharges against: the static
    pressure, raised by the head of a momentum chamber's through-flow that runs
    against the jet.  This makes the forward and reverse driving potentials of an
    element antisymmetric, so the flow direction is unique and mdot(p) continuous."""
    return recovered_total(ctx, st, phi_jet + 180.0)


def inlet_state(ctx: Context, st: ChamberState, r: float, omega_e: float, dq_in: float,
                phi_e: float | None = None) -> InletState:
    """Inlet state of an element fed by chamber `st`.

    Driving total pressure = static pressure + recovered dynamic heads:
      * through-flow of a momentum chamber: cos^2(theta) projection on the element
        direction phi_e (Nart, FlowNet Eq. 8/10), see recovered_total();
      * relative tangential (swirl) head: fraction (1 - DQ_IN).
    """
    gas = ctx.gas
    vt = st.vtheta(r)
    vm = st.vm
    cp = gas.cp(st.Tt)
    Ts = max(st.Tt - (vt * vt + vm * vm) / (2.0 * cp), 0.2 * st.Tt)
    U = omega_e * r
    w = vt - U
    Tt_rel = Ts + (w * w + vm * vm) / (2.0 * cp)
    g = gas.gamma(0.5 * (Ts + Tt_rel))
    p_m = recovered_total(ctx, st, phi_e) if (vm > 0.0 and phi_e is not None) else st.p
    pt = p_m * (1.0 + (1.0 - dq_in) * w * w / (2.0 * cp * Ts)) ** (g / (g - 1.0))
    rho = st.p / (gas.R * Ts)
    return InletState(ps=st.p, pt=pt, Tt_rel=Tt_rel, Ts=Ts, vtheta=vt, w_theta=w, r=r, U=U,
                      gamma=g, cp=cp, R=gas.R, rho=rho)


def rotational_pumping(inl: InletState, U_out: float) -> tuple[float, float]:
    """Isentropic effect of radius change in a rotating element (rothalpy
    conservation): returns (pt_eff, Tt_rel_eff) at the outlet radius."""
    if inl.U == U_out:
        return inl.pt, inl.Tt_rel
    Tt2 = inl.Tt_rel + (U_out * U_out - inl.U * inl.U) / (2.0 * inl.cp)
    Tt2 = max(Tt2, 0.3 * inl.Tt_rel)
    g = inl.gamma
    pt2 = inl.pt * (Tt2 / inl.Tt_rel) ** (g / (g - 1.0))
    return pt2, Tt2


@dataclass
class ElementResult:
    mdot: float = 0.0                 # signed, a -> b positive
    Tt_out: float = 0.0               # absolute total temperature of flow leaving element
    rvt_out: float = 0.0              # r * V_theta (absolute) of flow leaving element
    r_out: float = 0.0
    log_pr: float = 0.0               # pressure-type: ln(p_b/p_a) imposed
    choked: bool = False
    vm_out: float = 0.0               # through-flow speed of the exit jet (for momentum chambers)
    phi_out: float = 0.0              # direction of the exit jet in the meridional plane [deg]
    outputs: dict = field(default_factory=dict)
    profile: dict | None = None       # optional radial/axial distribution for plotting


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
REGISTRY: dict[str, type] = {}


def register(cls):
    REGISTRY[cls.type_name] = cls
    return cls


COMMON_ROT = [
    ParamSpec("rotor", "Rotor", 0, kind="rotor", group="Rotation",
              tip="Rotor the element is attached to (0 = stationary)."),
    ParamSpec("r_a", "Radius at port a", 0.0, unit="length", group="Rotation", minimum=0.0,
              tip="Radial position of the element inlet/outlet at port a."),
    ParamSpec("r_b", "Radius at port b", 0.0, unit="length", group="Rotation", minimum=0.0,
              tip="Radial position at port b (differs from r_a for radial holes/pipes)."),
]

COMMON_FLOW = [
    ParamSpec("dq_in", "Inlet dyn. head lost (DQ_IN)", 1.0, minimum=0.0, maximum=1.0, group="Inlet / exit",
              tip="Fraction of the upstream relative tangential dynamic head that is lost "
                  "(1 = only static pressure drives the flow, 0 = full recovery)."),
    ParamSpec("swirl_out", "Exit swirl", "auto", kind="choice",
              choices=(("auto", "Element physics"), ("conserve", "Conserve r·Vθ"),
                       ("fixed", "Fixed K")), group="Inlet / exit",
              tip="auto: stationary -> jet tangential component; rotating -> U + jet component.\n"
                  "conserve: angular momentum carried through (free vortex).\n"
                  "fixed: V_theta = K * Omega_ref * r_out (Omega_ref = downstream chamber rotor)."),
    ParamSpec("exit_K", "Exit swirl ratio K", 0.0, group="Inlet / exit", visible_if=("swirl_out", "fixed")),
    ParamSpec("exit_angle", "Exit jet angle", 0.0, unit="angle", group="Inlet / exit",
              tip="Angle of the exit jet from the element axis towards the direction of rotation "
                  "(pre-swirl nozzles: 60-80 deg)."),
    ParamSpec("direction", "Flow direction φ", 0.0, unit="angle", group="Inlet / exit",
              tip="Direction of the element axis in the meridional plane (a → b). A momentum chamber "
                  "upstream passes on its through-flow dynamic head as cos²θ, θ = angle between the "
                  "chamber velocity and this direction (Nart, FlowNet Eq. 8/10)."),
    ParamSpec("heat_W", "Heat added", 0.0, unit="power", group="Inlet / exit"),
]


class Element:
    """Base class for all elements."""

    type_name = "base"
    label = "Element"
    category = "mass"       # "mass" or "pressure"
    symbol = "box"
    description = ""
    PARAMS: list[ParamSpec] = []

    def __init__(self, params: dict | None = None):
        self.p = merge_params(self.PARAMS, params)

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return cls.PARAMS

    # Pressure-type elements override
    def evaluate(self, ctx: Context, sa: ChamberState, sb: ChamberState, mdot: float | None = None) -> ElementResult:
        raise NotImplementedError

    # --- helpers --------------------------------------------------------
    def port_radii(self) -> tuple[float, float]:
        return self.p.get("r_a", 0.0), self.p.get("r_b", 0.0)

    def radii(self, reverse: bool) -> tuple[float, float]:
        ra, rb = self.port_radii()
        return (rb, ra) if reverse else (ra, rb)


class TwoPortMass(Element):
    """Mass-type element: mdot = f(upstream state, downstream static pressure)."""

    category = "mass"

    # subclasses implement: flow magnitude for given direction
    def forward(self, ctx: Context, inl: InletState, pt_eff: float, Tt_eff: float, dn: ChamberState,
                r_in: float, r_out: float, reverse: bool) -> tuple[float, dict]:
        """Return (mdot >= 0, info). info may contain 'v_jet', 'choked' and outputs."""
        raise NotImplementedError

    def _drive(self, ctx, up: ChamberState, r_in: float, r_out: float, reverse: bool = False):
        om = ctx.omega(self.p.get("rotor", 0))
        phi = self.p.get("direction", 0.0) + (180.0 if reverse else 0.0)
        inl = inlet_state(ctx, up, r_in, om, self.p.get("dq_in", 1.0), phi)
        pt_eff, Tt_eff = rotational_pumping(inl, om * r_out)
        return om, inl, pt_eff, Tt_eff

    def evaluate(self, ctx, sa, sb, mdot=None):
        ra, rb = self.port_radii()
        om_f, inl_f, pt_f, Tt_f = self._drive(ctx, sa, ra, rb)
        om_r, inl_r, pt_r, Tt_r = self._drive(ctx, sb, rb, ra, reverse=True)
        phi = self.p.get("direction", 0.0)
        pb = back_pressure(ctx, sb, phi)
        pa = back_pressure(ctx, sa, phi + 180.0)
        if pb != sb.p:
            sb = replace(sb, p=pb)
        if pa != sa.p:
            sa = replace(sa, p=pa)
        pot_f = pt_f - sb.p
        pot_r = pt_r - sa.p
        if pot_f > 0.0 and pot_r > 0.0:
            # Both sides can drive the element (recovered dynamic heads larger than the static
            # pressure difference, e.g. opposing jets): the net flow is the difference of the two
            # one-way flows, which keeps mdot(p) continuous through the direction change.
            m_f, info_f = self.forward(ctx, inl_f, pt_f, Tt_f, sb, ra, rb, False)
            m_r, info_r = self.forward(ctx, inl_r, pt_r, Tt_r, sa, rb, ra, True)
            if m_f >= m_r:
                m, info = m_f - m_r, info_f
                sign, inl, Tt_eff, up, dn, r_in, r_out, om = 1.0, inl_f, Tt_f, sa, sb, ra, rb, om_f
            else:
                m, info = m_r - m_f, info_r
                sign, inl, Tt_eff, up, dn, r_in, r_out, om = -1.0, inl_r, Tt_r, sb, sa, rb, ra, om_r
            full = max(m_f, m_r)
            if full > 0 and "v_jet" in info:
                info = dict(info)
                info["v_jet"] = info["v_jet"] * m / full
        elif pot_f >= pot_r:
            m, info = self.forward(ctx, inl_f, pt_f, Tt_f, sb, ra, rb, False)
            sign, inl, Tt_eff, up, dn, r_in, r_out, om = 1.0, inl_f, Tt_f, sa, sb, ra, rb, om_f
        else:
            m, info = self.forward(ctx, inl_r, pt_r, Tt_r, sa, rb, ra, True)
            sign, inl, Tt_eff, up, dn, r_in, r_out, om = -1.0, inl_r, Tt_r, sb, sa, rb, ra, om_r
        res = ElementResult(mdot=sign * m, r_out=r_out, choked=bool(info.get("choked", False)))
        self._exit_state(ctx, res, info, inl, Tt_eff, up, dn, r_in, r_out, om, abs(m))
        res.outputs.update(info.get("outputs", {}))
        res.vm_out = info.get("v_jet", 0.0) * abs(math.cos(math.radians(self.p.get("exit_angle", 0.0))))
        res.phi_out = self.p.get("direction", 0.0) + (0.0 if sign > 0 else 180.0)
        return res

    def _exit_state(self, ctx, res, info, inl, Tt_eff, up, dn, r_in, r_out, om, m):
        cp = inl.cp
        U_out = om * r_out
        heat = self.p.get("heat_W", 0.0)
        Tt_rel_out = info.get("Tt_rel_exit", Tt_eff) + (heat / (m * cp) if m > 1e-12 else 0.0)
        v_jet = info.get("v_jet", 0.0)
        ang = math.radians(self.p.get("exit_angle", 0.0))
        w_t = v_jet * math.sin(ang)
        mode = self.p.get("swirl_out", "auto")
        if mode == "conserve":
            vt = inl.vtheta * r_in / r_out if r_out > 0 else 0.0
        elif mode == "fixed":
            vt = self.p.get("exit_K", 0.0) * dn.omega_ref * r_out
        else:
            vt = U_out + w_t
        if om != 0.0 and mode != "auto":
            # rotating element forcing a non-physical swirl: keep relative energy, adjust absolute
            w_t = vt - U_out
        # absolute total temperature at exit: Tt_abs = Tt_rel + (V^2 - W^2)/(2cp)
        if om == 0.0:
            Tt_abs = Tt_rel_out          # stationary element: no work, Tt conserved
        else:
            Tt_abs = Tt_rel_out + (vt * vt - w_t * w_t) / (2.0 * cp)
        res.Tt_out = Tt_abs
        res.rvt_out = r_out * vt
        res.outputs.setdefault("Vθ_exit", vt)
        res.outputs.setdefault("Tt_rel_in", inl.Tt_rel)
        res.outputs.setdefault("pt_in", inl.pt)


def make_element(type_name: str, params: dict | None = None) -> Element:
    if type_name not in REGISTRY:
        raise KeyError(f"Unknown element type '{type_name}'")
    return REGISTRY[type_name](params)
