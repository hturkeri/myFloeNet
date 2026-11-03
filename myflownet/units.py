"""Display-unit handling.  The solver works in SI only; the GUI converts.

Each unit kind has a set of selectable units: name -> (scale, offset) with
SI = value * scale + offset.
"""
from __future__ import annotations

UNITS: dict[str, dict[str, tuple[float, float]]] = {
    "pressure": {"bar": (1e5, 0.0), "kPa": (1e3, 0.0), "Pa": (1.0, 0.0), "MPa": (1e6, 0.0),
                 "psi": (6894.757293168, 0.0)},
    "temperature": {"K": (1.0, 0.0), "°C": (1.0, 273.15), "°F": (5.0 / 9.0, 255.3722222222)},
    "temperature_diff": {"K": (1.0, 0.0)},
    "length": {"mm": (1e-3, 0.0), "m": (1.0, 0.0), "in": (0.0254, 0.0)},
    "small_length": {"µm": (1e-6, 0.0), "mm": (1e-3, 0.0)},
    "area": {"mm²": (1e-6, 0.0), "m²": (1.0, 0.0), "in²": (0.00064516, 0.0)},
    "massflow": {"kg/s": (1.0, 0.0), "g/s": (1e-3, 0.0), "lbm/s": (0.45359237, 0.0)},
    "rpm": {"rpm": (1.0, 0.0)},
    "angle": {"deg": (1.0, 0.0)},
    "power": {"W": (1.0, 0.0), "kW": (1e3, 0.0)},
    "velocity": {"m/s": (1.0, 0.0)},
    "none": {"-": (1.0, 0.0)},
    "torque": {"N·m": (1.0, 0.0)},
    "density": {"kg/m³": (1.0, 0.0)},
}

DEFAULT_DISPLAY = {
    "pressure": "bar",
    "temperature": "K",
    "temperature_diff": "K",
    "length": "mm",
    "small_length": "µm",
    "area": "mm²",
    "massflow": "kg/s",
    "rpm": "rpm",
    "angle": "deg",
    "power": "W",
    "velocity": "m/s",
    "none": "-",
    "torque": "N·m",
    "density": "kg/m³",
}


class UnitSystem:
    def __init__(self, choice: dict | None = None):
        self.choice = dict(DEFAULT_DISPLAY)
        if choice:
            self.choice.update({k: v for k, v in choice.items() if k in UNITS and v in UNITS[k]})

    def label(self, kind: str) -> str:
        return self.choice.get(kind, "-") if kind in UNITS else ""

    def to_display(self, kind: str, si: float) -> float:
        if kind not in UNITS:
            return si
        scale, off = UNITS[kind][self.choice[kind]]
        return (si - off) / scale

    def to_si(self, kind: str, disp: float) -> float:
        if kind not in UNITS:
            return disp
        scale, off = UNITS[kind][self.choice[kind]]
        return disp * scale + off


def fmt(value: float, digits: int = 5) -> str:
    """Compact engineering formatting."""
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == 0.0:
        return "0"
    a = abs(v)
    if 1e-3 <= a < 1e6:
        s = f"{v:.{digits}g}"
    else:
        s = f"{v:.{max(digits - 2, 2)}e}"
    return s
