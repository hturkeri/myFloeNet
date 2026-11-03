"""Network data model and JSON (de)serialisation."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass, field

from .elements import REGISTRY, make_element
from .params import ParamSpec, merge_params

FORMAT = "myflownet"
VERSION = 1

CHAMBER_KINDS = (("boundary", "Boundary"), ("plenum", "Plenum"), ("momentum", "Momentum (through-flow)"),
                 ("inertial", "Inertial (swirl)"))

CHAMBER_PARAMS = [
    ParamSpec("kind", "Type", "plenum", kind="choice", choices=CHAMBER_KINDS, group="Chamber",
              tip="Boundary: fixed p, T, swirl.  Plenum: no through-flow velocity, swirl fixed by user.  "
                  "Momentum: carries the mixed through-flow velocity of its inflows; downstream elements "
                  "recover its dynamic head as cos²θ.  Inertial: swirl from angular-momentum mixing."),
    ParamSpec("p", "Pressure", 1.0e5, unit="pressure", minimum=1.0, group="State",
              tip="Imposed boundary pressure (total or static).", visible_if=("kind", "boundary")),
    ParamSpec("p_type", "Pressure type", "total", kind="choice",
              choices=(("total", "Total"), ("static", "Static")), group="State",
              visible_if=("kind", "boundary")),
    ParamSpec("T", "Total temperature", 300.0, unit="temperature", minimum=1.0, group="State",
              tip="Imposed total temperature of flow leaving the boundary.", visible_if=("kind", "boundary")),
    ParamSpec("K", "Swirl ratio K", 0.0, group="Swirl",
              tip="V_theta = K · Ω_ref · r.  Inertial chambers: initial guess."),
    ParamSpec("ref_rotor", "Reference rotor", 1, kind="rotor", group="Swirl"),
    ParamSpec("radius", "Reference radius", 0.0, unit="length", minimum=0.0, group="Swirl",
              tip="Radius at which the chamber swirl / static pressure is defined."),
    ParamSpec("heat_W", "Heat input", 0.0, unit="power", group="Energy",
              visible_if=("kind", ("plenum", "momentum", "inertial"))),
]


def portable_path(file: str, base_dir: str) -> str:
    """Path of `file` relative to `base_dir` (forward slashes) when it is close by, else absolute."""
    try:
        rel = os.path.relpath(os.path.abspath(file), base_dir)
    except ValueError:                      # other drive (Windows)
        return os.path.abspath(file)
    if rel.replace("\\", "/").startswith("../../.."):
        return os.path.abspath(file)
    return rel.replace("\\", "/")


@dataclass
class Rotor:
    id: int
    name: str = "Rotor"
    rpm: float = 0.0


@dataclass
class Chamber:
    id: int
    name: str = ""
    x: float = 0.0
    y: float = 0.0
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        self.params = merge_params(CHAMBER_PARAMS, self.params)
        if not self.name:
            self.name = f"C{self.id}"

    @property
    def kind(self) -> str:
        return self.params["kind"]

    @property
    def is_boundary(self) -> bool:
        return self.params["kind"] == "boundary"


@dataclass
class ElementSpec:
    id: int
    type: str
    a: int
    b: int
    name: str = ""
    params: dict = field(default_factory=dict)
    bend: float = 0.0   # GUI curvature of the connection

    def __post_init__(self):
        cls = REGISTRY[self.type]
        self.params = merge_params(cls.PARAMS, self.params)
        if not self.name:
            self.name = f"E{self.id}"

    def build(self):
        return make_element(self.type, self.params)


@dataclass
class SolverSettings:
    max_iter: int = 300
    tol_mass: float = 1e-9        # relative mass imbalance
    tol_T: float = 1e-6           # K
    tol_K: float = 1e-7
    max_dp_frac: float = 0.3      # max relative pressure change per Newton step
    relax_T: float = 1.0
    relax_V: float = 1.0          # relaxation of the momentum-chamber dynamic-pressure update
    gas: dict = field(default_factory=lambda: {"model": "air"})


class Network:
    def __init__(self, title: str = "Untitled"):
        self.title = title
        self.description = ""
        self.rotors: list[Rotor] = [Rotor(1, "HP Rotor", 10000.0)]
        self.chambers: dict[int, Chamber] = {}
        self.elements: dict[int, ElementSpec] = {}
        self.settings = SolverSettings()
        self.display_units: dict = {}
        self.background: dict | None = None   # background CAD geometry (file, view, placement)

    # ---------------------------------------------------------------- ids
    def _next_id(self, d: dict) -> int:
        return (max(d) + 1) if d else 1

    def add_chamber(self, kind: str = "plenum", name: str = "", x: float = 0.0, y: float = 0.0,
                    cid: int | None = None, **params) -> Chamber:
        cid = cid if cid is not None else self._next_id(self.chambers)
        params = dict(params)
        params["kind"] = kind
        ch = Chamber(cid, name, x, y, params)
        self.chambers[cid] = ch
        return ch

    def add_element(self, etype: str, a: int, b: int, name: str = "", eid: int | None = None,
                    **params) -> ElementSpec:
        if a not in self.chambers or b not in self.chambers:
            raise KeyError("Element ports must reference existing chambers")
        if a == b:
            raise ValueError("Element must connect two different chambers")
        eid = eid if eid is not None else self._next_id(self.elements)
        el = ElementSpec(eid, etype, a, b, name, params)
        self.elements[eid] = el
        return el

    def remove_chamber(self, cid: int):
        self.chambers.pop(cid, None)
        for eid in [e.id for e in self.elements.values() if cid in (e.a, e.b)]:
            self.elements.pop(eid)

    def remove_element(self, eid: int):
        self.elements.pop(eid, None)

    def rotor_omega(self) -> dict:
        import math
        return {r.id: r.rpm * 2.0 * math.pi / 60.0 for r in self.rotors}

    # ---------------------------------------------------------------- checks
    def validate(self) -> list[str]:
        """Return a list of problems (empty if OK)."""
        msgs = []
        if not any(c.is_boundary for c in self.chambers.values()):
            msgs.append("The network needs at least one boundary chamber.")
        # connectivity to a boundary
        adj = {cid: set() for cid in self.chambers}
        for e in self.elements.values():
            adj[e.a].add(e.b)
            adj[e.b].add(e.a)
        seen = set()
        stack = [c.id for c in self.chambers.values() if c.is_boundary]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            stack.extend(adj[c] - seen)
        for cid, ch in self.chambers.items():
            if cid not in seen:
                msgs.append(f"Chamber '{ch.name}' is not connected to any boundary.")
            elif not adj[cid]:
                msgs.append(f"Chamber '{ch.name}' has no elements.")
        rotor_ids = {r.id for r in self.rotors}
        for e in self.elements.values():
            rid = e.params.get("rotor", 0)
            if rid and rid not in rotor_ids:
                msgs.append(f"Element '{e.name}' references undefined rotor {rid}.")
        return msgs

    # ---------------------------------------------------------------- IO
    def to_dict(self) -> dict:
        return {
            "format": FORMAT, "version": VERSION,
            "title": self.title, "description": self.description,
            "settings": asdict(self.settings),
            "display_units": self.display_units,
            **({"background": copy.deepcopy(self.background)} if self.background else {}),
            "rotors": [asdict(r) for r in self.rotors],
            "chambers": [{"id": c.id, "name": c.name, "x": c.x, "y": c.y, "params": dict(c.params)}
                         for c in self.chambers.values()],
            "elements": [{"id": e.id, "type": e.type, "name": e.name, "a": e.a, "b": e.b,
                          "bend": e.bend, "params": dict(e.params)} for e in self.elements.values()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Network":
        if d.get("format") not in (FORMAT, None):
            raise ValueError("Not a myFlowNet model file")
        net = cls(d.get("title", "Untitled"))
        net.description = d.get("description", "")
        s = d.get("settings", {})
        net.settings = SolverSettings(**{k: v for k, v in s.items() if k in SolverSettings.__dataclass_fields__})
        net.display_units = d.get("display_units", {})
        net.background = copy.deepcopy(d.get("background")) or None
        net.rotors = [Rotor(**r) for r in d.get("rotors", [])]
        for c in d.get("chambers", []):
            net.chambers[c["id"]] = Chamber(c["id"], c.get("name", ""), c.get("x", 0.0), c.get("y", 0.0),
                                            c.get("params", {}))
        for e in d.get("elements", []):
            net.elements[e["id"]] = ElementSpec(e["id"], e["type"], e["a"], e["b"], e.get("name", ""),
                                                e.get("params", {}), e.get("bend", 0.0))
        return net

    def save(self, path: str):
        d = self.to_dict()
        bg = d.get("background")
        if bg and bg.get("file"):
            bg["file"] = portable_path(bg["file"], os.path.dirname(os.path.abspath(path)))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "Network":
        with open(path, "r", encoding="utf-8") as f:
            net = cls.from_dict(json.load(f))
        bg = net.background
        if bg and bg.get("file") and not os.path.isabs(bg["file"]):
            bg["file"] = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), bg["file"]))
        return net

    def copy(self) -> "Network":
        return Network.from_dict(copy.deepcopy(self.to_dict()))
