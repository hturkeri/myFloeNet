"""Contour colouring of the model (Post-Processing → Colorize) and its legend settings."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                               QSpinBox, QVBoxLayout)

from .theme import Rainbow, ramp

# key: (entity, label, value function(net, sol, oid) -> float | None, unit kind)
QUANTITIES = {
    "none": ("", "No colouring", None, "none"),
    "ch_p": ("chamber", "Chambers – static pressure", lambda net, s, i: s.chambers[i]["p"], "pressure"),
    "ch_pt": ("chamber", "Chambers – total pressure", lambda net, s, i: s.chambers[i]["pt"], "pressure"),
    "ch_Tt": ("chamber", "Chambers – total temperature", lambda net, s, i: s.chambers[i]["Tt"], "temperature"),
    "ch_K": ("chamber", "Chambers – swirl ratio K", lambda net, s, i: s.chambers[i]["K"], "none"),
    "ch_rho": ("chamber", "Chambers – density", lambda net, s, i: s.chambers[i]["rho"], "density"),
    "ch_r": ("chamber", "Chambers – reference radius (input)",
             lambda net, s, i: net.chambers[i].params.get("radius", 0.0), "length"),
    "el_m": ("element", "Elements – mass flow", lambda net, s, i: abs(s.elements[i]["mdot"]), "massflow"),
    "el_dp": ("element", "Elements – static Δp", lambda net, s, i: s.elements[i]["dp"], "pressure"),
    "el_Tt": ("element", "Elements – exit total temperature", lambda net, s, i: s.elements[i]["Tt_out"],
              "temperature"),
    "el_M": ("element", "Elements – Mach number",
             lambda net, s, i: next((s.elements[i]["outputs"][k] for k in ("Mach exit", "Mach", "Mach out")
                                     if k in s.elements[i]["outputs"]), None), "none"),
    "el_D": ("element", "Elements – diameter (input)",
             lambda net, s, i: net.elements[i].params.get("diameter"), "length"),
}
INPUT_QUANTITIES = {"ch_r", "el_D"}


@dataclass
class ContourSettings:
    quantity: str = "ch_p"
    levels: int = 10             # 2..32 discrete bands; 0 = continuous
    colormap: str = "rainbow"    # rainbow | sequential
    fixed: bool = False          # fixed scale (vmin / vmax) instead of the data range
    vmin: float = 0.0
    vmax: float = 1.0
    reverse: bool = False
    numfmt: str = "fixed"        # fixed | scientific
    precision: int = 4
    show_minmax: bool = True

    @classmethod
    def from_dict(cls, d):
        out = cls()
        for k, v in (d or {}).items():
            if k in cls.__dataclass_fields__:
                setattr(out, k, type(getattr(out, k))(v))
        return out

    def to_dict(self):
        return asdict(self)


def colour_fn(cs: ContourSettings, dark_canvas: bool, kind_hint: str = "pressure"):
    if cs.colormap == "rainbow":
        rb = Rainbow(cs.levels if cs.levels >= 2 else 0, cs.reverse)
        return rb.color
    rp = ramp(kind_hint, dark_canvas)
    n = cs.levels

    def f(t):
        t = min(max(t, 0.0), 1.0)
        if n >= 2:
            t = min(int(t * n), n - 1) / (n - 1)
        return rp.color(1.0 - t if cs.reverse else t)
    return f


def format_value(v: float, cs: ContourSettings) -> str:
    if cs.numfmt == "scientific":
        return f"{v:.{max(cs.precision - 1, 0)}e}"
    if v == 0 or not math.isfinite(v):
        return "0"
    digits = max(0, cs.precision - 1 - int(math.floor(math.log10(abs(v))))) if abs(v) < 1e6 else 0
    return f"{v:.{min(digits, 12)}f}"


class LegendDialog(QDialog):
    """Contour / legend settings: quantity, levels, scale, colours and number format."""

    def __init__(self, parent, cs: ContourSettings, unit_label: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Contour and legend settings")
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.q = QComboBox()
        for k, (_, lab, _, _) in QUANTITIES.items():
            self.q.addItem(lab, k)
        self.q.setCurrentIndex(max(self.q.findData(cs.quantity), 0))
        f.addRow("Colorize", self.q)
        self.levels = QSpinBox()
        self.levels.setRange(0, 32)
        self.levels.setSpecialValueText("Continuous")
        self.levels.setValue(cs.levels)
        f.addRow("Number of levels", self.levels)
        self.cmap = QComboBox()
        self.cmap.addItem("Rainbow (blue → red)", "rainbow")
        self.cmap.addItem("Single hue", "sequential")
        self.cmap.setCurrentIndex(max(self.cmap.findData(cs.colormap), 0))
        f.addRow("Colours", self.cmap)
        self.reverse = QCheckBox("Reverse colours")
        self.reverse.setChecked(cs.reverse)
        f.addRow("", self.reverse)
        self.fixed = QComboBox()
        self.fixed.addItem("Dynamic (range of the data)", False)
        self.fixed.addItem("Fixed (legend min / max)", True)
        self.fixed.setCurrentIndex(1 if cs.fixed else 0)
        f.addRow("Scale", self.fixed)
        self.vmin = QLineEdit(f"{cs.vmin:g}")
        self.vmax = QLineEdit(f"{cs.vmax:g}")
        f.addRow(f"Legend min {unit_label}", self.vmin)
        f.addRow(f"Legend max {unit_label}", self.vmax)
        self.numfmt = QComboBox()
        self.numfmt.addItem("Fixed", "fixed")
        self.numfmt.addItem("Scientific", "scientific")
        self.numfmt.setCurrentIndex(max(self.numfmt.findData(cs.numfmt), 0))
        f.addRow("Numeric format", self.numfmt)
        self.prec = QSpinBox()
        self.prec.setRange(1, 12)
        self.prec.setValue(cs.precision)
        f.addRow("Significant digits", self.prec)
        self.minmax = QCheckBox("Mark minimum and maximum on the model")
        self.minmax.setChecked(cs.show_minmax)
        f.addRow("", self.minmax)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> ContourSettings:
        def num(ed, default):
            try:
                return float(ed.text().replace(",", "."))
            except ValueError:
                return default
        return ContourSettings(self.q.currentData(), self.levels.value(), self.cmap.currentData(),
                               bool(self.fixed.currentData()), num(self.vmin, 0.0), num(self.vmax, 1.0),
                               self.reverse.isChecked(), self.numfmt.currentData(), self.prec.value(),
                               self.minmax.isChecked())
