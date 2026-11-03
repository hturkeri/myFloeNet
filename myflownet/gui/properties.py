"""Property editor: a Parameter | Value | Unit grid for the selection.

* Required inputs are shown in blue.  Less used inputs appear with *Show more*, solver-level
  inputs with *Advanced options*.
* Several selected items of the same kind are edited together: the grid shows their common
  inputs (blank where the values differ) and a change applies to all of them.
* A mixed selection can be narrowed to one item type with the selection filter.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..elements import REGISTRY
from ..model import CHAMBER_PARAMS
from ..units import fmt

OUTPUT_UNITS = {
    "Area": "area", "pt_in": "pressure", "p exit": "pressure", "Δpt": "pressure",
    "Tt_rel_in": "temperature", "Tt_rel exit": "temperature", "Vθ_exit": "velocity", "Vθ in": "velocity",
    "Vθ out": "velocity", "ΔTt": "temperature_diff", "ΔTt windage": "temperature_diff",
    "Windage power": "power", "Rotor torque": "torque", "Stator torque": "torque",
    "pumped": "massflow", "prescribed": "massflow",
}
OUTPUT_LABELS = {
    "pt_in": "Driving total pressure", "Tt_rel_in": "Inlet Tt (element frame)", "Vθ_exit": "Exit Vθ",
    "Tt_rel exit": "Exit Tt (element frame)", "p exit": "Exit static pressure",
}
CHAMBER_TYPES = {"boundary": "Boundary chamber", "plenum": "Plenum chamber", "momentum": "Momentum chamber",
                 "inertial": "Inertial chamber"}

# inputs the user has to think about (shown in blue)
REQUIRED = {"p", "T", "n_holes", "diameter", "cd", "K", "n_paths", "n_pipes", "length", "n_teeth", "radius",
            "clearance", "pitch", "gap", "mdot", "vortex_type"}
REQUIRED_BY_TYPE = {"vortex": {"r_a", "r_b", "rotor"}, "cavity": {"r_a", "r_b", "rotor"},
                    "discpump": {"r_a", "r_b", "rotor"}, "orifice": {"n_holes", "diameter", "cd"}}
MORE_GROUPS = {"Inlet / exit", "Heat transfer", "Swirl / windage", "Friction", "Model", "Energy"}
ADVANCED_KEYS = {"cd_rev", "K_rev", "dT_max", "wet_area_factor", "f_mult", "htc_mult", "cd_mult", "mult",
                 "cf_rotor_mult", "cf_stator_mult", "K0", "n_seg", "heat_W"}


def param_level(spec, etype: str | None) -> str:
    if is_required(spec, etype):
        return "main"
    if spec.key in ADVANCED_KEYS or spec.group == "Numerics":
        return "advanced"
    if spec.group in MORE_GROUPS:
        return "more"
    return "main"


def is_required(spec, etype: str | None) -> bool:
    if etype in ("vortex", "cavity", "discpump") and spec.key in ("radius",):
        return False
    return spec.key in REQUIRED or spec.key in REQUIRED_BY_TYPE.get(etype or "", set())


def selection_groups(net, sel):
    """[(key, label, [(kind, id), ...])] of a selection, by item type."""
    groups = {}
    for kind, oid in sel:
        if kind == "chamber" and oid in net.chambers:
            k, lab = "chamber", "Chambers"
        elif kind == "element" and oid in net.elements:
            t = net.elements[oid].type
            k, lab = f"element:{t}", REGISTRY[t].label
        else:
            continue
        groups.setdefault(k, [lab, []])[1].append((kind, oid))
    return [(k, v[0], v[1]) for k, v in groups.items()]


class PropertyPanel(QWidget):
    paramChanged = Signal(str, int, str, object)        # kind, id, key, SI value
    paramsChanged = Signal(str, object, str, object)     # kind, [ids], key, SI value (multi-edit)
    nameChanged = Signal(str, int, str)
    modelTextChanged = Signal(str, str)                  # field, value
    connectionChanged = Signal(int, str, int)            # element id, "a" | "b", chamber id
    filterRequested = Signal(str)                        # selection-group key ("" = all)

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.sel = []
        self.store = QSettings("myFlowNet", "myFlowNet")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget()
        head.setObjectName("propHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(8, 6, 8, 6)
        hl.setSpacing(4)
        row = QHBoxLayout()
        self.type_label = QLabel("Model")
        self.type_label.setObjectName("typeLabel")
        row.addWidget(self.type_label, 1)
        self.id_label = QLabel("")
        self.id_label.setObjectName("idLabel")
        row.addWidget(self.id_label)
        hl.addLayout(row)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("nameEdit")
        self.name_edit.editingFinished.connect(self._name_done)
        hl.addWidget(self.name_edit)
        frow = QHBoxLayout()
        self.filter_label = QLabel("Selection filter")
        self.filter = QComboBox()
        self.filter.activated.connect(lambda i: self.filterRequested.emit(self.filter.itemData(i) or ""))
        frow.addWidget(self.filter_label)
        frow.addWidget(self.filter, 1)
        hl.addLayout(frow)
        lay.addWidget(head)

        self.tree = QTreeWidget()
        self.tree.setObjectName("propGrid")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Parameter", "Value", "Unit"])
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(12)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.setFocusPolicy(Qt.NoFocus)
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(0, 170)
        lay.addWidget(self.tree, 1)

        self.desc = QPlainTextEdit()
        self.desc.setObjectName("descEdit")
        self.desc.setPlaceholderText("Model description")
        self.desc.setMaximumHeight(110)
        self.desc.focusOutEvent = self._desc_focus_out
        lay.addWidget(self.desc)

        foot = QWidget()
        foot.setObjectName("propFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(8, 4, 8, 4)
        self.cb_more = QCheckBox("Show more")
        self.cb_adv = QCheckBox("Advanced options")
        self.cb_more.setChecked(self.store.value("props/more", "false") == "true")
        self.cb_adv.setChecked(self.store.value("props/advanced", "false") == "true")
        self.cb_more.toggled.connect(lambda v: (self.store.setValue("props/more", "true" if v else "false"),
                                                self.refresh()))
        self.cb_adv.toggled.connect(lambda v: (self.store.setValue("props/advanced", "true" if v else "false"),
                                               self.refresh()))
        fl.addWidget(self.cb_more)
        fl.addWidget(self.cb_adv)
        fl.addStretch(1)
        self.req_hint = QLabel("Blue: required input")
        self.req_hint.setObjectName("hintLabel")
        fl.addWidget(self.req_hint)
        lay.addWidget(foot)
        self.refresh()

    # ------------------------------------------------------------------ public
    def show_item(self, kind, oid):
        self.show_selection([(kind, oid)] if kind else [])

    def show_selection(self, sel):
        self.sel = list(sel)
        self.refresh()

    def refresh(self):
        net = self.main.net
        self.sel = [(k, i) for k, i in self.sel if (k == "chamber" and i in net.chambers)
                    or (k == "element" and i in net.elements)]
        self.tree.clear()
        groups = selection_groups(net, self.sel)
        self.filter.clear()
        multi_types = len(groups) > 1
        self.filter_label.setVisible(len(self.sel) > 1)
        self.filter.setVisible(len(self.sel) > 1)
        if len(self.sel) > 1:
            self.filter.addItem(f"All ({len(self.sel)})", "")
            for k, lab, items in groups:
                self.filter.addItem(f"{lab} ({len(items)})", k)
        self.desc.setVisible(not self.sel)
        if not self.sel:
            self._overview()
        elif multi_types:
            self._mixed(groups)
        else:
            kind = self.sel[0][0]
            ids = [i for _, i in self.sel]
            if kind == "chamber":
                self._chambers(ids)
            else:
                self._elements(ids)
        self.tree.expandAll()

    # ------------------------------------------------------------------ header
    def _set_head(self, type_text, id_text, name, editable=True):
        self.type_label.setText(type_text)
        self.id_label.setText(id_text)
        self.name_edit.blockSignals(True)
        self.name_edit.setText(name)
        self.name_edit.setVisible(editable)
        self.name_edit.blockSignals(False)

    def _name_done(self):
        txt = self.name_edit.text().strip()
        if not txt:
            return
        if not self.sel:
            if txt != self.main.net.title:
                self.modelTextChanged.emit("title", txt)
            return
        if len(self.sel) == 1:
            kind, oid = self.sel[0]
            obj = self.main.net.chambers[oid] if kind == "chamber" else self.main.net.elements[oid]
            if txt != obj.name:
                self.nameChanged.emit(kind, oid, txt)

    def _desc_focus_out(self, e):
        QPlainTextEdit.focusOutEvent(self.desc, e)
        if not self.sel and self.desc.toPlainText() != self.main.net.description:
            self.modelTextChanged.emit("description", self.desc.toPlainText())

    # ------------------------------------------------------------------ rows
    def _group(self, text, parent=None):
        it = QTreeWidgetItem([text, "", ""])
        f = QFont(self.tree.font())
        f.setBold(True)
        it.setFont(0, f)
        it.setFirstColumnSpanned(True)
        it.setFlags(Qt.ItemIsEnabled)
        (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
        return it

    def _row(self, parent, label, widget=None, value_text="", unit="", tip="", required=False):
        it = QTreeWidgetItem([label, value_text, unit])
        it.setFlags(Qt.ItemIsEnabled)
        if tip:
            it.setToolTip(0, tip)
        if required:
            it.setForeground(0, QBrush(QColor(self.main.theme.get("required", "#1452B8"))))
        it.setForeground(2, QBrush(QColor(self.main.theme["muted"])))
        if value_text:
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        parent.addChild(it)
        if widget is not None:
            if tip:
                widget.setToolTip(tip)
            self.tree.setItemWidget(it, 1, widget)
        return it

    def _param_rows(self, specs, values_list, kind, ids, etype=None):
        """Rows for `specs`; values_list holds the params dict of every selected item."""
        units = self.main.units
        more, adv = self.cb_more.isChecked(), self.cb_adv.isChecked()
        groups = []
        for s in specs:
            if s.group not in groups:
                groups.append(s.group)
        hidden = 0
        for g in groups:
            rows = []
            for s in specs:
                if s.group != g or not all(s.is_visible(v) for v in values_list):
                    continue
                lev = param_level(s, etype)
                if (lev == "more" and not more) or (lev == "advanced" and not adv):
                    hidden += 1
                    continue
                rows.append(s)
            if not rows:
                continue
            gi = self._group(g)
            for s in rows:
                vals = [v[s.key] for v in values_list]
                same = all(x == vals[0] for x in vals)
                w = self._editor(s, vals[0] if same else None, kind, ids)
                u = units.label(s.unit) if s.unit not in ("none",) else ""
                self._row(gi, s.label, w, unit=u, tip=s.tip, required=is_required(s, etype))
        if hidden:
            self.req_hint.setText(f"Blue: required input · {hidden} more hidden")
        else:
            self.req_hint.setText("Blue: required input")

    def _emit(self, kind, ids, key, value):
        if len(ids) == 1:
            self.paramChanged.emit(kind, ids[0], key, value)
        else:
            self.paramsChanged.emit(kind, list(ids), key, value)

    def _editor(self, s, value, kind, ids):
        units = self.main.units
        mixed = value is None
        if s.kind in ("choice", "rotor"):
            cb = QComboBox()
            cb.setFrame(False)
            if s.kind == "choice":
                for v, label in s.choices:
                    cb.addItem(label, v)
            else:
                cb.addItem("Stationary", 0)
                for r in self.main.net.rotors:
                    cb.addItem(f"{r.name}  ({fmt(r.rpm, 6)} rpm)", r.id)
            data = [cb.itemData(i) for i in range(cb.count())]
            if mixed:
                cb.insertItem(0, "(mixed)", None)
                cb.setCurrentIndex(0)
            else:
                cb.setCurrentIndex(data.index(value) if value in data else 0)
            cb.currentIndexChanged.connect(lambda i, cb=cb: cb.itemData(i) is not None and
                                           self._emit(kind, ids, s.key, cb.itemData(i)))
            return cb
        if s.kind == "bool":
            ch = QCheckBox()
            if mixed:
                ch.setTristate(True)
                ch.setCheckState(Qt.PartiallyChecked)
            else:
                ch.setChecked(bool(value))
            ch.clicked.connect(lambda v: self._emit(kind, ids, s.key, bool(v)))
            return ch
        ed = QLineEdit()
        ed.setFrame(False)
        ed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if mixed:
            ed.setPlaceholderText("(mixed)")
        else:
            disp = units.to_display(s.unit, value) if s.kind == "float" else value
            ed.setText(fmt(disp, 8) if s.kind == "float" else str(value))
        start = ed.text()

        def commit(ed=ed, s=s):
            txt = ed.text().strip().replace(",", ".")
            if txt == start or (mixed and not txt):
                return
            try:
                v = float(txt)
                v = units.to_si(s.unit, v) if s.kind == "float" else v
                v = s.coerce(v)
            except (ValueError, TypeError) as ex:
                ed.setProperty("invalid", True)
                ed.setToolTip(str(ex) if str(ex) else "Enter a number")
                ed.style().unpolish(ed)
                ed.style().polish(ed)
                return
            self._emit(kind, ids, s.key, v)

        ed.editingFinished.connect(commit)
        return ed

    def _results(self, rows):
        if not rows:
            return
        gi = self._group("Results" + ("  (out of date)" if self.main.results_stale else ""))
        for lab, val, unit in rows:
            self._row(gi, lab, value_text=val, unit=unit)

    # ------------------------------------------------------------------ content
    def _overview(self):
        net = self.main.net
        self._set_head("Model", "", net.title)
        self.desc.blockSignals(True)
        if self.desc.toPlainText() != net.description:
            self.desc.setPlainText(net.description)
        self.desc.blockSignals(False)
        nb = sum(1 for c in net.chambers.values() if c.is_boundary)
        gi = self._group("Contents")
        self._row(gi, "Chambers", value_text=str(len(net.chambers)))
        self._row(gi, "Boundary chambers", value_text=str(nb))
        self._row(gi, "Elements", value_text=str(len(net.elements)))
        gi = self._group("Rotors")
        for r in net.rotors:
            self._row(gi, r.name, value_text=fmt(r.rpm, 6), unit="rpm")
        if net.background and net.background.get("file"):
            import os
            gi = self._group("Background geometry")
            self._row(gi, "File", value_text=os.path.basename(net.background["file"]))
        gi = self._group("How to build")
        for t, tip in (("Drag a chamber from the library onto the canvas",
                        "Drag a chamber type from the Element Library onto the canvas, or click it and then click "
                        "the canvas (Shift places several)."),
                       ("Drop an element on its upstream chamber",
                        "Drag an element type onto the upstream chamber, then click the downstream chamber "
                        "(or pick it in the library and drag from chamber to chamber)."),
                       ("Shift-click or a rectangle edits several",
                        "Several items of one type are edited together here; the selection filter narrows a "
                        "mixed selection."),
                       ("Middle-drag pans · wheel zooms · Esc selects", "")):
            it = self._row(gi, t, tip=tip)
            it.setFirstColumnSpanned(True)

    def _mixed(self, groups):
        self._set_head("Mixed selection", f"{len(self.sel)} items", "", editable=False)
        gi = self._group("Selection")
        for k, lab, items in groups:
            self._row(gi, lab, value_text=str(len(items)))
        it = self._row(gi, "Use the selection filter to edit one item type together.")
        it.setFirstColumnSpanned(True)

    def _chambers(self, ids):
        net = self.main.net
        chs = [net.chambers[i] for i in ids]
        if len(chs) == 1:
            ch = chs[0]
            self._set_head(CHAMBER_TYPES.get(ch.kind, "Chamber"), f"C{ch.id}", ch.name)
        else:
            kinds = {c.kind for c in chs}
            t = CHAMBER_TYPES[kinds.pop()] + "s" if len(kinds) == 1 else "Chambers"
            self._set_head(f"{t} – editing {len(chs)} together", ", ".join(f"C{c.id}" for c in chs[:6])
                           + ("…" if len(chs) > 6 else ""), "", editable=False)
        self._param_rows(CHAMBER_PARAMS, [c.params for c in chs], "chamber", ids)
        sol = self.main.solution
        if len(chs) == 1 and sol and chs[0].id in sol.chambers:
            r = sol.chambers[chs[0].id]
            u = self.main.units
            rows = [("Static pressure", fmt(u.to_display("pressure", r["p"]), 6), u.label("pressure")),
                    ("Total pressure", fmt(u.to_display("pressure", r["pt"]), 6), u.label("pressure")),
                    ("Total temperature", fmt(u.to_display("temperature", r["Tt"]), 6), u.label("temperature")),
                    ("Swirl ratio K", fmt(r["K"], 5), ""),
                    ("Tangential velocity", fmt(r["vtheta"], 5), "m/s"),
                    ("Density", fmt(r["rho"], 5), "kg/m³")]
            if r.get("vm", 0.0) > 0:
                rows += [("Through-flow velocity", fmt(r["vm"], 5), "m/s"),
                         ("Through-flow direction φ", fmt(r.get("phi", 0.0), 4), "deg")]
            if r.get("flow_out") is not None:
                rows.append(("Net flow out of boundary", fmt(u.to_display("massflow", r["flow_out"]), 6),
                             u.label("massflow")))
            if r.get("T_arrival") is not None:
                rows.append(("Arriving flow Tt", fmt(u.to_display("temperature", r["T_arrival"]), 6),
                             u.label("temperature")))
            self._results(rows)

    def _elements(self, ids):
        net = self.main.net
        els = [net.elements[i] for i in ids]
        cls = REGISTRY[els[0].type]
        if len(els) == 1:
            el = els[0]
            self._set_head(cls.label, f"E{el.id}", el.name)
            gi = self._group("Connection")
            for port, lab in (("a", "Upstream chamber (a)"), ("b", "Downstream chamber (b)")):
                cb = QComboBox()
                cb.setFrame(False)
                for c in net.chambers.values():
                    cb.addItem(f"C{c.id}  {c.name}", c.id)
                cur = getattr(el, port)
                cb.setCurrentIndex([cb.itemData(i) for i in range(cb.count())].index(cur))
                cb.currentIndexChanged.connect(lambda i, cb=cb, port=port, eid=el.id:
                                               self.connectionChanged.emit(eid, port, cb.itemData(i)))
                self._row(gi, lab, cb, tip="Change the connection by choosing another chamber")
        else:
            self._set_head(f"{cls.label} – editing {len(els)} together",
                           ", ".join(f"E{e.id}" for e in els[:6]) + ("…" if len(els) > 6 else ""), "",
                           editable=False)
        self._param_rows(cls.PARAMS, [e.params for e in els], "element", ids, els[0].type)
        sol = self.main.solution
        if len(els) == 1 and sol and els[0].id in sol.elements:
            r = sol.elements[els[0].id]
            u = self.main.units
            rows = [("Mass flow (a → b)", fmt(u.to_display("massflow", r["mdot"]), 6), u.label("massflow")),
                    ("Static Δp (a − b)", fmt(u.to_display("pressure", r["dp"]), 6), u.label("pressure")),
                    ("Inlet Tt", fmt(u.to_display("temperature", r["Tt_in"]), 6), u.label("temperature")),
                    ("Exit Tt", fmt(u.to_display("temperature", r["Tt_out"]), 6), u.label("temperature"))]
            for k, v in r["outputs"].items():
                if isinstance(v, bool) or k == "choked":
                    rows.append((OUTPUT_LABELS.get(k, k), "yes" if v else "no", ""))
                elif isinstance(v, (int, float)):
                    kind = OUTPUT_UNITS.get(k)
                    if kind:
                        rows.append((OUTPUT_LABELS.get(k, k), fmt(u.to_display(kind, v), 6), u.label(kind)))
                    else:
                        rows.append((OUTPUT_LABELS.get(k, k), fmt(v, 5), ""))
                else:
                    rows.append((k, str(v), ""))
            self._results(rows)
