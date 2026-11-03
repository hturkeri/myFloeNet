"""Network solver.

Method (SASS-type, cf. Majumdar's GFSSP and the Altair Flow Simulator solver):

1. Unknowns of the Newton system: static pressure of every internal chamber
   plus the mass flow of every pressure-type element (vortex, cavity).
2. Residuals: mass balance of every internal chamber and the pressure
   relation ln(p_b) - ln(p_a) - ln(PR_e) = 0 of every pressure-type element.
3. Jacobian assembled from element-local finite differences (each element
   only depends on its own two chambers -> sparse structure, cheap).
4. Damped Newton step with pressure-change limiting and a back-tracking line
   search on the residual norm.
5. After every accepted step the energy equation (total enthalpy mixing,
   solved as a linear system) and the angular-momentum (swirl) balance of
   inertial chambers are updated by successive substitution.
6. Momentum chambers (through-flow dynamic pressure q = Pt - Ps carried to the
   next element as cos^2(theta), Nart's FlowNet formulation) are handled in an
   outer loop: the inner Newton converges with q frozen, then q is updated from
   the incoming jets.  Starting from q = 0 reproduces Nart's initialisation
   (first solve with momentum transfer disabled, Pt = Ps).
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field

import numpy as np

from .elements import ChamberState, Context
from .fluid import make_gas
from .model import Network

_DEBUG = bool(os.environ.get("MYFLOWNET_DEBUG"))
Q_REL = 1e-2     # momentum-chamber q convergence is measured against Q_REL * (largest boundary pressure)


class SolverError(RuntimeError):
    pass


@dataclass
class Solution:
    converged: bool = False
    iterations: int = 0
    message: str = ""
    history: list = field(default_factory=list)
    chambers: dict = field(default_factory=dict)
    elements: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    elapsed: float = 0.0
    state: dict = field(default_factory=dict)   # raw state for warm start


class _Problem:
    def __init__(self, net: Network):
        self.net = net
        msgs = net.validate()
        if msgs:
            raise SolverError("\n".join(msgs))
        self.gas = make_gas(net.settings.gas)
        self.ctx = Context(self.gas, net.rotor_omega())
        self.cids = list(net.chambers)
        self.internal = [c for c in self.cids if not net.chambers[c].is_boundary]
        self.bounds = [c for c in self.cids if net.chambers[c].is_boundary]
        self.eids = list(net.elements)
        self.el = {eid: net.elements[eid].build() for eid in self.eids}
        self.spec = net.elements
        self.pr_elems = [e for e in self.eids if self.el[e].category == "pressure"]
        self.ms_elems = [e for e in self.eids if self.el[e].category != "pressure"]
        self.idx = {c: i for i, c in enumerate(self.internal)}
        n_c = len(self.internal)
        self.eidx = {e: n_c + i for i, e in enumerate(self.pr_elems)}
        self.n = n_c + len(self.pr_elems)
        self.momentum = [c for c in self.internal if net.chambers[c].kind == "momentum"]
        self.is_mom = set(self.momentum)
        for e in self.pr_elems:
            s = self.spec[e]
            if net.chambers[s.a].is_boundary and net.chambers[s.b].is_boundary:
                raise SolverError(f"Pressure-type element '{s.name}' connects two boundaries; "
                                  "its flow would be undetermined.")
        om = self.ctx.rotor_omega
        self.ch_omega = {c: om.get(net.chambers[c].params["ref_rotor"], 0.0) for c in self.cids}
        # momentum chambers: through-flow dynamic pressure q = Pt,m - Ps and its direction
        self.q = {c: 0.0 for c in self.cids}
        self.phi = {c: 0.0 for c in self.cids}
        self.q_scale = 1.0

    # ------------------------------------------------------------------
    def _T0(self, c, Tt, K):
        """Stagnation temperature of the through-flow (swirl head removed)."""
        cp = self.gas.cp(Tt[c])
        vt = K[c] * self.ch_omega[c] * self.net.chambers[c].params["radius"]
        return max(Tt[c] - vt * vt / (2 * cp), 1.0), cp

    def vm_of(self, c, p, Tt, K, q=None):
        """Through-flow speed from the dynamic pressure q (isentropic)."""
        q = self.q[c] if q is None else q
        if q <= 0.0:
            return 0.0
        T0, cp = self._T0(c, Tt, K)
        g = self.gas.gamma(Tt[c])
        Ts = T0 / (1.0 + q / p[c]) ** ((g - 1.0) / g)
        return math.sqrt(max(2.0 * cp * (T0 - Ts), 0.0))

    def q_of(self, c, p, Tt, K, v):
        T0, cp = self._T0(c, Tt, K)
        g = self.gas.gamma(Tt[c])
        Ts = max(T0 - v * v / (2.0 * cp), 1e-3 * T0)
        return p[c] * ((T0 / Ts) ** (g / (g - 1.0)) - 1.0)

    def inflow_velocity(self, c, res, Tt, K):
        """Mass-averaged through-flow velocity of the jets entering momentum
        chamber c: |sum(m_e v_e)| / sum(m_e) and its direction, limited to M < 1."""
        msum = mx = my = 0.0
        for e in self.eids:
            s = self.spec[e]
            if c not in (s.a, s.b):
                continue
            r = res[e]
            m = r.mdot
            if (s.b == c and m > 0) or (s.a == c and m < 0):
                w = abs(m)
                ang = math.radians(r.phi_out)
                msum += w
                mx += w * r.vm_out * math.cos(ang)
                my += w * r.vm_out * math.sin(ang)
        if msum <= 0.0:
            return 0.0, self.phi[c]
        v = math.hypot(mx, my) / msum
        T0, cp = self._T0(c, Tt, K)
        g = self.gas.gamma(Tt[c])
        vmax = 0.99 * math.sqrt(2.0 * (g - 1.0) * cp * T0 / (g + 1.0))   # M = 1 from stagnation T
        phi = math.degrees(math.atan2(my, mx)) if v > 0 else self.phi[c]
        return min(v, vmax), phi

    def chamber_state(self, c, p, Tt, K):
        ch = self.net.chambers[c]
        vm = self.vm_of(c, p, Tt, K) if c in self.is_mom else 0.0
        return ChamberState(p=p[c], Tt=Tt[c], K=K[c], omega_ref=self.ch_omega[c],
                            r=ch.params["radius"], is_boundary=ch.is_boundary,
                            vm=vm, phi=self.phi[c])

    def boundary_static(self, c):
        ch = self.net.chambers[c]
        prm = ch.params
        Tt = prm["T"]
        if prm["p_type"] == "static":
            return prm["p"]
        vt = prm["K"] * self.ch_omega[c] * prm["radius"]
        cp = self.gas.cp(Tt)
        Ts = Tt - vt * vt / (2 * cp)
        g = self.gas.gamma(0.5 * (Ts + Tt))
        return prm["p"] * (Ts / Tt) ** (g / (g - 1.0))

    def eval_elem(self, e, p, Tt, K, mflow):
        s = self.spec[e]
        sa = self.chamber_state(s.a, p, Tt, K)
        sb = self.chamber_state(s.b, p, Tt, K)
        return self.el[e].evaluate(self.ctx, sa, sb, mflow.get(e))

    def eval_all(self, p, Tt, K, mflow):
        return {e: self.eval_elem(e, p, Tt, K, mflow) for e in self.eids}

    def residual(self, res, p, mflow, mscale):
        R = np.zeros(self.n)
        for e in self.eids:
            s = self.spec[e]
            m = res[e].mdot
            if s.a in self.idx:
                R[self.idx[s.a]] -= m
            if s.b in self.idx:
                R[self.idx[s.b]] += m
        R[: len(self.internal)] /= mscale
        for e in self.pr_elems:
            s = self.spec[e]
            R[self.eidx[e]] = math.log(p[s.b]) - math.log(p[s.a]) - res[e].log_pr
        return R


def _laplace_init(prob: _Problem, values_b: dict, user: dict) -> dict:
    """Graph-Laplacian interpolation of boundary values onto internal chambers."""
    internal = prob.internal
    n = len(internal)
    out = dict(values_b)
    if n == 0:
        return out
    idx = prob.idx
    A = np.zeros((n, n))
    b = np.zeros(n)
    for e in prob.eids:
        s = prob.spec[e]
        for u, v in ((s.a, s.b), (s.b, s.a)):
            if u in idx:
                A[idx[u], idx[u]] += 1.0
                if v in idx:
                    A[idx[u], idx[v]] -= 1.0
                else:
                    b[idx[u]] += values_b[v]
    try:
        x = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        x = np.linalg.lstsq(A, b, rcond=None)[0]
    for c in internal:
        out[c] = float(x[idx[c]]) if c not in user else user[c]
    return out


class _State:
    def __init__(self, p, Tt, K, mflow):
        self.p, self.Tt, self.K, self.mflow = p, Tt, K, mflow


def solve(net: Network, initial: dict | None = None, callback=None, stop=None,
          use_user_guess: bool = False) -> Solution:
    t0 = time.time()
    prob = _Problem(net)
    st = net.settings
    gas = prob.gas
    sol = Solution()

    # ---------------------------------------------------------- initial state
    p_b = {c: prob.boundary_static(c) for c in prob.bounds}
    T_b = {c: net.chambers[c].params["T"] for c in prob.bounds}
    user_p = {c: net.chambers[c].params["p"] for c in prob.internal} if use_user_guess else {}
    user_T = {c: net.chambers[c].params["T"] for c in prob.internal} if use_user_guess else {}
    p = _laplace_init(prob, p_b, user_p)
    Tt = _laplace_init(prob, T_b, user_T)
    K = {c: net.chambers[c].params["K"] for c in prob.cids}
    mflow = {e: 0.0 for e in prob.pr_elems}
    if initial:
        for c, v in (initial.get("p") or {}).items():
            if int(c) in prob.idx:
                p[int(c)] = v
        for c, v in (initial.get("Tt") or {}).items():
            if int(c) in prob.idx:
                Tt[int(c)] = v
        for c, v in (initial.get("K") or {}).items():
            if int(c) in prob.idx and net.chambers[int(c)].kind == "inertial":
                K[int(c)] = v
        for e, v in (initial.get("m") or {}).items():
            if int(e) in mflow:
                mflow[int(e)] = v
        for c, v in (initial.get("q") or {}).items():
            if int(c) in prob.is_mom:
                prob.q[int(c)] = v
                prob.phi[int(c)] = (initial.get("phi") or {}).get(c, 0.0)
    prob.q_scale = Q_REL * max(p_b.values())
    S = _State(p, Tt, K, mflow)
    budget = [st.max_iter]

    if not prob.momentum:
        res, converged = _newton(prob, S, st, sol, callback, stop, budget)
    else:
        # outer loop on the momentum-chamber dynamic pressures (lagged node velocity)
        relax = max(min(st.relax_V, 1.0), 0.05)
        last_dq = float("inf")
        converged = False
        for outer in range(200):
            res, inner_ok = _newton(prob, S, st, sol, callback, stop, budget)
            if sol.message == "Stopped by user" or budget[0] <= 0:
                break
            dq = dphi = 0.0
            targets = {}
            for c in prob.momentum:
                v, ph = prob.inflow_velocity(c, res, S.Tt, S.K)
                targets[c] = (prob.q_of(c, S.p, S.Tt, S.K, v), ph)
            for c, (qt, ph) in targets.items():
                dq = max(dq, abs(qt - prob.q[c]) / prob.q_scale)
                dphi = max(dphi, abs(ph - prob.phi[c]))
                prob.q[c] += relax * (qt - prob.q[c])
                prob.phi[c] = ph
            if sol.history:
                sol.history[-1]["vel"] = dq
            if inner_ok and dq < 1e-9 and dphi < 1e-6:
                converged = True
                break
            if dq > last_dq:               # oscillation: damp the outer update
                relax = max(0.5 * relax, 0.1)
            last_dq = dq
        res = prob.eval_all(S.p, S.Tt, S.K, S.mflow)

    it = st.max_iter - budget[0]
    if sol.message != "Stopped by user":
        sol.message = f"Converged in {it} iterations" if converged else f"Not converged after {it} iterations"
    sol.converged = converged
    sol.iterations = it
    _collect(prob, sol, res, S.p, S.Tt, S.K, S.mflow)
    sol.elapsed = time.time() - t0
    return sol


def _newton(prob: _Problem, S: _State, st, sol, callback, stop, budget):
    """Damped Newton on pressures (and pressure-type element flows) with energy
    and swirl updates after every accepted step.  Returns (results, converged)."""
    p, Tt, K, mflow = S.p, S.Tt, S.K, S.mflow
    gas = prob.gas
    inertial = [c for c in prob.internal if prob.net.chambers[c].kind == "inertial"]
    p_floor = 1e-3 * min(prob.boundary_static(c) for c in prob.bounds)
    dT_last, dK_last = float("inf"), float("inf")
    res = prob.eval_all(p, Tt, K, mflow)
    nm = len(prob.internal)
    npr = len(prob.pr_elems)
    while budget[0] > 0:
        if stop is not None and stop():
            sol.message = "Stopped by user"
            return res, False
        mscale = max([abs(r.mdot) for r in res.values()] + [1e-9])
        R = prob.residual(res, p, mflow, mscale)
        rm = float(np.max(np.abs(R[:nm]))) if nm else 0.0
        rp = float(np.max(np.abs(R[nm:nm + npr]))) if npr else 0.0
        if rm < st.tol_mass and rp < 1e-10 and dT_last < st.tol_T and dK_last < st.tol_K:
            return res, True
        budget[0] -= 1
        it = st.max_iter - budget[0]
        sol.history.append({"iter": it, "mass": rm, "pr": rp, "dT": dT_last, "dK": dK_last})
        if callback:
            callback(it, rm, rp, dT_last, dK_last)
        J = _jacobian(prob, res, p, Tt, K, mflow, mscale)
        try:
            dx = np.linalg.solve(J, -R)
            if not np.all(np.isfinite(dx)):
                raise np.linalg.LinAlgError
        except np.linalg.LinAlgError:
            dx = np.linalg.lstsq(J, -R, rcond=None)[0]
        # ------------------------------------------------ step limiting + line search
        lam = 1.0
        for c, i in prob.idx.items():
            if dx[i] != 0.0:
                lam = min(lam, st.max_dp_frac * p[c] / abs(dx[i]))
        phi0 = float(np.dot(R, R))
        p_old = dict(p)
        m_old = dict(mflow)
        accepted = None
        for _ls in range(14):
            for c, i in prob.idx.items():
                p[c] = max(p_old[c] + lam * dx[i], p_floor)
            for e, k in prob.eidx.items():
                mflow[e] = m_old[e] + lam * dx[k]
            res_t = prob.eval_all(p, Tt, K, mflow)
            R_t = prob.residual(res_t, p, mflow, mscale)
            phi = float(np.dot(R_t, R_t))
            if phi <= (1.0 - 0.1 * lam) * phi0 or phi < 1e-24:
                accepted = res_t
                break
            lam *= 0.5
        if accepted is None:
            accepted = res_t   # take the last (small) step anyway
        res = accepted
        if _DEBUG:
            print(f"it {it} lam={lam:.3g} phi0={phi0:.3e} phi={phi:.3e} "
                  f"p={ {c: round(float(p[c]), 1) for c in prob.idx} } q={ {c: round(prob.q[c], 1) for c in prob.momentum} }")
        # ------------------------------------------------ energy & swirl update
        dT_last, Tn = _update_energy(prob, res, Tt, gas, st.relax_T)
        Tt.update(Tn)
        dK_last = 0.0
        for c in inertial:
            om = prob.ch_omega[c]
            r = prob.net.chambers[c].params["radius"]
            msum = rvt = 0.0
            for e in prob.eids:
                s = prob.spec[e]
                m = res[e].mdot
                if (s.b == c and m > 0) or (s.a == c and m < 0):
                    msum += abs(m)
                    rvt += abs(m) * res[e].rvt_out
            if msum > 0 and om * r * r != 0:
                Knew = rvt / (msum * om * r * r)
                dK_last = max(dK_last, abs(Knew - K[c]))
                K[c] = Knew
        if dT_last > 0 or dK_last > 0:
            res = prob.eval_all(p, Tt, K, mflow)
    return res, False


def _jacobian(prob: _Problem, res, p, Tt, K, mflow, mscale):
    """Element-local finite-difference Jacobian: every element depends only on
    its two chambers (static pressures) and, for pressure-type elements, on its
    own mass flow."""
    J = np.zeros((prob.n, prob.n))
    for e in prob.eids:
        s = prob.spec[e]
        base = res[e]
        for c in (s.a, s.b):
            if c not in prob.idx:
                continue
            h = max(1e-7 * p[c], 1e-3)
            pc = p[c]
            p[c] = pc + h
            r2 = prob.eval_elem(e, p, Tt, K, mflow)
            p[c] = pc
            j = prob.idx[c]
            if e in prob.eidx:
                J[prob.eidx[e], j] += -(r2.log_pr - base.log_pr) / h
            else:
                dm = (r2.mdot - base.mdot) / h / mscale
                if s.a in prob.idx:
                    J[prob.idx[s.a], j] -= dm
                if s.b in prob.idx:
                    J[prob.idx[s.b], j] += dm
        if e in prob.eidx:
            k = prob.eidx[e]
            if s.a in prob.idx:
                J[k, prob.idx[s.a]] += -1.0 / p[s.a]
            if s.b in prob.idx:
                J[k, prob.idx[s.b]] += 1.0 / p[s.b]
            m0 = mflow[e]
            h = max(1e-6 * abs(m0), 1e-7 * mscale, 1e-12)
            mflow[e] = m0 + h
            r2 = prob.eval_elem(e, p, Tt, K, mflow)
            mflow[e] = m0
            J[k, k] += -(r2.log_pr - base.log_pr) / h
            if s.a in prob.idx:
                J[prob.idx[s.a], k] -= 1.0 / mscale
            if s.b in prob.idx:
                J[prob.idx[s.b], k] += 1.0 / mscale
    return J


def _update_energy(prob: _Problem, res, Tt, gas, relax):
    """Solve the total-enthalpy mixing equations of all internal chambers."""
    internal = prob.internal
    n = len(internal)
    if n == 0:
        return 0.0, Tt
    idx = prob.idx
    A = np.zeros((n, n))
    b = np.zeros(n)
    h = {c: gas.h(Tt[c]) for c in prob.cids}
    for c in internal:
        i = idx[c]
        b[i] += prob.net.chambers[c].params.get("heat_W", 0.0)
    for e in prob.eids:
        s = prob.spec[e]
        m = res[e].mdot
        if m == 0.0:
            continue
        up, dn = (s.a, s.b) if m > 0 else (s.b, s.a)
        if dn not in idx:
            continue
        ma = abs(m)
        dh = gas.h(res[e].Tt_out) - h[up]
        i = idx[dn]
        A[i, i] += ma
        b[i] += ma * dh
        if up in idx:
            A[i, idx[up]] -= ma
        else:
            b[i] += ma * h[up]
    for c in internal:
        i = idx[c]
        if A[i, i] <= 0.0:
            A[i, :] = 0.0
            A[i, i] = 1.0
            b[i] = h[c]
    try:
        x = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        x = np.linalg.lstsq(A, b, rcond=None)[0]
    dT = 0.0
    Tn = dict(Tt)
    for c in internal:
        Tnew = gas.T_from_h(float(x[idx[c]]), Tt[c])
        Tnew = Tt[c] + relax * (Tnew - Tt[c])
        dT = max(dT, abs(Tnew - Tt[c]))
        Tn[c] = Tnew
    return dT, Tn


def _py(v):
    """Convert numpy scalars to plain Python values (JSON friendly)."""
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v) if not isinstance(v, (bool, int)) or isinstance(v, np.integer) else v
    return v


def _collect(prob: _Problem, sol: Solution, res, p, Tt, K, mflow):
    net = prob.net
    gas = prob.gas
    # inflow-mixed arrival temperature at boundaries + net flows
    inflow = {c: [0.0, 0.0] for c in prob.cids}
    net_out = {c: 0.0 for c in prob.cids}
    for e in prob.eids:
        s = prob.spec[e]
        m = res[e].mdot
        net_out[s.a] += m
        net_out[s.b] -= m
        dn = s.b if m > 0 else s.a
        inflow[dn][0] += abs(m)
        inflow[dn][1] += abs(m) * gas.h(res[e].Tt_out)
    for c in prob.cids:
        ch = net.chambers[c]
        om = prob.ch_omega[c]
        r = ch.params["radius"]
        vt = K[c] * om * r
        vm = prob.vm_of(c, p, Tt, K) if c in prob.is_mom else 0.0
        cp = gas.cp(Tt[c])
        Ts = Tt[c] - (vt * vt + vm * vm) / (2 * cp)
        g = gas.gamma(0.5 * (Ts + Tt[c]))
        pt = p[c] * (Tt[c] / Ts) ** (g / (g - 1.0)) if Ts > 0 else p[c]
        d = {"name": ch.name, "kind": ch.kind, "p": p[c], "pt": pt, "Tt": Tt[c], "Ts": Ts,
             "K": K[c], "vtheta": vt, "rho": p[c] / (gas.R * Ts) if Ts > 0 else 0.0,
             "vm": vm, "phi": prob.phi[c] if vm > 0 else 0.0}
        if ch.is_boundary:
            d["flow_out"] = net_out[c]
            d["T_arrival"] = (gas.T_from_h(inflow[c][1] / inflow[c][0], Tt[c])
                              if inflow[c][0] > 0 else None)
        sol.chambers[c] = d
    for e in prob.eids:
        s = prob.spec[e]
        r = res[e]
        up, dn = (s.a, s.b) if r.mdot >= 0 else (s.b, s.a)
        d = {"name": s.name, "type": s.type, "mdot": float(r.mdot), "p_a": float(p[s.a]), "p_b": float(p[s.b]),
             "dp": float(p[s.a] - p[s.b]), "Tt_in": float(Tt[up]), "Tt_out": float(r.Tt_out),
             "choked": bool(r.choked), "outputs": {k: _py(v) for k, v in r.outputs.items()},
             "rvt_out": float(r.rvt_out)}
        if r.profile is not None:
            d["profile"] = r.profile
        el = prob.el[e]
        if hasattr(el, "profile") and callable(getattr(el, "profile")) and el.type_name == "pipe":
            try:
                sa = prob.chamber_state(s.a, p, Tt, K)
                sb = prob.chamber_state(s.b, p, Tt, K)
                prof = el.profile(prob.ctx, sa, sb, r)
                if prof:
                    d["profile"] = prof
            except Exception:  # pragma: no cover - plotting aid only
                pass
        if el.type_name == "cavity":
            sa = prob.chamber_state(s.a, p, Tt, K)
            sb = prob.chamber_state(s.b, p, Tt, K)
            rr = el.evaluate(prob.ctx, sa, sb, mflow.get(e), profile=True)
            if rr.profile:
                prof = dict(rr.profile)
                p_up = p[up]
                prof["p"] = [p_up * x for x in prof.pop("p_rel")]
                d["profile"] = prof
        sol.elements[e] = d
    sol.state = {"p": {c: p[c] for c in prob.cids}, "Tt": dict(Tt), "K": dict(K), "m": dict(mflow),
                 "q": dict(prob.q), "phi": dict(prob.phi)}
    # mass-conservation check
    tot = sum(v["flow_out"] for v in sol.chambers.values() if v["kind"] == "boundary")
    scale = max([abs(v["mdot"]) for v in sol.elements.values()] + [1e-12])
    if abs(tot) > 1e-6 * scale:
        sol.warnings.append(f"Boundary flows do not balance: Σ = {tot:.3e} kg/s")
    for e, d in sol.elements.items():
        if d["choked"]:
            sol.warnings.append(f"Element '{d['name']}' is choked.")
