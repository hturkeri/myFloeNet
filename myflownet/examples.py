"""Built-in example networks (also used by the tests)."""
from __future__ import annotations

import math
import os

from .model import Network, Rotor


def orifice_series() -> Network:
    net = Network("Two orifices in series")
    net.description = "Validation case: two identical orifices between two boundaries."
    net.rotors = [Rotor(1, "Rotor", 0.0)]
    a = net.add_chamber("boundary", "Supply", -300, 0, p=3e5, T=500.0)
    c = net.add_chamber("plenum", "Middle", 0, 0)
    b = net.add_chamber("boundary", "Exhaust", 300, 0, p=1e5, T=300.0)
    net.add_element("orifice", a.id, c.id, "Orifice 1", diameter=10e-3, cd=0.7)
    net.add_element("orifice", c.id, b.id, "Orifice 2", diameter=10e-3, cd=0.7)
    return net


def seal_pipe_chain() -> Network:
    net = Network("Labyrinth - pipe - bend chain")
    net.description = "Stationary chain: 5-tooth labyrinth, 0.5 m pipe and a 90° bend (K = 1.2)."
    net.rotors = [Rotor(1, "Rotor", 0.0)]
    b1 = net.add_chamber("boundary", "Supply", -450, 0, p=4e5, T=300.0)
    c2 = net.add_chamber("plenum", "Seal exit", -150, 0)
    c3 = net.add_chamber("plenum", "Pipe exit", 150, 0)
    b4 = net.add_chamber("boundary", "Ambient", 450, 0, p=1e5, T=288.15)
    net.add_element("labyrinth", b1.id, c2.id, "Labyrinth", n_teeth=5, radius=0.1, clearance=0.4e-3,
                    pitch=4e-3, tip_width=0.25e-3)
    net.add_element("pipe", c2.id, c3.id, "Pipe", length=0.5, diameter=20e-3, roughness=10e-6, K_in=0.5)
    net.add_element("kloss", c3.id, b4.id, "Bend 90°", diameter=20e-3, K=1.2)
    return net


def rotor_stator_cavity() -> Network:
    net = Network("Rotor-stator cavity with radial outflow")
    net.description = ("Air enters a rotor-stator wheel-space at low radius, flows radially outward "
                       "through the cavity (1D radial march) and leaves through the rim seal.")
    net.rotors = [Rotor(1, "HP Rotor", 9000.0)]
    b1 = net.add_chamber("boundary", "Bore supply", -450, 0, p=6e5, T=550.0)
    c2 = net.add_chamber("inertial", "Cavity inlet", -150, 0, radius=0.08, ref_rotor=1)
    c3 = net.add_chamber("inertial", "Rim cavity", 150, 0, radius=0.25, ref_rotor=1)
    b4 = net.add_chamber("boundary", "Annulus", 450, 0, p=5.2e5, p_type="static", T=900.0, radius=0.26)
    net.add_element("orifice", b1.id, c2.id, "Inlet holes", n_holes=12, diameter=6e-3, cd=0.65,
                    r_a=0.08, r_b=0.08)
    net.add_element("cavity", c2.id, c3.id, "Wheel-space", rotor=1, r_a=0.08, r_b=0.25, gap=6e-3)
    net.add_element("orifice", c3.id, b4.id, "Rim seal", area_override=4.0e-4, cd=0.6, r_a=0.25, r_b=0.25)
    return net


def preswirl_system() -> Network:
    net = Network("HP turbine pre-swirl cooling system")
    net.description = ("Direct-transfer pre-swirl system: stationary pre-swirl nozzles feed a rotating "
                       "receiver-hole row; the cover-plate cavity (forced vortex, K = 1) pumps the air up to "
                       "the blade feed; radial rotating blade passages discharge to the gas path. "
                       "Inner and outer labyrinths leak from the pre-swirl chamber; the outer leakage "
                       "passes a rotor-stator wheel-space and leaves through the rim seal.")
    net.rotors = [Rotor(1, "HP Rotor", 12000.0)]
    B1 = net.add_chamber("boundary", "Compressor delivery", -640, 0, p=25e5, T=800.0)
    C2 = net.add_chamber("inertial", "Pre-swirl chamber", -340, 0, radius=0.25, ref_rotor=1)
    C3 = net.add_chamber("inertial", "Cover-plate inlet", -40, 0, radius=0.25, ref_rotor=1, K=1.0)
    C4 = net.add_chamber("inertial", "Blade feed", 260, 0, radius=0.30, ref_rotor=1, K=1.0)
    B5 = net.add_chamber("boundary", "Blade exit (gas path)", 560, 0, p=14e5, p_type="static", T=1300.0)
    B6 = net.add_chamber("boundary", "Bearing chamber vent", -340, 280, p=9e5, p_type="static", T=600.0)
    C7 = net.add_chamber("inertial", "Upper wheel-space", -340, -300, radius=0.28, ref_rotor=1)
    C8 = net.add_chamber("inertial", "Rim cavity", -40, -300, radius=0.34, ref_rotor=1)
    B9 = net.add_chamber("boundary", "Annulus", 260, -300, p=15e5, p_type="static", T=1200.0, radius=0.35)
    net.add_element("orifice", B1.id, C2.id, "Pre-swirl nozzles", n_holes=24, diameter=7e-3, cd=0.9,
                    exit_angle=75.0, r_a=0.25, r_b=0.25)
    net.add_element("orifice", C2.id, C3.id, "Receiver holes", n_holes=48, diameter=8e-3, cd=0.75,
                    rotor=1, r_a=0.25, r_b=0.25, dq_in=0.0)
    net.add_element("vortex", C3.id, C4.id, "Cover-plate cavity", vortex_type="forced", rotor=1,
                    r_a=0.25, r_b=0.30, swirl_source="fixed", K=1.0, work="rotor")
    net.add_element("pipe", C4.id, B5.id, "Blade passages", n_pipes=80, length=0.06, diameter=3.0e-3,
                    rotor=1, r_a=0.30, r_b=0.36, K_in=0.6)
    net.add_element("labyrinth", C2.id, B6.id, "Inner labyrinth", n_teeth=4, radius=0.20,
                    clearance=0.35e-3, pitch=4e-3, tip_width=0.3e-3, rotor=1)
    net.add_element("labyrinth", C2.id, C7.id, "Outer labyrinth", n_teeth=3, radius=0.28,
                    clearance=0.4e-3, pitch=4e-3, tip_width=0.3e-3, rotor=1)
    net.add_element("cavity", C7.id, C8.id, "Rotor-stator wheel-space", rotor=1, r_a=0.28, r_b=0.34,
                    gap=5e-3)
    net.add_element("orifice", C8.id, B9.id, "Rim seal", area_override=6.0e-4, cd=0.6, r_a=0.34, r_b=0.34)
    return net


GEOMETRY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "geometry")


def preswirl_on_cad() -> Network:
    """The pre-swirl network drawn on the meridional section of a CAD model (background geometry)."""
    net = preswirl_system()
    net.title = "HPT pre-swirl system on CAD geometry"
    net.description = ("The pre-swirl network of the 'HPT pre-swirl cooling system' example, drawn on the "
                       "meridional section of the CAD model examples/geometry/hpt_preswirl_rig.step "
                       "(background geometry, engine axis X, cut angle θ = 0 through a nozzle and a receiver "
                       "hole). Chamber reference radii are taken from their positions on the section "
                       "(Model → Set chamber radii from background geometry).")
    s, ox, oy = 3.0, -105.0, 960.0           # canvas = (ox + s·axial, oy − s·r)
    where = {"Compressor delivery": (-62, 268), "Pre-swirl chamber": (40, 250), "Cover-plate inlet": (84, 250),
             "Blade feed": (84, 302), "Blade exit (gas path)": (128, 398), "Bearing chamber vent": (32, 170),
             "Upper wheel-space": (28, 322), "Rim cavity": (64, 343), "Annulus": (35, 392)}
    for ch in net.chambers.values():
        ax, r = where[ch.name]
        ch.x, ch.y = ox + s * ax, oy - s * r
        if not ch.is_boundary:
            ch.params["radius"] = r / 1000.0
    net.background = {"file": os.path.join(GEOMETRY_DIR, "hpt_preswirl_rig.step"), "quality": "normal",
                      "unit_scale": 1.0, "axis": "x", "origin": [0.0, 0.0, 0.0], "theta": 0.0, "yaw": 0.0,
                      "pitch": 0.0, "cut": True, "upper_half": True, "show_faces": True, "show_edges": True,
                      "show_section": True, "opacity": 0.9, "surface_opacity": 0.45, "scale": s, "offset": [ox, oy], "visible": True,
                      "snap": True}
    return net


def bore_free_vortex() -> Network:
    net = Network("Compressor bleed - free vortex - shaft")
    net.description = ("Air bled through rotating holes in the compressor drum enters the drum cavity "
                       "with solid-body swirl and flows radially inward as a free vortex (angular momentum "
                       "conserved): the static pressure drops strongly - the reason vortex reducers are "
                       "used.  The air then flows along the shaft bore (pipe) to the turbine.")
    net.rotors = [Rotor(1, "HP Rotor", 11000.0)]
    B1 = net.add_chamber("boundary", "Compressor bleed", -480, 0, p=12e5, T=650.0, K=0.6, radius=0.28)
    C2 = net.add_chamber("inertial", "Drum cavity (outer)", -200, 0, radius=0.27, ref_rotor=1, K=1.0)
    C3 = net.add_chamber("inertial", "Shaft bore inlet", 80, 0, radius=0.15, ref_rotor=1)
    B4 = net.add_chamber("boundary", "Turbine disc cavity", 360, 0, p=3.0e5, p_type="static", T=700.0)
    net.add_element("orifice", B1.id, C2.id, "Bleed holes", n_holes=30, diameter=8e-3, cd=0.7, rotor=1,
                    r_a=0.28, r_b=0.27)
    net.add_element("vortex", C2.id, C3.id, "Free vortex (radial inflow)", vortex_type="free", rotor=1,
                    r_a=0.27, r_b=0.15, swirl_source="upstream", work="none")
    net.add_element("pipe", C3.id, B4.id, "Shaft bore", length=1.2, diameter=0.08, roughness=20e-6, K_in=0.3)
    return net


def nart_momentum_network(theta: float = 45.0) -> Network:
    """Validation network of Nart (TEI FlowNet paper, Fig. 5) against Altair Flow Simulator."""
    net = Network(f"Momentum chambers - sudden area and direction change (θ = {theta:g}°)")
    net.description = ("Validation case of Nart, 'Development of Newton Raphson Based 1D Flow Network "
                       "Solver' (TEI FlowNet), Fig. 5 / Table 1: K-loss elements D = 5 mm, 250 mm, 5 mm, "
                       "K = 2; inlet Pt = Ps = 5 bar, 500 K; exit Ps = 2 bar; dry air. The jet of element 1 "
                       "enters momentum chamber 2; element 2 is turned by θ and recovers the jet's dynamic "
                       "head as cos²θ. Flow Simulator mass flow: 9.395 / 9.282 / 9.099 / 8.948 / 8.813 g/s "
                       "for θ = 0 / 30 / 45 / 60 / 90°.")
    net.rotors = [Rotor(1, "Rotor", 0.0)]
    rad = math.radians(theta)
    b1 = net.add_chamber("boundary", "Node 1 (Pt = Ps = 5 bar)", -420, -60, p=5e5, T=500.0)
    c2 = net.add_chamber("momentum", "Node 2", -140, -60)
    c3 = net.add_chamber("momentum", "Node 3", -140 + 260 * math.cos(rad), -60 + 260 * math.sin(rad))
    b4 = net.add_chamber("boundary", "Node 4 (Ps = 2 bar)", -140 + 260 * math.cos(rad) + 280,
                         -60 + 260 * math.sin(rad), p=2e5, p_type="static", T=500.0)
    net.add_element("kloss", b1.id, c2.id, "D 5 mm, K 2", diameter=5e-3, K=2.0, direction=0.0)
    net.add_element("kloss", c2.id, c3.id, "D 250 mm, K 2", diameter=0.25, K=2.0, direction=-theta)
    net.add_element("kloss", c3.id, b4.id, "D 5 mm, K 2 ", diameter=5e-3, K=2.0, direction=0.0)
    return net


EXAMPLES = {
    "Orifice series (validation)": orifice_series,
    "Labyrinth - pipe - bend": seal_pipe_chain,
    "Rotor-stator cavity": rotor_stator_cavity,
    "HPT pre-swirl cooling system": preswirl_system,
    "HPT pre-swirl system on CAD geometry": preswirl_on_cad,
    "Bleed + free vortex + shaft": bore_free_vortex,
    "Momentum chambers (Nart / Flow Simulator)": nart_momentum_network,
}
