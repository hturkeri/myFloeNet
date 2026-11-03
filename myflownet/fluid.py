"""Gas property models for myFlowNet.

All quantities are SI: T [K], p [Pa], cp/h [J/kg, J/kg/K], mu [Pa s], k [W/m/K].

Two models are provided:

* ``AirNASA``  - dry air as an ideal mixture of N2/O2/Ar with temperature
  dependent cp(T) from NASA 7-coefficient polynomials (GRI-Mech 3.0 data,
  valid 200-5000 K). Viscosity and conductivity follow Sutherland's law.
* ``IdealGasConstant`` - calorically perfect gas (constant cp, gamma), useful
  for validation against closed-form solutions.

The enthalpy is the *sensible* enthalpy measured from 298.15 K and is built by
integrating cp so that the two NASA temperature ranges join continuously
without using the a6/a7 formation constants.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

R_UNIVERSAL = 8314.462618  # J/(kmol K)

# NASA 7-coefficient polynomials (a1..a5) for cp/R; [low (200-1000 K), high (1000-5000 K)]
_NASA = {
    "N2": (
        (3.298677, 1.4082404e-3, -3.963222e-6, 5.641515e-9, -2.444854e-12),
        (2.92664, 1.4879768e-3, -5.68476e-7, 1.0097038e-10, -6.753351e-15),
        28.0134,
    ),
    "O2": (
        (3.78245636, -2.99673416e-3, 9.84730201e-6, -9.68129509e-9, 3.24372837e-12),
        (3.28253784, 1.48308754e-3, -7.57966669e-7, 2.09470555e-10, -2.16717794e-14),
        31.9988,
    ),
    "AR": (
        (2.5, 0.0, 0.0, 0.0, 0.0),
        (2.5, 0.0, 0.0, 0.0, 0.0),
        39.948,
    ),
}
_AIR_X = {"N2": 0.78084, "O2": 0.20946, "AR": 0.00934}
_T_MID = 1000.0
_T_REF = 298.15


def _mix_coeffs(x: dict):
    tot = sum(x.values())
    low = [0.0] * 5
    high = [0.0] * 5
    mw = 0.0
    for sp, xi in x.items():
        lo, hi, w = _NASA[sp]
        xi /= tot
        mw += xi * w
        for i in range(5):
            low[i] += xi * lo[i]
            high[i] += xi * hi[i]
    return tuple(low), tuple(high), mw


def _cp_over_R(a, T):
    return a[0] + T * (a[1] + T * (a[2] + T * (a[3] + T * a[4])))


def _h_over_R(a, T):
    """Integral of cp/R dT (without constant)."""
    return T * (a[0] + T * (a[1] / 2 + T * (a[2] / 3 + T * (a[3] / 4 + T * a[4] / 5))))


class GasModel:
    """Interface for gas models."""

    name = "gas"
    R: float = 287.05

    def cp(self, T: float) -> float:  # pragma: no cover - interface
        raise NotImplementedError

    def h(self, T: float) -> float:  # pragma: no cover - interface
        raise NotImplementedError

    def mu(self, T: float) -> float:  # pragma: no cover - interface
        raise NotImplementedError

    def k(self, T: float) -> float:  # pragma: no cover - interface
        raise NotImplementedError

    # ---- derived -----------------------------------------------------
    def gamma(self, T: float) -> float:
        cp = self.cp(T)
        return cp / (cp - self.R)

    def T_from_h(self, h: float, T_guess: float = 500.0) -> float:
        T = max(T_guess, 50.0)
        for _ in range(50):
            f = self.h(T) - h
            dT = f / self.cp(T)
            T -= dT
            if T < 20.0:
                T = 20.0
            if abs(dT) < 1e-10 * max(T, 1.0):
                break
        return T

    def Pr(self, T: float) -> float:
        return self.cp(T) * self.mu(T) / self.k(T)

    def to_dict(self) -> dict:
        return {"model": self.name}


class AirNASA(GasModel):
    name = "air"

    def __init__(self):
        self._low, self._high, self.MW = _mix_coeffs(_AIR_X)
        self.R = R_UNIVERSAL / self.MW
        self._h_low_mid = _h_over_R(self._low, _T_MID) - _h_over_R(self._low, _T_REF)
        self._h_high_mid = _h_over_R(self._high, _T_MID)

    def cp(self, T: float) -> float:
        T = min(max(T, 150.0), 5000.0)
        a = self._low if T <= _T_MID else self._high
        return self.R * _cp_over_R(a, T)

    def h(self, T: float) -> float:
        if T <= _T_MID:
            Tc = max(T, 150.0)
            val = _h_over_R(self._low, Tc) - _h_over_R(self._low, _T_REF)
            if T < 150.0:  # linear extrapolation
                val += (T - 150.0) * _cp_over_R(self._low, 150.0)
            return self.R * val
        return self.R * (self._h_low_mid + _h_over_R(self._high, T) - self._h_high_mid)

    def mu(self, T: float) -> float:
        # Sutherland: mu0=1.716e-5 Pa s at 273.15 K, S=110.4 K
        return 1.716e-5 * (T / 273.15) ** 1.5 * (273.15 + 110.4) / (T + 110.4)

    def k(self, T: float) -> float:
        # Sutherland for conductivity: k0=0.0241 W/mK at 273.15 K, S=194 K
        return 0.0241 * (T / 273.15) ** 1.5 * (273.15 + 194.0) / (T + 194.0)


@dataclass
class IdealGasConstant(GasModel):
    cp_const: float = 1004.5
    R_const: float = 287.05
    mu_const: float = 1.8e-5
    Pr_const: float = 0.71

    name = "ideal_constant"

    def __post_init__(self):
        self.R = self.R_const

    def cp(self, T: float) -> float:
        return self.cp_const

    def h(self, T: float) -> float:
        return self.cp_const * (T - _T_REF)

    def T_from_h(self, h: float, T_guess: float = 500.0) -> float:
        return h / self.cp_const + _T_REF

    def mu(self, T: float) -> float:
        return self.mu_const

    def k(self, T: float) -> float:
        return self.cp_const * self.mu_const / self.Pr_const

    def to_dict(self) -> dict:
        return {"model": self.name, "cp": self.cp_const, "R": self.R_const,
                "mu": self.mu_const, "Pr": self.Pr_const}


def make_gas(spec: dict | None) -> GasModel:
    spec = spec or {"model": "air"}
    model = spec.get("model", "air")
    if model == "air":
        return AirNASA()
    if model == "ideal_constant":
        return IdealGasConstant(cp_const=float(spec.get("cp", 1004.5)),
                                R_const=float(spec.get("R", 287.05)),
                                mu_const=float(spec.get("mu", 1.8e-5)),
                                Pr_const=float(spec.get("Pr", 0.71)))
    raise ValueError(f"Unknown gas model '{model}'")


def speed_of_sound(gas: GasModel, T: float) -> float:
    return math.sqrt(gas.gamma(T) * gas.R * T)
