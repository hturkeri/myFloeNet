"""Verification of myFlowNet against closed-form solutions.

Run:  python -m pytest -q
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from myflownet import Network, solve                                    # noqa: E402
from myflownet.elements import ChamberState, Context, make_element     # noqa: E402
from myflownet.examples import EXAMPLES                                 # noqa: E402
from myflownet.fluid import IdealGasConstant, AirNASA                   # noqa: E402
from myflownet.model import Rotor                                       # noqa: E402

CP, R = 1004.5, 287.05
G = CP / (CP - R)


def ideal_net(title="t"):
    net = Network(title)
    net.settings.gas = {"model": "ideal_constant", "cp": CP, "R": R, "mu": 1.8e-5}
    net.rotors = [Rotor(1, "R", 0.0)]
    return net


def isentropic_orifice(pt, Tt, ps, A, cd):
    pr = max(ps / pt, (2 / (G + 1)) ** (G / (G - 1)))
    return cd * A * pt / math.sqrt(R * Tt) * math.sqrt(2 * G / (G - 1) * (pr ** (2 / G) - pr ** ((G + 1) / G)))


# ---------------------------------------------------------------------------
@pytest.mark.parametrize("p_out", [2.5e5, 1.0e5])   # subcritical and choked
def test_single_orifice_matches_isentropic_formula(p_out):
    net = ideal_net()
    a = net.add_chamber("boundary", "in", p=3e5, T=500.0)
    b = net.add_chamber("boundary", "out", p=p_out, T=300.0, p_type="static")
    net.add_element("orifice", a.id, b.id, diameter=10e-3, cd=0.7)
    # one element between two boundaries: evaluate directly
    from myflownet.solver import _Problem
    prob = _Problem(net)
    p = {a.id: 3e5, b.id: p_out}
    res = prob.eval_elem(1, p, {a.id: 500.0, b.id: 300.0}, {a.id: 0.0, b.id: 0.0}, {})
    ref = isentropic_orifice(3e5, 500.0, p_out, math.pi * 0.01 ** 2 / 4, 0.7)
    assert res.mdot == pytest.approx(ref, rel=1e-10)


def test_orifices_in_series_conserve_mass_and_match_direct_solution():
    net = ideal_net()
    a = net.add_chamber("boundary", "in", p=3e5, T=500.0)
    c = net.add_chamber("plenum", "mid")
    b = net.add_chamber("boundary", "out", p=2e5, T=300.0, p_type="static")
    net.add_element("orifice", a.id, c.id, diameter=10e-3, cd=0.7)
    net.add_element("orifice", c.id, b.id, diameter=12e-3, cd=0.6)
    s = solve(net)
    assert s.converged
    pm = s.chambers[c.id]["p"]
    A1, A2 = math.pi * 0.01 ** 2 / 4, math.pi * 0.012 ** 2 / 4
    m1 = isentropic_orifice(3e5, 500.0, pm, A1, 0.7)
    m2 = isentropic_orifice(pm, 500.0, 2e5, A2, 0.6)
    assert m1 == pytest.approx(m2, rel=1e-8)
    assert s.elements[1]["mdot"] == pytest.approx(m1, rel=1e-8)
    assert s.chambers[b.id]["T_arrival"] == pytest.approx(500.0, abs=1e-6)


def fanno(M, g=G):
    return (1 - M * M) / (g * M * M) + (g + 1) / (2 * g) * math.log((g + 1) * M * M / (2 + (g - 1) * M * M))


def test_pipe_matches_fanno_flow():
    net = ideal_net()
    a = net.add_chamber("boundary", "in", p=3e5, T=400.0)
    b = net.add_chamber("boundary", "out", p=2.0e5, T=300.0, p_type="static")
    net.add_element("pipe", a.id, b.id, length=1.0, diameter=0.02, K_in=0.0, n_seg=200)
    s = solve(net)
    e = s.elements[1]
    m = e["mdot"]
    A = math.pi * 0.02 ** 2 / 4
    from myflownet.compressible import mach_from_flow_function
    M1 = mach_from_flow_function(m * math.sqrt(R * 400.0) / (A * 3e5), G)
    M2 = e["outputs"]["Mach exit"]
    Re = 4 * m / (math.pi * 0.02 * 1.8e-5)
    from myflownet.correlations import friction_factor_darcy
    f = friction_factor_darcy(Re, 0.0)
    # Fanno: f L / D = F(M1) - F(M2)   (Darcy f)
    assert f * 1.0 / 0.02 == pytest.approx(fanno(M1) - fanno(M2), rel=2e-3)


def test_pipe_choking_flow_independent_of_back_pressure():
    flows = []
    for pout in (0.8e5, 0.5e5):
        net = ideal_net()
        a = net.add_chamber("boundary", "in", p=3e5, T=400.0)
        b = net.add_chamber("boundary", "out", p=pout, T=300.0, p_type="static")
        net.add_element("pipe", a.id, b.id, length=0.5, diameter=0.01, K_in=0.0, n_seg=60)
        s = solve(net)
        assert s.elements[1]["choked"]
        flows.append(s.elements[1]["mdot"])
    assert flows[0] == pytest.approx(flows[1], rel=1e-4)


def test_labyrinth_neumann_closed_form():
    """Neumann tooth equation, Cd const, no carry-over:
    m = Cd A sqrt((p0^2 - pn^2) / (n R T))."""
    net = ideal_net()
    a = net.add_chamber("boundary", "in", p=1.5e5, T=300.0)
    b = net.add_chamber("boundary", "out", p=1.2e5, T=300.0, p_type="static")
    net.add_element("labyrinth", a.id, b.id, n_teeth=6, radius=0.1, clearance=0.3e-3,
                    tooth_eq="neumann", cd_model="constant", cd=0.7, carryover="none")
    s = solve(net)
    A = 2 * math.pi * (0.1 + 0.15e-3) * 0.3e-3
    ref = 0.7 * A * math.sqrt((1.5e5 ** 2 - 1.2e5 ** 2) / (6 * R * 300.0))
    assert s.elements[1]["mdot"] == pytest.approx(ref, rel=1e-8)


def test_labyrinth_last_tooth_chokes():
    flows = []
    for pout in (0.4e5, 0.2e5):
        net = ideal_net()
        a = net.add_chamber("boundary", "in", p=4e5, T=300.0)
        b = net.add_chamber("boundary", "out", p=pout, T=300.0, p_type="static")
        net.add_element("labyrinth", a.id, b.id, n_teeth=3)
        s = solve(net)
        assert s.elements[1]["choked"]
        flows.append(s.elements[1]["mdot"])
    assert flows[0] == pytest.approx(flows[1], rel=1e-6)


def _ctx(rpm):
    om = rpm * 2 * math.pi / 60
    return Context(IdealGasConstant(cp_const=CP, R_const=R), {1: om}), om


def test_forced_vortex_pressure_ratio():
    ctx, om = _ctx(10000)
    el = make_element("vortex", {"vortex_type": "forced", "rotor": 1, "r_a": 0.1, "r_b": 0.3,
                                 "swirl_source": "fixed", "K": 0.8, "work": "none"})
    sa = ChamberState(p=5e5, Tt=600.0, K=0.8, omega_ref=om, r=0.1)
    sb = ChamberState(p=5e5, Tt=600.0, K=0.8, omega_ref=om, r=0.3)
    res = el.evaluate(ctx, sa, sb, 0.1)
    w = 0.8 * om
    Ts1 = 600.0 - (w * 0.1) ** 2 / (2 * CP)
    ref = (1 + w * w * (0.3 ** 2 - 0.1 ** 2) / (2 * CP * Ts1)) ** (G / (G - 1))
    assert math.exp(res.log_pr) == pytest.approx(ref, rel=1e-12)
    # isothermal approximation should be close for small rises
    assert res.Tt_out == pytest.approx(600.0)


def test_free_vortex_pressure_ratio_and_angular_momentum():
    ctx, om = _ctx(10000)
    el = make_element("vortex", {"vortex_type": "free", "rotor": 1, "r_a": 0.3, "r_b": 0.15,
                                 "swirl_source": "upstream", "work": "none"})
    sa = ChamberState(p=8e5, Tt=650.0, K=0.5, omega_ref=om, r=0.3)
    sb = ChamberState(p=6e5, Tt=650.0, K=0.0, omega_ref=om, r=0.15)
    res = el.evaluate(ctx, sa, sb, 0.5)
    C = 0.3 * 0.5 * om * 0.3
    Ts1 = 650.0 - (C / 0.3) ** 2 / (2 * CP)
    Ts2 = Ts1 + C * C / (2 * CP) * (1 / 0.3 ** 2 - 1 / 0.15 ** 2)
    assert math.exp(res.log_pr) == pytest.approx((Ts2 / Ts1) ** (G / (G - 1)), rel=1e-12)
    assert res.rvt_out == pytest.approx(C, rel=1e-12)


@pytest.mark.parametrize("wall,K_expected", [("stator", 0.426), ("rotor", 1.0)])
def test_closed_cavity_core_swirl(wall, K_expected):
    ctx, om = _ctx(8000)
    el = make_element("cavity", {"rotor": 1, "r_a": 0.05, "r_b": 0.25, "second_wall": wall,
                                 "swirl_source": "fixed", "K_in": 0.0, "n_seg": 40})
    st = ChamberState(p=3e5, Tt=500.0, K=0.0, omega_ref=om, r=0.05)
    res = el.evaluate(ctx, st, st, 0.0)
    assert res.outputs["K out"] == pytest.approx(K_expected, abs=2e-3)


def test_rotating_radial_pipe_euler_work():
    """Inlet co-rotating (K=1); exit swirl = U2 -> Euler: cp dTt = U2^2 - U1^2."""
    net = ideal_net()
    net.rotors = [Rotor(1, "R", 9000.0)]
    om = 9000 * 2 * math.pi / 60
    a = net.add_chamber("boundary", "feed", p=6e5, T=700.0, K=1.0, radius=0.2)
    b = net.add_chamber("boundary", "tip", p=5e5, T=700.0, p_type="static")
    net.add_element("pipe", a.id, b.id, rotor=1, r_a=0.2, r_b=0.3, length=0.1, diameter=4e-3, n_pipes=50)
    s = solve(net)
    assert s.converged
    dT = s.chambers[b.id]["T_arrival"] - 700.0
    assert dT == pytest.approx(om ** 2 * (0.3 ** 2 - 0.2 ** 2) / CP, rel=1e-6)


def test_preswirl_relative_total_temperature():
    """T_t,rel = T_t,abs - U^2 (2 beta - 1) / (2 cp) at the receiver hole."""
    ctx, om = _ctx(12000)
    r = 0.25
    beta = 1.1
    st = ChamberState(p=19e5, Tt=800.0, K=beta, omega_ref=om, r=r)
    dn = ChamberState(p=18e5, Tt=800.0, K=1.0, omega_ref=om, r=r)
    el = make_element("orifice", {"rotor": 1, "r_a": r, "r_b": r, "diameter": 8e-3, "n_holes": 40})
    res = el.evaluate(ctx, st, dn)
    U = om * r
    assert res.outputs["Tt_rel_in"] == pytest.approx(800.0 - U * U * (2 * beta - 1) / (2 * CP), rel=1e-12)
    # Euler work across the hole: Tt_out - Tt_in = U (U - beta U)/cp
    assert res.Tt_out - 800.0 == pytest.approx(U * U * (1 - beta) / CP, rel=1e-9)


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_examples_converge_and_conserve(name):
    net = EXAMPLES[name]()
    s = solve(net)
    assert s.converged, s.message
    tot = sum(v["flow_out"] for v in s.chambers.values() if v["kind"] == "boundary")
    assert abs(tot) < 1e-7 * max(abs(v["mdot"]) for v in s.elements.values())


def test_energy_conservation_with_heat_and_mixing():
    net = ideal_net()
    a = net.add_chamber("boundary", "hot", p=4e5, T=700.0)
    b = net.add_chamber("boundary", "cold", p=4e5, T=400.0)
    c = net.add_chamber("plenum", "mix", heat_W=2000.0)
    d = net.add_chamber("boundary", "out", p=2e5, T=300.0, p_type="static")
    net.add_element("orifice", a.id, c.id, diameter=6e-3)
    net.add_element("orifice", b.id, c.id, diameter=8e-3)
    net.add_element("orifice", c.id, d.id, diameter=10e-3)
    s = solve(net)
    assert s.converged
    m1, m2, m3 = (s.elements[i]["mdot"] for i in (1, 2, 3))
    h_in = m1 * CP * 700.0 + m2 * CP * 400.0 + 2000.0
    assert m3 * CP * s.chambers[d.id]["T_arrival"] == pytest.approx(h_in, rel=1e-9)


def test_json_roundtrip(tmp_path):
    net = EXAMPLES["HPT pre-swirl cooling system"]()
    f = tmp_path / "m.json"
    net.save(str(f))
    net2 = Network.load(str(f))
    assert net2.to_dict() == net.to_dict()
    s1, s2 = solve(net), solve(net2)
    assert s1.elements[1]["mdot"] == pytest.approx(s2.elements[1]["mdot"], rel=1e-12)


def test_air_properties():
    air = AirNASA()
    assert air.cp(300.0) == pytest.approx(1005.0, rel=3e-3)
    assert air.cp(1000.0) == pytest.approx(1141.0, rel=5e-3)
    assert air.R == pytest.approx(287.05, rel=1e-3)
    # enthalpy is the integral of cp
    T1, T2 = 600.0, 1400.0
    n = 2000
    integ = sum(air.cp(T1 + (i + 0.5) * (T2 - T1) / n) for i in range(n)) * (T2 - T1) / n
    assert air.h(T2) - air.h(T1) == pytest.approx(integ, rel=1e-5)
    assert air.T_from_h(air.h(1234.5)) == pytest.approx(1234.5, abs=1e-8)


# ---------------------------------------------------------------------------
# Momentum chambers: Nart (TEI FlowNet), Fig. 5 / Table 1, vs Altair Flow Simulator
# ---------------------------------------------------------------------------
FLOWSIM_TABLE1 = {0: 9.395, 30: 9.282, 45: 9.099, 60: 8.948, 90: 8.813}   # g/s


def test_momentum_chamber_direction_recovery_vs_flow_simulator():
    from myflownet.examples import nart_momentum_network
    flows = {}
    for th in FLOWSIM_TABLE1:
        s = solve(nart_momentum_network(th))
        assert s.converged, (th, s.message)
        flows[th] = s.elements[1]["mdot"] * 1e3
        # absolute level within 3.5 % of Flow Simulator (K-loss compressibility details differ)
        assert flows[th] == pytest.approx(FLOWSIM_TABLE1[th], rel=0.035)
        # exit Mach number of the 250 mm element (Flow Simulator: 1.50e-4)
        assert s.elements[2]["outputs"]["Mach exit"] == pytest.approx(1.50e-4, rel=0.1)
    # flow falls monotonically as less of the jet head is recovered
    ths = sorted(flows)
    assert all(flows[a] > flows[b] for a, b in zip(ths, ths[1:]))
    # recovery effect theta = 0 vs 90 deg within 1 % of Flow Simulator's ratio
    assert flows[0] / flows[90] == pytest.approx(FLOWSIM_TABLE1[0] / FLOWSIM_TABLE1[90], rel=0.01)


def test_momentum_chamber_at_90_degrees_equals_plenum():
    from myflownet.examples import nart_momentum_network
    a = solve(nart_momentum_network(90.0))
    net = nart_momentum_network(90.0)
    for c in net.chambers.values():
        if c.kind == "momentum":
            c.params["kind"] = "plenum"
    b = solve(net)
    assert a.elements[1]["mdot"] == pytest.approx(b.elements[1]["mdot"], rel=1e-7)


def test_kloss_exit_definition_incompressible_limit():
    """K on the exit dynamic head: at low Mach  m = A sqrt(2 rho (pt - ps)/(1 + K))."""
    net = ideal_net()
    a = net.add_chamber("boundary", "in", p=1.0005e5, T=300.0)
    b = net.add_chamber("boundary", "out", p=1.0e5, T=300.0, p_type="static")
    net.add_element("kloss", a.id, b.id, diameter=0.02, K=3.0, K_def="exit")
    s = solve(net)
    A = math.pi * 0.02 ** 2 / 4
    rho = 1.0e5 / (R * 300.0)
    ref = A * math.sqrt(2 * rho * 50.0 / 4.0)
    assert s.elements[1]["mdot"] == pytest.approx(ref, rel=2e-3)
