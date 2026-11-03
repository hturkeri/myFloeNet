"""Model Browser (tree of the model) and Element Library (drag & drop source)."""
from __future__ import annotations

import os

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QTreeWidget,
                               QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget)

from ..elements import REGISTRY
from .glyphs import chamber_icon, element_icon

MIME = "application/x-myflownet-mode"
CHAMBER_LABELS = {"boundary": "Boundary", "plenum": "Plenum", "momentum": "Momentum (through-flow)",
                  "inertial": "Inertial (swirl)"}
LIBRARY = [
    ("Chambers", [("add:boundary", "Boundary"), ("add:plenum", "Plenum"), ("add:momentum", "Momentum (through-flow)"),
                  ("add:inertial", "Inertial (swirl)")]),
    ("Restrictions", [("connect:orifice", None), ("connect:kloss", None)]),
    ("Tubes", [("connect:pipe", None)]),
    ("Seals", [("connect:labyrinth", None)]),
    ("Rotating cavities", [("connect:vortex", None), ("connect:cavity", None), ("connect:discpump", None)]),
    ("Sources", [("connect:fixedflow", None)]),
]
CHAMBER_TIPS = {
    "boundary": "Fixed pressure, temperature and swirl (source or sink).",
    "plenum": "Internal chamber; swirl fixed by the user (default: none).",
    "momentum": "Internal node that carries the through-flow velocity of the incoming jets; downstream "
                "elements recover its dynamic head as cos²θ.",
    "inertial": "Internal chamber whose swirl follows from the angular momentum of the incoming flows.",
}


class _Tree(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setUniformRowHeights(True)
        self.setIndentation(14)
        self.setIconSize(QSize(18, 18))


class LibraryTree(_Tree):
    """Element Library: click to pick a tool, or drag an entry onto the canvas."""

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

    def startDrag(self, actions):
        it = self.currentItem()
        mode = it.data(0, Qt.UserRole) if it else None
        if not mode:
            return
        md = QMimeData()
        md.setData(MIME, mode.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(it.icon(0).pixmap(28, 28))
        drag.exec(Qt.CopyAction)


class ElementLibrary(QWidget):
    modePicked = Signal(str)

    def __init__(self, main):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tree = LibraryTree()
        lay.addWidget(self.tree)
        self.items = {}
        self.build()
        self.tree.itemClicked.connect(self._clicked)

    def build(self):
        t = self.main.theme
        self.tree.clear()
        self.items = {}
        bold = QFont(self.tree.font())
        bold.setBold(True)
        sel = QTreeWidgetItem(["Select / move"])
        sel.setData(0, Qt.UserRole, "select")
        sel.setToolTip(0, "Select, move and edit items (Esc)")
        from .glyphs import tool_icon
        sel.setIcon(0, tool_icon("select", t["ink"], 18))
        self.tree.addTopLevelItem(sel)
        self.items["select"] = sel
        for cat, entries in LIBRARY:
            ci = QTreeWidgetItem([cat])
            ci.setFont(0, bold)
            ci.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(ci)
            for mode, label in entries:
                kind, key = mode.split(":")
                if kind == "add":
                    it = QTreeWidgetItem([label])
                    it.setIcon(0, chamber_icon(key, t["ink2"], t["surface"], 18))
                    it.setToolTip(0, CHAMBER_TIPS[key] + "\nDrag onto the canvas, or click and then click the canvas.")
                else:
                    cls = REGISTRY[key]
                    it = QTreeWidgetItem([cls.label])
                    it.setIcon(0, element_icon(key, t["ink"], 20))
                    it.setToolTip(0, cls.description + "\nDrag onto the upstream chamber, then click the downstream "
                                                       "chamber.")
                it.setData(0, Qt.UserRole, mode)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                ci.addChild(it)
                self.items[mode] = it
        self.tree.expandAll()

    def _clicked(self, it, col):
        mode = it.data(0, Qt.UserRole)
        if mode:
            self.modePicked.emit(mode)

    def sync(self, mode):
        it = self.items.get(mode)
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(it) if it else self.tree.clearSelection()
        self.tree.blockSignals(False)


class ModelBrowser(QWidget):
    """Tree of chambers, elements, rotors and background geometry; selection is synchronised with the canvas."""
    selectionPicked = Signal(object)     # [(kind, id), ...]
    focusRequested = Signal(str, int)    # double click: centre and edit

    def __init__(self, main):
        super().__init__()
        self.main = main
        self._sync = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(4, 4, 4, 4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name or ID")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.sort = QComboBox()
        self.sort.addItem("By type", "type")
        self.sort.addItem("By ID", "id")
        self.sort.setToolTip("Type sort")
        self.sort.currentIndexChanged.connect(lambda _: self.rebuild())
        row.addWidget(self.search, 1)
        row.addWidget(self.sort)
        lay.addLayout(row)
        self.tree = _Tree()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Entity", "Info"])
        self.tree.header().setStretchLastSection(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._picked)
        self.tree.itemDoubleClicked.connect(self._double)
        lay.addWidget(self.tree)
        self.rebuild()

    def rebuild(self):
        net = self.main.net
        t = self.main.theme
        self._sync = True
        self.tree.clear()
        bold = QFont(self.tree.font())
        bold.setBold(True)
        by_id = self.sort.currentData() == "id"
        sol = self.main.solution
        u = self.main.units

        def top(text):
            it = QTreeWidgetItem([text, ""])
            it.setFont(0, bold)
            it.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(it)
            return it
        cht = top(f"Chambers ({len(net.chambers)})")
        groups = {}
        for ch in sorted(net.chambers.values(), key=lambda c: c.id):
            if by_id:
                parent = cht
            else:
                if ch.kind not in groups:
                    groups[ch.kind] = QTreeWidgetItem([CHAMBER_LABELS[ch.kind], ""])
                    groups[ch.kind].setFlags(Qt.ItemIsEnabled)
                    cht.addChild(groups[ch.kind])
                parent = groups[ch.kind]
            info = ""
            if sol and ch.id in sol.chambers:
                from ..units import fmt
                info = f"{fmt(u.to_display('pressure', sol.chambers[ch.id]['p']), 5)} {u.label('pressure')}"
            it = QTreeWidgetItem([f"C{ch.id}  {ch.name}", info])
            it.setIcon(0, chamber_icon(ch.kind, t["ink2"], t["surface"], 16))
            it.setData(0, Qt.UserRole, ("chamber", ch.id))
            parent.addChild(it)
        elt = top(f"Elements ({len(net.elements)})")
        groups = {}
        for el in sorted(net.elements.values(), key=lambda e: e.id):
            if by_id:
                parent = elt
            else:
                if el.type not in groups:
                    groups[el.type] = QTreeWidgetItem([REGISTRY[el.type].label, ""])
                    groups[el.type].setFlags(Qt.ItemIsEnabled)
                    elt.addChild(groups[el.type])
                parent = groups[el.type]
            info = f"C{el.a} → C{el.b}"
            if sol and el.id in sol.elements:
                from ..units import fmt
                info = f"{fmt(u.to_display('massflow', sol.elements[el.id]['mdot']), 4)} {u.label('massflow')}"
            it = QTreeWidgetItem([f"E{el.id}  {el.name}", info])
            it.setIcon(0, element_icon(el.type, t["ink"], 18))
            it.setData(0, Qt.UserRole, ("element", el.id))
            it.setToolTip(0, f"C{el.a} {net.chambers[el.a].name}  →  C{el.b} {net.chambers[el.b].name}")
            parent.addChild(it)
        rt = top(f"Rotors ({len(net.rotors)})")
        for r in net.rotors:
            it = QTreeWidgetItem([f"R{r.id}  {r.name}", f"{r.rpm:g} rpm"])
            it.setFlags(Qt.ItemIsEnabled)
            rt.addChild(it)
        if net.background and net.background.get("file"):
            gt = top("Background geometry")
            it = QTreeWidgetItem([os.path.basename(net.background["file"]), ""])
            it.setFlags(Qt.ItemIsEnabled)
            it.setToolTip(0, net.background["file"])
            gt.addChild(it)
        self.tree.expandAll()
        self._sync = False
        self._apply_filter(self.search.text())
        self.sync_selection(self.main.scene.selection_list())

    def _items(self):
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            yield it.value()
            it += 1

    def _apply_filter(self, text):
        text = text.strip().lower()
        for it in self._items():
            d = it.data(0, Qt.UserRole)
            if d:
                it.setHidden(bool(text) and text not in it.text(0).lower())

    def sync_selection(self, sel):
        if self._sync:
            return
        self._sync = True
        want = set(sel)
        first = None
        for it in self._items():
            d = it.data(0, Qt.UserRole)
            if d:
                on = tuple(d) in want
                it.setSelected(on)
                if on and first is None:
                    first = it
        if first is not None:
            self.tree.scrollToItem(first)
        self._sync = False

    def _picked(self):
        if self._sync:
            return
        sel = [tuple(it.data(0, Qt.UserRole)) for it in self.tree.selectedItems() if it.data(0, Qt.UserRole)]
        self._sync = True
        self.selectionPicked.emit(sel)
        self._sync = False

    def _double(self, it, col):
        d = it.data(0, Qt.UserRole)
        if d:
            self.focusRequested.emit(d[0], d[1])
