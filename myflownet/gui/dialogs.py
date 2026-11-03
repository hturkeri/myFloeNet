"""Model settings dialog (rotors, gas, solver, display units) and the theory viewer."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
                               QTextBrowser, QVBoxLayout, QWidget)

from ..model import Rotor
from ..units import UNITS


class SettingsDialog(QDialog):
    def __init__(self, parent, net, units_choice: dict):
        super().__init__(parent)
        self.setWindowTitle("Model settings")
        self.resize(560, 440)
        self.net = net
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # rotors ---------------------------------------------------------
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("Rotors are referenced by elements (rotating holes, pipes, seals, cavities) and by "
                      "chambers as the reference speed of the swirl ratio K.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.rt = QTableWidget(0, 3)
        self.rt.setHorizontalHeaderLabels(["Id", "Name", "Speed [rpm]"])
        self.rt.verticalHeader().setVisible(False)
        self.rt.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for r in net.rotors:
            self._add_rotor_row(r.id, r.name, r.rpm)
        v.addWidget(self.rt)
        hb = QHBoxLayout()
        b1 = QPushButton("Add rotor")
        b2 = QPushButton("Remove selected")
        b1.clicked.connect(lambda: self._add_rotor_row(self._next_rotor_id(), "Rotor", 0.0))
        b2.clicked.connect(lambda: self.rt.removeRow(self.rt.currentRow()) if self.rt.currentRow() >= 0 else None)
        hb.addWidget(b1)
        hb.addWidget(b2)
        hb.addStretch(1)
        v.addLayout(hb)
        tabs.addTab(w, "Rotors")

        # gas ------------------------------------------------------------
        w = QWidget()
        f = QFormLayout(w)
        g = net.settings.gas
        self.gas_model = QComboBox()
        self.gas_model.addItem("Dry air, cp(T) from NASA polynomials", "air")
        self.gas_model.addItem("Calorically perfect gas (constant cp)", "ideal_constant")
        self.gas_model.setCurrentIndex(0 if g.get("model", "air") == "air" else 1)
        f.addRow("Gas model", self.gas_model)
        self.cp = QLineEdit(str(g.get("cp", 1004.5)))
        self.R = QLineEdit(str(g.get("R", 287.05)))
        self.mu = QLineEdit(str(g.get("mu", 1.8e-5)))
        self.Pr = QLineEdit(str(g.get("Pr", 0.71)))
        f.addRow("cp [J/kg/K]", self.cp)
        f.addRow("R [J/kg/K]", self.R)
        f.addRow("Viscosity [Pa·s]", self.mu)
        f.addRow("Prandtl number", self.Pr)
        self.gas_model.currentIndexChanged.connect(self._gas_vis)
        self._gas_vis()
        tabs.addTab(w, "Gas")

        # solver ---------------------------------------------------------
        w = QWidget()
        f = QFormLayout(w)
        s = net.settings
        self.max_iter = QLineEdit(str(s.max_iter))
        self.tol_mass = QLineEdit(str(s.tol_mass))
        self.tol_T = QLineEdit(str(s.tol_T))
        self.tol_K = QLineEdit(str(s.tol_K))
        self.max_dp = QLineEdit(str(s.max_dp_frac))
        f.addRow("Maximum iterations", self.max_iter)
        f.addRow("Mass imbalance tolerance (relative)", self.tol_mass)
        f.addRow("Temperature change tolerance [K]", self.tol_T)
        f.addRow("Swirl change tolerance", self.tol_K)
        f.addRow("Max. pressure change per step (fraction)", self.max_dp)
        tabs.addTab(w, "Solver")

        # units ----------------------------------------------------------
        w = QWidget()
        f = QFormLayout(w)
        self.unit_boxes = {}
        names = {"pressure": "Pressure", "temperature": "Temperature", "length": "Length", "area": "Area",
                 "massflow": "Mass flow", "power": "Power"}
        for k, lab in names.items():
            cb = QComboBox()
            for u in UNITS[k]:
                cb.addItem(u, u)
            cur = units_choice.get(k)
            if cur in UNITS[k]:
                cb.setCurrentText(cur)
            self.unit_boxes[k] = cb
            f.addRow(lab, cb)
        tabs.addTab(w, "Units")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setProperty("primary", True)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _gas_vis(self):
        on = self.gas_model.currentData() == "ideal_constant"
        for wdg in (self.cp, self.R, self.mu, self.Pr):
            wdg.setEnabled(on)

    def _next_rotor_id(self):
        ids = [int(self.rt.item(r, 0).text()) for r in range(self.rt.rowCount()) if self.rt.item(r, 0)]
        return max(ids + [0]) + 1

    def _add_rotor_row(self, rid, name, rpm):
        r = self.rt.rowCount()
        self.rt.insertRow(r)
        it = QTableWidgetItem(str(rid))
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
        self.rt.setItem(r, 0, it)
        self.rt.setItem(r, 1, QTableWidgetItem(name))
        self.rt.setItem(r, 2, QTableWidgetItem(f"{rpm:g}"))

    def values(self):
        rotors = []
        for r in range(self.rt.rowCount()):
            rid = int(self.rt.item(r, 0).text())
            name = self.rt.item(r, 1).text() if self.rt.item(r, 1) else f"Rotor {rid}"
            rpm = float((self.rt.item(r, 2).text() if self.rt.item(r, 2) else "0").replace(",", "."))
            rotors.append(Rotor(rid, name, rpm))
        gas = {"model": self.gas_model.currentData()}
        if gas["model"] == "ideal_constant":
            gas.update(cp=float(self.cp.text()), R=float(self.R.text()), mu=float(self.mu.text()),
                       Pr=float(self.Pr.text()))
        solver = dict(max_iter=int(float(self.max_iter.text())), tol_mass=float(self.tol_mass.text()),
                      tol_T=float(self.tol_T.text()), tol_K=float(self.tol_K.text()),
                      max_dp_frac=float(self.max_dp.text()))
        units = {k: cb.currentData() for k, cb in self.unit_boxes.items()}
        return rotors, gas, solver, units


class TheoryDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("myFlowNet theory guide")
        self.resize(860, 760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(os.path.join(here, "..", "..", "docs", "THEORY.md"))
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                tb.setMarkdown(f.read())
        else:
            tb.setPlainText("docs/THEORY.md was not found next to the program.")
        tb.document().setDocumentMargin(24)
        lay.addWidget(tb)
