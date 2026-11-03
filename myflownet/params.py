"""Parameter specification used by elements and chambers.

A ParamSpec describes one user input: its key, label, unit kind, default and
help text.  The GUI builds property editors from these specs; the solver reads
values in SI units.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParamSpec:
    key: str
    label: str
    default: Any
    unit: str = "none"          # unit kind, see units.py
    kind: str = "float"         # float | int | choice | bool | rotor
    choices: tuple = ()         # for kind == "choice": tuple of (value, label)
    tip: str = ""
    group: str = "General"
    minimum: float | None = None
    maximum: float | None = None
    visible_if: tuple | None = None   # (key, value or tuple of values)

    def coerce(self, value: Any) -> Any:
        if self.kind in ("float",):
            v = float(value)
            if self.minimum is not None and v < self.minimum:
                raise ValueError(f"{self.label} must be >= {self.minimum}")
            if self.maximum is not None and v > self.maximum:
                raise ValueError(f"{self.label} must be <= {self.maximum}")
            return v
        if self.kind in ("int", "rotor"):
            v = int(round(float(value)))
            if self.minimum is not None and v < self.minimum:
                raise ValueError(f"{self.label} must be >= {int(self.minimum)}")
            return v
        if self.kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if self.kind == "choice":
            allowed = [c[0] for c in self.choices]
            if value not in allowed:
                raise ValueError(f"{self.label}: '{value}' not in {allowed}")
            return value
        return value

    def is_visible(self, values: dict) -> bool:
        if not self.visible_if:
            return True
        k, v = self.visible_if
        cur = values.get(k)
        if isinstance(v, tuple):
            return cur in v
        return cur == v


def defaults(specs: list[ParamSpec]) -> dict:
    return {s.key: s.default for s in specs}


def merge_params(specs: list[ParamSpec], given: dict | None) -> dict:
    out = defaults(specs)
    if given:
        byk = {s.key: s for s in specs}
        for k, v in given.items():
            if k in byk:
                out[k] = byk[k].coerce(v)
    return out
