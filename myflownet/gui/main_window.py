"""myFlowNet main window."""
from __future__ import annotations

import copy
import csv
import json
import math

import numpy as np
import os
import sys
import threading
import traceback

from PySide6.QtCore import QObject, QPointF, QProcess, QRectF, QSettings, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDockWidget, QFileDialog, QLabel,
                               QMainWindow, QMessageBox, QSizePolicy, QTabWidget, QTextBrowser, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

from .. import __version__, cad
from ..elements import REGISTRY
from ..examples import EXAMPLES
from ..model import Network
from ..solver import SolverError, solve
from ..units import UnitSystem, fmt
from ..geomview import view_rotation
from .background import VIEW_KEYS, BackgroundLayer, BackgroundPanel, CadLoader, merged_settings
from .browser import ElementLibrary, ModelBrowser
from .canvas import ChamberItem, ElementItem, NetworkScene, NetworkView
from .contour import QUANTITIES, ContourSettings, LegendDialog, colour_fn, format_value
from .dialogs import SettingsDialog, TheoryDialog
from .glyphs import chamber_icon, element_icon, tool_icon
from .properties import PropertyPanel
from .results import LinePlot, LogView, ProfilePanel, ResultTable
from .theme import APP_THEMES, CANVAS_PRESETS, CLASSIC, DARK, LIGHT, apply_theme, ui_font

LAYOUT_VERSION = 3
LABEL_MODES = [("id_name", "ID + name"), ("name", "Name"), ("id", "ID"), ("none", "None")]
CHAMBER_NAMES = {"boundary": "Boundary", "plenum": "Plenum", "momentum": "Node", "inertial": "Chamber"}


class SolveWorker(QObject):
    progress = Signal(int, float, float, float, float)
    done = Signal(object, str)

    def __init__(self, net, initial):
        super().__init__()
        self.net = net
        self.initial = initial
        self.stop_event = threading.Event()

    def run(self):
        try:
            sol = solve(self.net, initial=self.initial,
                        callback=lambda *a: self.progress.emit(*[float(x) if i else int(x) for i, x in enumerate(a)]),
                        stop=self.stop_event.is_set)
            self.done.emit(sol, "")
        except SolverError as ex:
            self.done.emit(None, str(ex))
        except Exception:  # pragma: no cover - shown to the user
            self.done.emit(None, traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self, net: Network | None = None, path: str | None = None):
        super().__init__()
        self.settings_store = QSettings("myFlowNet", "myFlowNet")
        st = self.settings_store
        name = st.value("theme", "classic")
        self.theme = APP_THEMES.get(name, CLASSIC)
        apply_theme(QApplication.instance(), self.theme)
        self.net = net or EXAMPLES["HPT pre-swirl cooling system"]()
        self.file_path = path
        self.units = UnitSystem(self.net.display_units or self._stored_units())
        self.solution = None
        self.results_stale = False
        self.modified = False
        self.undo_stack, self.redo_stack = [], []
        self.thread = None
        self.worker = None
        try:
            self.contour = ContourSettings.from_dict(json.loads(st.value("contour", "{}") or "{}"))
        except Exception:
            self.contour = ContourSettings()
        self.history = []

        self.scene = NetworkScene(self.net, self.theme)
        custom = st.value("canvas/custom", "")
        custom = tuple(custom.split(",")) if isinstance(custom, str) and custom.count(",") == 1 else None
        self.scene.set_canvas(st.value("canvas/preset", "blue"), custom)
        self.scene.label_mode = st.value("canvas/labels", "id_name")
        self.scene.wireframe = st.value("canvas/wireframe", "false") == "true"
        self.scene.line_scale = float(st.value("canvas/line", 1.0))
        self.scene.show_axes = st.value("canvas/axes", "true") == "true"
        self.scene.show_results = st.value("canvas/results", "true") == "true"
        self.view = NetworkView(self.scene)
        self.setCentralWidget(self.view)
        self.bg = BackgroundLayer(self.scene)
        self.scene.background = self.bg
        self.cad_loader = CadLoader(self)
        self._bg_summary = ""
        self._bg_fit_network = False
        self._bg_fit_view = False
        self.pip = None
        self._build_docks()
        self._build_actions()
        self._build_toolbar()
        self._build_menus()
        self._build_status()
        self._connect()
        self.scene.rebuild(self.net)
        self.browser.rebuild()
        self._attach_background(fit_view=True)
        self.resize(1560, 960)
        self._default_state = self.saveState(LAYOUT_VERSION)
        geo = st.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        state = st.value("windowState")
        if state is not None:
            self.restoreState(state, LAYOUT_VERSION)
        self._update_title()
        QTimer.singleShot(0, self.view.fit)

    # ================================================================ build
    def _stored_units(self):
        u = self.settings_store.value("units")
        return u if isinstance(u, dict) else {}

    def _dock(self, title, name, widget, area):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                      QDockWidget.DockWidgetClosable)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.library = ElementLibrary(self)
        self.library_dock = self._dock("Element Library", "libraryDock", self.library, Qt.LeftDockWidgetArea)
        self.browser = ModelBrowser(self)
        self.browser_dock = self._dock("Model Browser", "browserDock", self.browser, Qt.LeftDockWidgetArea)
        self.splitDockWidget(self.library_dock, self.browser_dock, Qt.Vertical)
        self.resizeDocks([self.library_dock, self.browser_dock], [330, 420], Qt.Vertical)
        self.resizeDocks([self.library_dock], [300], Qt.Horizontal)

        self.props = PropertyPanel(self)
        self.props_dock = self._dock("Property Editor", "propsDock", self.props, Qt.RightDockWidgetArea)
        self.props_dock.setMinimumWidth(340)
        self.bg_panel = BackgroundPanel()
        self.bg_dock = self._dock("Background Geometry", "backgroundDock", self.bg_panel, Qt.RightDockWidgetArea)
        self.tabifyDockWidget(self.props_dock, self.bg_dock)
        self.props_dock.raise_()

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.info = QTextBrowser()
        self.info.setOpenLinks(False)
        self.logv = LogView()
        self.t_ch = ResultTable()
        self.t_el = ResultTable()
        self.conv = LinePlot(self.theme)
        self.conv.set_data("Convergence", "Iteration", "Maximum residual", [], log_y=True)
        self.profile = ProfilePanel(self.theme)
        self.tabs.addTab(self.info, "Info")
        self.tabs.addTab(self.logv, "Output")
        self.tabs.addTab(self.t_ch, "Chamber Results")
        self.tabs.addTab(self.t_el, "Element Results")
        self.tabs.addTab(self.conv, "Convergence")
        self.tabs.addTab(self.profile, "Distribution")
        self.output_dock = self._dock("Output", "outputDock", self.tabs, Qt.BottomDockWidgetArea)
        self.resizeDocks([self.output_dock], [250], Qt.Vertical)

    def _act(self, text, slot, shortcut=None, icon=None, tip=None, checkable=False):
        a = QAction(text, self)
        if icon:
            a.setIcon(tool_icon(icon, self.theme["ink"], 20))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        a.icon_kind = icon
        return a

    def _build_actions(self):
        self.a_new = self._act("New", self.new_model, "Ctrl+N", "new", "New empty model")
        self.a_open = self._act("Open…", self.open_model, "Ctrl+O", "open", "Open a model file")
        self.a_save = self._act("Save", self.save_model, "Ctrl+S", "save", "Save the model")
        self.a_save_as = self._act("Save as…", lambda: self.save_model(as_new=True), "Ctrl+Shift+S")
        self.a_undo = self._act("Undo", self.undo, "Ctrl+Z", "undo", "Undo")
        self.a_redo = self._act("Redo", self.redo, "Ctrl+Y", "redo", "Redo")
        self.a_delete = self._act("Delete", self.delete_selected, "Del")
        self.a_select_all = self._act("Select all", self.select_all, "Ctrl+A")
        self.a_select = self._act("Select / move", lambda: self.scene.set_mode("select"), None, "select",
                                  "Select, move and edit items (Esc)", checkable=True)
        self.a_select.setChecked(True)
        self.a_solve = self._act("Run", self.solve, "F5", "play", "Run the solver (F5)")
        self.a_stop = self._act("Stop", self.stop_solve, None, "stop", "Stop the solver")
        self.a_stop.setEnabled(False)
        self.a_fit = self._act("Fit to window", self.view.fit, "F", "fit", "Fit the model in the window (F)")
        self.a_zoom_in = self._act("Zoom in", lambda: self.view.zoom_by(1.25), "Ctrl++", "zoomin", "Zoom in")
        self.a_zoom_out = self._act("Zoom out", lambda: self.view.zoom_by(0.8), "Ctrl+-", "zoomout", "Zoom out")
        self.a_settings = self._act("Model settings…", self.edit_settings, "Ctrl+,", "settings",
                                    "Rotors, gas model, solver tolerances and units")
        self.a_export = self._act("Export results (CSV)…", self.export_csv, None, "export",
                                  "Export chamber and element results to CSV")
        self.a_labels = self._act("Results on model", self.toggle_labels, None, "labels",
                                  "Print results next to chambers and elements", checkable=True)
        self.a_labels.setChecked(self.scene.show_results)
        self.a_wire = self._act("Symbols as wireframe", self.toggle_wireframe, None, None,
                                "Draw chamber and element symbols as outlines", checkable=True)
        self.a_wire.setChecked(self.scene.wireframe)
        self.a_axes = self._act("Global axes", self.toggle_axes, None, None, "Show the axes triad", checkable=True)
        self.a_axes.setChecked(self.scene.show_axes)
        self.a_theory = self._act("Theory guide", self.show_theory, "F1", "help", "Equations and references")
        self.a_legend = self._act("Contour / legend settings…", self.edit_contour, None, "legend",
                                  "Quantity, levels, scale and format of the contour colouring")
        self.a_bg_load = self._act("Load background geometry…", self.load_background, "Ctrl+G", None,
                                   "Load a STEP / IGES / STL model to draw the network on")
        self.a_bg_remove = self._act("Remove background geometry", self.remove_background)
        self.a_bg_show = self._act("Background geometry", self.toggle_background, "Ctrl+Shift+G", "geometry",
                                   "Show / hide the background CAD geometry (Ctrl+Shift+G)", checkable=True)
        self.a_bg_radii = self._act("Set chamber radii from background geometry", self.radii_from_background)

        self.g_labels = QActionGroup(self)
        self.a_label_modes = []
        for key, text in LABEL_MODES:
            a = QAction(text, self, checkable=True)
            a.setChecked(self.scene.label_mode == key)
            a.triggered.connect(lambda _=False, k=key: self.set_label_mode(k))
            self.g_labels.addAction(a)
            self.a_label_modes.append((key, a))
        self.g_canvas = QActionGroup(self)
        self.a_canvas = []
        for key, c in CANVAS_PRESETS.items():
            a = QAction(c["label"] + ("…" if key == "gradient" else ""), self, checkable=True)
            a.setChecked(self.scene.canvas_preset == key)
            a.triggered.connect(lambda _=False, k=key: self.set_canvas(k))
            self.g_canvas.addAction(a)
            self.a_canvas.append((key, a))
        self.g_style = QActionGroup(self)
        self.a_styles = []
        for key, text in (("classic", "Classic"), ("light", "Modern light"), ("dark", "Modern dark")):
            a = QAction(text, self, checkable=True)
            a.setChecked(self.theme.get("name") == key)
            a.triggered.connect(lambda _=False, k=key: self.set_app_style(k))
            self.g_style.addAction(a)
            self.a_styles.append((key, a))

    def _build_toolbar(self):
        def bar(title, name):
            tb = self.addToolBar(title)
            tb.setObjectName(name)
            tb.setIconSize(QSize(20, 20))
            return tb
        tb = bar("File", "fileToolbar")
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
        tb = bar("Edit", "editToolbar")
        for a in (self.a_undo, self.a_redo, self.a_select):
            tb.addAction(a)
        tb = bar("View", "viewToolbar")
        for a in (self.a_fit, self.a_zoom_in, self.a_zoom_out, self.a_labels, self.a_bg_show):
            tb.addAction(a)
        lab = QLabel(" Labels ")
        lab.setObjectName("hintLabel")
        tb.addWidget(lab)
        self.label_combo = QComboBox()
        for key, text in LABEL_MODES:
            self.label_combo.addItem(text, key)
        self.label_combo.setCurrentIndex(max(self.label_combo.findData(self.scene.label_mode), 0))
        self.label_combo.activated.connect(lambda i: self.set_label_mode(self.label_combo.itemData(i)))
        tb.addWidget(self.label_combo)
        tb = bar("Solver", "solverToolbar")
        self.solve_btn = QToolButton()
        self.solve_btn.setObjectName("solveButton")
        self.solve_btn.setDefaultAction(self.a_solve)
        self.solve_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.a_solve.setIcon(tool_icon("play", "#FFFFFF", 20))
        tb.addWidget(self.solve_btn)
        tb.addAction(self.a_stop)
        tb = bar("Post-Processing", "postToolbar")
        lab = QLabel(" Colorize ")
        lab.setObjectName("hintLabel")
        tb.addWidget(lab)
        self.color_combo = QComboBox()
        for k, (_, text, _, _) in QUANTITIES.items():
            self.color_combo.addItem(text, k)
        self.color_combo.setCurrentIndex(max(self.color_combo.findData(self.contour.quantity), 0))
        self.color_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.color_combo.activated.connect(self._color_changed)
        tb.addWidget(self.color_combo)
        tb.addAction(self.a_legend)
        tb.addAction(self.a_export)
        tb = bar("Help", "helpToolbar")
        tb.addAction(self.a_settings)
        tb.addAction(self.a_theory)
        self.toolbar = tb

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_as):
            m.addAction(a)
        ex = m.addMenu("Examples")
        for name, fn in EXAMPLES.items():
            ex.addAction(name, lambda f=fn: self.load_example(f))
        m.addSeparator()
        m.addAction(self.a_bg_load)
        m.addAction(self.a_bg_remove)
        m.addSeparator()
        m.addAction(self.a_export)
        m.addSeparator()
        m.addAction("Quit", self.close, QKeySequence("Ctrl+Q"))
        m = mb.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_select, self.a_select_all, self.a_delete):
            m.addAction(a)
        m = mb.addMenu("&View")
        for a in (self.a_fit, self.a_zoom_in, self.a_zoom_out):
            m.addAction(a)
        m.addSeparator()
        sm = m.addMenu("Labels")
        for _, a in self.a_label_modes:
            sm.addAction(a)
        m.addAction(self.a_labels)
        m.addAction(self.a_bg_show)
        sm = m.addMenu("Modelling window background")
        for _, a in self.a_canvas:
            sm.addAction(a)
        m.addAction(self.a_wire)
        sm = m.addMenu("Connection line thickness")
        self.g_line = QActionGroup(self)
        for f, text in ((0.6, "Thin"), (1.0, "Normal"), (1.6, "Thick"), (2.4, "Extra thick")):
            a = QAction(text, self, checkable=True)
            a.setChecked(abs(self.scene.line_scale - f) < 1e-6)
            a.triggered.connect(lambda _=False, f=f: self.set_line_scale(f))
            self.g_line.addAction(a)
            sm.addAction(a)
        m.addAction(self.a_axes)
        m.addSeparator()
        sm = m.addMenu("Application style")
        for _, a in self.a_styles:
            sm.addAction(a)
        sm = m.addMenu("Panels")
        for d in (self.library_dock, self.browser_dock, self.props_dock, self.bg_dock, self.output_dock):
            sm.addAction(d.toggleViewAction())
        sm.addSeparator()
        for tb in self.findChildren(QToolBar):
            sm.addAction(tb.toggleViewAction())
        m.addAction("Reset layout", self.reset_layout)
        m = mb.addMenu("&Tools")
        m.addAction("Check connectivity", self.check_model)
        m.addAction("Set element flow directions from the drawing", self.directions_from_drawing)
        m.addAction(self.a_bg_radii)
        m.addSeparator()
        m.addAction("Units…", self.edit_settings)
        m = mb.addMenu("&Pre-Processing")
        m.addAction("Property Editor", lambda: self._raise(self.props_dock))
        m.addAction("Model Browser", lambda: self._raise(self.browser_dock))
        m.addAction("Element Library", lambda: self._raise(self.library_dock))
        m.addAction("Background geometry", self.show_background_panel)
        m.addSeparator()
        m.addAction("Rotors, gas and units…", self.edit_settings)
        m = mb.addMenu("&Solver")
        m.addAction(self.a_solve)
        m.addAction(self.a_stop)
        m.addSeparator()
        m.addAction("Solver settings…", self.edit_settings)
        m.addAction("Check model", self.check_model)
        m.addAction("Solver output", lambda: self._show_tab(self.logv))
        m = mb.addMenu("P&ost-Processing")
        sm = m.addMenu("Colorize")
        self.g_color = QActionGroup(self)
        self.a_color = []
        for k, (_, text, _, _) in QUANTITIES.items():
            a = QAction(text, self, checkable=True)
            a.setChecked(self.contour.quantity == k)
            a.triggered.connect(lambda _=False, k=k: self.set_contour_quantity(k))
            self.g_color.addAction(a)
            sm.addAction(a)
            self.a_color.append((k, a))
        m.addAction(self.a_legend)
        m.addSeparator()
        m.addAction("Chamber results table", lambda: self._show_tab(self.t_ch))
        m.addAction("Element results table", lambda: self._show_tab(self.t_el))
        m.addAction("Convergence history", lambda: self._show_tab(self.conv))
        m.addAction("Distribution along the element", lambda: self._show_tab(self.profile))
        m.addSeparator()
        m.addAction(self.a_export)
        m = mb.addMenu("&Help")
        m.addAction(self.a_theory)
        m.addAction("About myFlowNet", self.about)

    def _build_status(self):
        sb = self.statusBar()
        self.st_icon = QLabel()
        self.st_text = QLabel("Ready")
        self.st_stale = QLabel("")
        self.st_mode = QLabel("")
        self.st_coord = QLabel("")
        self.st_coord.setObjectName("hintLabel")
        self.st_count = QLabel("")
        self.st_count.setObjectName("hintLabel")
        sb.addWidget(self.st_icon)
        sb.addWidget(self.st_text, 1)
        sb.addPermanentWidget(self.st_coord)
        sb.addPermanentWidget(self.st_count)
        sb.addPermanentWidget(self.st_stale)
        sb.addPermanentWidget(self.st_mode)

    def _connect(self):
        sc = self.scene
        sc.selectionIds.connect(self._on_selection)
        sc.selectionListChanged.connect(self._on_selection_list)
        sc.addChamberRequested.connect(self.add_chamber)
        sc.addElementRequested.connect(self.add_element)
        sc.deleteRequested.connect(self.delete_selected)
        sc.reverseRequested.connect(self.reverse_element)
        sc.duplicateRequested.connect(self.duplicate_chamber)
        sc.moveFinished.connect(self._moved)
        sc.modeChanged.connect(self._mode_changed)
        self.props.paramChanged.connect(self.set_param)
        self.props.paramsChanged.connect(self.set_params)
        self.props.nameChanged.connect(self.set_name)
        self.props.modelTextChanged.connect(self.set_model_text)
        self.props.connectionChanged.connect(self.set_connection)
        self.props.filterRequested.connect(self.filter_selection)
        self.library.modePicked.connect(self.scene.set_mode)
        self.browser.selectionPicked.connect(lambda sel: self.scene.select_many(sel))
        self.browser.focusRequested.connect(self.focus_item)
        self.t_ch.rowActivated.connect(lambda cid: self.scene.select("chamber", cid))
        self.t_el.rowActivated.connect(lambda eid: self.scene.select("element", eid))
        self.view.cursorMoved.connect(self._cursor_moved)
        self.cad_loader.loaded.connect(self._bg_loaded)
        self.cad_loader.failed.connect(self._bg_failed)
        self.cad_loader.progress.connect(self._bg_progress)
        self.bg.placementChanged.connect(self._bg_placement_changed)
        bp = self.bg_panel
        bp.loadRequested.connect(self.load_background)
        bp.removeRequested.connect(self.remove_background)
        bp.settingChanged.connect(self.bg_setting)
        bp.fitRequested.connect(self.fit_background_to_network)
        bp.adjustToggled.connect(lambda on: self.scene.set_mode("bg_adjust" if on else "select"))
        bp.radiiRequested.connect(self.radii_from_background)

    # ================================================================ state
    def _update_title(self):
        name = os.path.basename(self.file_path) if self.file_path else self.net.title
        self.setWindowTitle(f"{name}{' *' if self.modified else ''}  |  myFlowNet {__version__}")

    def _snapshot(self):
        return copy.deepcopy(self.net.to_dict())

    def push_undo(self):
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > 200:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def changed(self, rebuild=True):
        self.modified = True
        if self.solution is not None:
            self.results_stale = True
            self.st_stale.setText("Results are out of date")
        if rebuild:
            self.scene.rebuild(self.net)
            self.apply_results()
        else:
            self.scene.update()
            self.browser.rebuild()
            self._update_info()
        self.props.refresh()
        self._update_title()

    def _restore(self, d):
        sel = self.scene.current_selection()
        bg = self.net.background                 # the background is view state: not undone
        self.net = Network.from_dict(d)
        self.net.background = bg
        self.scene.net = self.net
        self.changed()
        if sel[0]:
            self.scene.select(*sel)

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())

    # ================================================================ editing
    def add_chamber(self, kind, pos: QPointF):
        self.push_undo()
        n = sum(1 for c in self.net.chambers.values() if c.kind == kind) + 1
        params = {}
        if kind == "boundary":
            params = {"p": 1.0e5, "T": 300.0}
        ch = self.net.add_chamber(kind, f"{CHAMBER_NAMES[kind]} {n}", pos.x(), pos.y(), **params)
        self.changed()
        self.scene.select("chamber", ch.id)

    def add_element(self, etype, a, b):
        self.push_undo()
        cls = REGISTRY[etype]
        n = sum(1 for e in self.net.elements.values() if e.type == etype) + 1
        params = {}
        keys = {s.key for s in cls.PARAMS}
        ra = self.net.chambers[a].params.get("radius", 0.0)
        rb = self.net.chambers[b].params.get("radius", 0.0)
        if "r_a" in keys and "r_b" in keys and (ra > 0 or rb > 0):
            params["r_a"] = ra or rb
            params["r_b"] = rb or ra
        el = self.net.add_element(etype, a, b, f"{cls.label.split(' /')[0].split(' (')[0]} {n}", **params)
        self.changed()
        self.scene.select("element", el.id)

    def delete_selected(self):
        items = self.scene.selectedItems()
        if not items:
            return
        self.push_undo()
        from .canvas import ChamberItem, ElementItem
        for it in items:
            if isinstance(it, ElementItem):
                self.net.remove_element(it.eid)
        for it in items:
            if isinstance(it, ChamberItem):
                self.net.remove_chamber(it.cid)
        self.changed()

    def reverse_element(self, eid):
        self.push_undo()
        el = self.net.elements[eid]
        el.a, el.b = el.b, el.a
        if "r_a" in el.params and "r_b" in el.params:
            el.params["r_a"], el.params["r_b"] = el.params["r_b"], el.params["r_a"]
        if el.type == "pipe" and el.params.get("diameter_b", 0) > 0:
            el.params["diameter"], el.params["diameter_b"] = el.params["diameter_b"], el.params["diameter"]
        self.changed()
        self.scene.select("element", eid)

    def duplicate_chamber(self, cid):
        self.push_undo()
        src = self.net.chambers[cid]
        ch = self.net.add_chamber(src.kind, src.name + " copy", src.x + 60, src.y + 60,
                                  **{k: v for k, v in src.params.items() if k != "kind"})
        self.changed()
        self.scene.select("chamber", ch.id)

    def _moved(self, original):
        d = self._snapshot()
        for c in d["chambers"]:
            if c["id"] in original:
                c["x"], c["y"] = original[c["id"]]
        self.undo_stack.append(d)
        self.redo_stack.clear()
        self.modified = True
        self._update_title()

    def set_param(self, kind, oid, key, value):
        self.push_undo()
        obj = self.net.chambers[oid] if kind == "chamber" else self.net.elements[oid]
        obj.params[key] = value
        self.changed(rebuild=(kind == "chamber" and key == "kind"))
        if kind == "chamber" and key == "kind":
            self.scene.select("chamber", oid)

    def set_params(self, kind, ids, key, value):
        """Multi-edit: the same input for several selected items."""
        self.push_undo()
        for oid in ids:
            obj = self.net.chambers.get(oid) if kind == "chamber" else self.net.elements.get(oid)
            if obj is not None and key in obj.params:
                obj.params[key] = value
        sel = self.scene.selection_list()
        self.changed(rebuild=(kind == "chamber" and key == "kind"))
        if kind == "chamber" and key == "kind":
            self.scene.select_many(sel)
        self.logv.log(f"{key} set for {len(ids)} {kind}s")

    def set_connection(self, eid, port, cid):
        el = self.net.elements.get(eid)
        other = el.b if port == "a" else el.a
        if el is None or cid == getattr(el, port):
            return
        if cid == other:
            QMessageBox.warning(self, "Connection", "Both ends of an element cannot be the same chamber.")
            self.props.refresh()
            return
        self.push_undo()
        setattr(el, port, cid)
        self.changed()
        self.scene.select("element", eid)

    def set_name(self, kind, oid, name):
        self.push_undo()
        obj = self.net.chambers[oid] if kind == "chamber" else self.net.elements[oid]
        obj.name = name
        self.changed(rebuild=False)
        self.apply_results()

    def set_model_text(self, field, value):
        self.push_undo()
        setattr(self.net, field, value)
        self.modified = True
        self._update_title()

    # ================================================================ files
    def _confirm_discard(self):
        if not self.modified:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "The model has unsaved changes. Save them first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_model()
        return r == QMessageBox.Discard

    def _set_model(self, net, path=None):
        self.net = net
        self.file_path = path
        self.solution = None
        self.results_stale = False
        self.st_stale.setText("")
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.modified = False
        if net.display_units:
            self.units = UnitSystem(net.display_units)
        self.scene.rebuild(self.net, keep_selection=False)
        self._attach_background(fit_view=True)
        self.scene.clear_results()
        self.view.legend = None
        self.props.show_item(None, None)
        self.t_ch.fill([], [])
        self.t_el.fill([], [])
        self.conv.set_data("Convergence", "Iteration", "Maximum residual", [], log_y=True)
        self.profile.empty()
        self.browser.rebuild()
        self._update_info()
        self._set_status("idle", "Ready")
        self._update_title()
        QTimer.singleShot(0, self.view.fit)

    def new_model(self):
        if not self._confirm_discard():
            return
        net = Network("Untitled")
        self._set_model(net)

    def load_example(self, fn):
        if not self._confirm_discard():
            return
        self._set_model(fn())
        self.logv.log(f"Loaded example: {self.net.title}")
        self.solve()

    def open_model(self):
        if not self._confirm_discard():
            return
        start = self.settings_store.value("lastDir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, "Open model", start, "myFlowNet model (*.json *.mfn)")
        if not path:
            return
        try:
            net = Network.load(path)
        except Exception as ex:
            QMessageBox.critical(self, "Could not open the file", str(ex))
            return
        self.settings_store.setValue("lastDir", os.path.dirname(path))
        self._set_model(net, path)
        self.logv.log(f"Opened {path}")

    def save_model(self, as_new=False):
        path = self.file_path
        if as_new or not path:
            start = self.settings_store.value("lastDir", os.path.expanduser("~"))
            path, _ = QFileDialog.getSaveFileName(self, "Save model", os.path.join(start, self.net.title + ".json"),
                                                  "myFlowNet model (*.json)")
            if not path:
                return False
        self.net.display_units = dict(self.units.choice)
        try:
            self.net.save(path)
        except Exception as ex:
            QMessageBox.critical(self, "Could not save the file", str(ex))
            return False
        self.file_path = path
        self.settings_store.setValue("lastDir", os.path.dirname(path))
        self.modified = False
        self._update_title()
        self.logv.log(f"Saved {path}")
        return True

    def export_csv(self):
        if not self.solution:
            QMessageBox.information(self, "No results", "Solve the network first, then export the results.")
            return
        start = self.settings_store.value("lastDir", os.path.expanduser("~"))
        path, _ = QFileDialog.getSaveFileName(self, "Export results", os.path.join(start, self.net.title + "_results.csv"),
                                              "CSV (*.csv)")
        if not path:
            return
        s = self.solution
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["# myFlowNet results", self.net.title, s.message])
            w.writerow([])
            w.writerow(["Chamber id", "Name", "Type", "p static [Pa]", "p total [Pa]", "Tt [K]", "K [-]",
                        "V_theta [m/s]", "Boundary net outflow [kg/s]", "Arriving Tt [K]"])
            for cid, r in s.chambers.items():
                w.writerow([cid, r["name"], r["kind"], r["p"], r["pt"], r["Tt"], r["K"], r["vtheta"],
                            r.get("flow_out", ""), r.get("T_arrival", "") or ""])
            w.writerow([])
            keys = sorted({k for r in s.elements.values() for k in r["outputs"]})
            w.writerow(["Element id", "Name", "Type", "mdot a->b [kg/s]", "p_a [Pa]", "p_b [Pa]", "Tt in [K]",
                        "Tt out [K]", "choked"] + keys)
            for eid, r in s.elements.items():
                w.writerow([eid, r["name"], r["type"], r["mdot"], r["p_a"], r["p_b"], r["Tt_in"], r["Tt_out"],
                            r["choked"]] + [r["outputs"].get(k, "") for k in keys])
        self.logv.log(f"Results exported to {path}")

    # ================================================================ solve
    def solve(self):
        if self.thread is not None:
            return
        problems = self.net.validate()
        if problems:
            self._set_status("error", "The network cannot be solved yet")
            QMessageBox.warning(self, "Network not ready", "\n".join(problems))
            return
        initial = None
        if self.solution is not None:
            initial = copy.deepcopy(self.solution.state)
        self.history = []
        self.conv.set_data("Convergence", "Iteration", "Maximum residual", [], log_y=True)
        self.thread = QThread()
        self.worker = SolveWorker(self.net.copy(), initial)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._solved)
        self.a_solve.setEnabled(False)
        self.a_stop.setEnabled(True)
        self._set_status("busy", "Solving…")
        self.thread.start()

    def stop_solve(self):
        if self.worker:
            self.worker.stop_event.set()

    def _progress(self, it, rm, rp, dT, dK):
        self.history.append((it, rm, rp))
        self.st_text.setText(f"Solving: iteration {it}, mass residual {rm:.2e}")
        if it % 2 == 0 or it < 10:
            self._plot_history()

    def _plot_history(self):
        if not self.history:
            return
        its = [h[0] for h in self.history]
        series = [("Mass balance (relative)", its, [max(h[1], 1e-16) for h in self.history], "series1")]
        if any(h[2] > 0 for h in self.history):
            series.append(("Pressure-ratio equations", its, [max(h[2], 1e-16) for h in self.history], "series2"))
        self.conv.set_data("Convergence", "Iteration", "Maximum residual", series, log_y=True)

    def _solved(self, sol, err):
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        self.a_solve.setEnabled(True)
        self.a_stop.setEnabled(False)
        if sol is None:
            self._set_status("error", "Solver error")
            self.logv.log("Solver error:\n" + err)
            QMessageBox.critical(self, "Solver error", err[-2000:])
            return
        self.solution = sol
        self.results_stale = False
        self.st_stale.setText("")
        self._plot_history()
        if sol.converged:
            self._set_status("good", f"{sol.message}  ({sol.elapsed:.2f} s)")
        else:
            self._set_status("error", f"{sol.message}. Check the log and the convergence plot.")
        self.logv.log(f"[{self.net.title}] {sol.message} in {sol.elapsed:.2f} s")
        for w in sol.warnings:
            self.logv.log("  warning: " + w)
        self.apply_results()
        self.props.refresh()
        self._on_selection(self.scene.current_selection())

    def _set_status(self, state, text):
        t = self.theme
        col, glyph = {"good": (t["good"], "✓"), "error": (t["critical"], "✕"), "busy": (t["accent"], "●"),
                      "idle": (t["muted"], "●")}[state]
        self.st_icon.setText(glyph)
        self.st_icon.setStyleSheet(f"color: {col}; font-weight: 700; padding-left: 8px;")
        self.st_text.setText(text)

    # ================================================================ results on canvas
    def _color_changed(self, i):
        self.set_contour_quantity(self.color_combo.itemData(i))

    def set_contour_quantity(self, key):
        self.contour.quantity = key
        self._save_contour()
        self.apply_results()

    def edit_contour(self):
        q = QUANTITIES.get(self.contour.quantity, QUANTITIES["none"])
        dlg = LegendDialog(self, self.contour, f"[{self.units.label(q[3])}]" if q[3] != "none" else "")
        if dlg.exec() != LegendDialog.Accepted:
            return
        self.contour = dlg.values()
        self._save_contour()
        self.apply_results()

    def _save_contour(self):
        self.settings_store.setValue("contour", json.dumps(self.contour.to_dict()))
        i = self.color_combo.findData(self.contour.quantity)
        if i >= 0 and i != self.color_combo.currentIndex():
            self.color_combo.setCurrentIndex(i)
        for k, a in self.a_color:
            a.setChecked(k == self.contour.quantity)

    def _contour_values(self):
        """{(kind, id): SI value} of the contour quantity, or ({}, None) when not available."""
        cs = self.contour
        ent, label, fn, unit = QUANTITIES.get(cs.quantity, QUANTITIES["none"])
        if fn is None:
            return {}, None
        s = self.solution
        out = {}
        if ent == "chamber":
            ids = self.net.chambers if cs.quantity in ("ch_r",) else (s.chambers if s else {})
            for cid in ids:
                if cid in self.net.chambers:
                    try:
                        v = fn(self.net, s, cid)
                    except Exception:
                        v = None
                    if v is not None:
                        out[("chamber", cid)] = float(v)
        else:
            ids = self.net.elements if cs.quantity in ("el_D",) else (s.elements if s else {})
            for eid in ids:
                if eid in self.net.elements:
                    try:
                        v = fn(self.net, s, eid)
                    except Exception:
                        v = None
                    if v is not None:
                        out[("element", eid)] = float(v)
        return out, unit

    def apply_results(self):
        s = self.solution
        sc = self.scene
        sc.clear_results()
        self.view.legend = None
        u = self.units
        if s is not None:
            pu, tu = u.label("pressure"), u.label("temperature")
            for cid, it in sc.chambers.items():
                r = s.chambers.get(cid)
                if r is None:
                    continue
                lines = [f"{fmt(u.to_display('pressure', r['p']), 5)} {pu}",
                         f"{fmt(u.to_display('temperature', r['Tt']), 5)} {tu}"]
                if r["kind"] == "inertial" or abs(r["K"]) > 0:
                    lines.append(f"K {fmt(r['K'], 3)}")
                if r.get("vm", 0.0) > 0:
                    lines.append(f"V {fmt(r['vm'], 4)} m/s")
                    it.flow_dir = r.get("phi", 0.0)
                if r["kind"] == "boundary" and r.get("flow_out") is not None and abs(r["flow_out"]) > 0:
                    lines.append(f"{'out' if r['flow_out'] > 0 else 'in'} "
                                 f"{fmt(abs(u.to_display('massflow', r['flow_out'])), 4)} {u.label('massflow')}")
                it.result_lines = lines
                it.update()
            flows = [abs(r["mdot"]) for r in s.elements.values()]
            mmax = max(flows + [1e-12])
            for eid, it in sc.elements.items():
                r = s.elements.get(eid)
                if r is None:
                    continue
                m = r["mdot"]
                it.width = 1.4 + 4.6 * (abs(m) / mmax) ** 0.5
                it.direction = 1 if m >= 0 else -1
                it.flow_label = f"{fmt(abs(u.to_display('massflow', m)), 4)} {u.label('massflow')}"
                it.warn = bool(r["choked"])
                it.setToolTip(f"{r['name']}\nmass flow {fmt(m, 6)} kg/s" + ("\nchoked" if r["choked"] else ""))
                it.update()
        # ---- contour colouring and legend
        cs = self.contour
        vals, unit = self._contour_values()
        if vals:
            disp = {k: u.to_display(unit, v) for k, v in vals.items()}
            lo, hi = (cs.vmin, cs.vmax) if cs.fixed else (min(disp.values()), max(disp.values()))
            if hi <= lo:
                hi = lo + (abs(lo) * 1e-3 or 1.0)
            col = colour_fn(cs, bool(sc.theme.get("canvas_dark")),
                            {"temperature": "temperature"}.get(unit, "pressure"))
            for (kind, oid), v in disp.items():
                t = (v - lo) / (hi - lo)
                if kind == "chamber" and oid in sc.chambers:
                    sc.chambers[oid].fill = col(t)
                    sc.chambers[oid].update()
                elif kind == "element" and oid in sc.elements:
                    sc.elements[oid].color = col(t)
                    sc.elements[oid].update()
            n = cs.levels if cs.levels >= 2 else 8
            labels = [format_value(lo + (hi - lo) * k / n, cs) for k in range(n + 1)]
            title = QUANTITIES[cs.quantity][1].split("–", 1)[-1].strip().capitalize()
            self.view.legend = {"title": title, "unit": u.label(unit) if unit != "none" else "",
                                "labels": labels, "color": col}
            if cs.show_minmax and len(disp) > 1:
                kmin = min(disp, key=disp.get)
                kmax = max(disp, key=disp.get)
                self.view.legend["min"] = kmin
                self.view.legend["max"] = kmax
                for key, tag in ((kmin, "min"), (kmax, "max")):
                    it = (sc.chambers if key[0] == "chamber" else sc.elements).get(key[1])
                    if it is not None:
                        it.extreme = tag
        self.view.viewport().update()
        self._fill_tables()
        self.browser.rebuild()
        self._update_info()

    def _fill_tables(self):
        s = self.solution
        if s is None:
            return
        u = self.units
        pu, tu, mu = u.label("pressure"), u.label("temperature"), u.label("massflow")
        rows = []
        for cid, r in s.chambers.items():
            flow = r.get("flow_out")
            rows.append((cid, [f"C{cid}", r["name"], r["kind"],
                               (fmt(u.to_display("pressure", r["p"]), 6), r["p"]),
                               (fmt(u.to_display("pressure", r["pt"]), 6), r["pt"]),
                               (fmt(u.to_display("temperature", r["Tt"]), 6), r["Tt"]),
                               (fmt(r["K"], 4), r["K"]),
                               (fmt(u.to_display("massflow", flow), 5) if flow is not None else "", flow or 0.0)]))
        self.t_ch.fill(["ID", "Chamber", "Type", f"p static [{pu}]", f"p total [{pu}]", f"Tt [{tu}]", "Swirl K",
                        f"Boundary outflow [{mu}]"], rows)
        rows = []
        for eid, r in s.elements.items():
            o = r["outputs"]
            key = next((k for k in ("Cd", "Mach exit", "K out", "PR overall", "p_dn/p_up", "Mach") if k in o), None)
            extra = f"{key} = {fmt(o[key], 4)}" if key else ""
            el = self.net.elements.get(eid)
            rows.append((eid, [f"E{eid}", r["name"], REGISTRY[r["type"]].label,
                               f"C{el.a} → C{el.b}" if el else "",
                               (fmt(u.to_display("massflow", r["mdot"]), 6), r["mdot"]),
                               (fmt(u.to_display("pressure", r["dp"]), 5), r["dp"]),
                               (fmt(u.to_display("temperature", r["Tt_in"]), 6), r["Tt_in"]),
                               (fmt(u.to_display("temperature", r["Tt_out"]), 6), r["Tt_out"]),
                               ("yes" if r["choked"] else "", 1 if r["choked"] else 0),
                               extra]))
        self.t_el.fill(["ID", "Element", "Type", "Connection", f"ṁ a→b [{mu}]", f"Δp static [{pu}]",
                        f"Tt in [{tu}]", f"Tt out [{tu}]", "Choked", "Key value"], rows)

    # ================================================================ selection
    def _on_selection(self, sel):
        kind, oid = sel
        s = self.solution
        if kind == "element" and s and oid in s.elements and "profile" in s.elements[oid]:
            r = s.elements[oid]
            self.profile.show_profile(r["type"], r["name"], r["profile"], self.units)
        elif kind == "element":
            self.profile.empty()

    def _on_selection_list(self, sel):
        self.props.show_selection(sel)
        self.browser.sync_selection(sel)
        nc = sum(1 for k, _ in sel if k == "chamber")
        self.st_count.setText(f"{nc} chamber(s), {len(sel) - nc} element(s) selected  " if sel else "")
        self._update_info()

    def select_all(self):
        self.scene.select_many([("chamber", c) for c in self.net.chambers] +
                               [("element", e) for e in self.net.elements])

    def filter_selection(self, key):
        if not key:
            return
        sel = self.scene.selection_list()
        if key == "chamber":
            keep = [x for x in sel if x[0] == "chamber"]
        else:
            t = key.split(":", 1)[1]
            keep = [x for x in sel if x[0] == "element" and self.net.elements[x[1]].type == t]
        self.scene.select_many(keep)

    def focus_item(self, kind, oid):
        self.scene.select_many([(kind, oid)], center=True)
        self._raise(self.props_dock)

    def _update_info(self):
        """Info tab: what is selected, how it is connected, warnings."""
        net, s, u = self.net, self.solution, self.units
        sel = self.scene.selection_list()
        t = self.theme
        h = [f"<div style='color:{t['ink']}'>"]
        if not sel:
            nb = sum(1 for c in net.chambers.values() if c.is_boundary)
            h.append(f"<b>{net.title}</b><br>{len(net.chambers)} chambers ({nb} boundaries), "
                     f"{len(net.elements)} elements, {len(net.rotors)} rotor(s).")
            probs = net.validate()
            if probs:
                h.append("<br><br><b>Model check</b><ul>" + "".join(f"<li>{p}</li>" for p in probs) + "</ul>")
            elif s is not None:
                h.append(f"<br><br>Solution: {s.message} ({s.elapsed:.2f} s)"
                         + (" – <i>out of date</i>" if self.results_stale else ""))
                for w in s.warnings[:12]:
                    h.append(f"<br>⚠ {w}")
        for kind, oid in sel[:20]:
            if kind == "chamber":
                ch = net.chambers[oid]
                conn = [e for e in net.elements.values() if oid in (e.a, e.b)]
                h.append(f"<p><b>C{oid} {ch.name}</b> – {ch.kind} chamber, {len(conn)} connection(s): "
                         + ", ".join(f"E{e.id} {e.name}" for e in conn))
                if s and oid in s.chambers:
                    r = s.chambers[oid]
                    h.append(f"<br>p = {fmt(u.to_display('pressure', r['p']), 6)} {u.label('pressure')}, "
                             f"pt = {fmt(u.to_display('pressure', r['pt']), 6)} {u.label('pressure')}, "
                             f"Tt = {fmt(u.to_display('temperature', r['Tt']), 6)} {u.label('temperature')}, "
                             f"K = {fmt(r['K'], 4)}")
                h.append("</p>")
            else:
                el = net.elements[oid]
                cls = REGISTRY[el.type]
                h.append(f"<p><b>E{oid} {el.name}</b> – {cls.label}: C{el.a} {net.chambers[el.a].name} → "
                         f"C{el.b} {net.chambers[el.b].name}<br><span style='color:{t['ink2']}'>"
                         f"{cls.description}</span>")
                if s and oid in s.elements:
                    r = s.elements[oid]
                    h.append(f"<br>ṁ = {fmt(u.to_display('massflow', r['mdot']), 6)} {u.label('massflow')}"
                             f"{', choked' if r['choked'] else ''}")
                h.append("</p>")
        h.append("</div>")
        self.info.setHtml("".join(h))

    # ================================================================ display options
    def _mode_changed(self, mode):
        self.library.sync(mode)
        self.a_select.setChecked(mode == "select")
        if mode.startswith("add:"):
            k = mode.split(":")[1]
            self.view.hint = (f"Click on the canvas to place a {CHAMBER_NAMES[k].lower() if k != 'inertial' else 'inertial chamber'}."
                              " Hold Shift to place several.")
        elif mode.startswith("connect:"):
            et = REGISTRY[mode.split(":")[1]].label
            self.view.hint = f"{et}: from the upstream chamber to the downstream chamber (drag or two clicks). Esc cancels."
        elif mode == "bg_adjust":
            self.view.hint = "Background geometry: drag to move it, turn the wheel to scale it. Esc ends."
        else:
            self.view.hint = ""
        self.bg_panel.set_adjust_checked(mode == "bg_adjust")
        self.view.viewport().update()

    def toggle_labels(self, on):
        self.scene.show_results = bool(on)
        self.settings_store.setValue("canvas/results", "true" if on else "false")
        self.scene.update()

    def set_label_mode(self, key):
        self.scene.label_mode = key
        self.settings_store.setValue("canvas/labels", key)
        for k, a in self.a_label_modes:
            a.setChecked(k == key)
        i = self.label_combo.findData(key)
        if i >= 0:
            self.label_combo.setCurrentIndex(i)
        self.scene.update()

    def set_canvas(self, key):
        custom = None
        if key == "gradient":
            c1 = QColorDialog.getColor(QColor(self.scene.canvas_custom[0] if self.scene.canvas_custom else "#9FB3C8"),
                                       self, "Gradient – top colour")
            if not c1.isValid():
                self._sync_canvas_actions()
                return
            c2 = QColorDialog.getColor(QColor(self.scene.canvas_custom[1] if self.scene.canvas_custom else "#F2F5F8"),
                                       self, "Gradient – bottom colour")
            if not c2.isValid():
                self._sync_canvas_actions()
                return
            custom = (c1.name(), c2.name())
            self.settings_store.setValue("canvas/custom", ",".join(custom))
        self.scene.set_canvas(key, custom)
        self.settings_store.setValue("canvas/preset", key)
        self._sync_canvas_actions()
        self.apply_results()

    def _sync_canvas_actions(self):
        for k, a in self.a_canvas:
            a.setChecked(k == self.scene.canvas_preset)

    def toggle_wireframe(self, on):
        self.scene.wireframe = bool(on)
        self.settings_store.setValue("canvas/wireframe", "true" if on else "false")
        self.scene.update()

    def set_line_scale(self, f):
        self.scene.line_scale = float(f)
        self.settings_store.setValue("canvas/line", float(f))
        self.scene.update()

    def toggle_axes(self, on):
        self.scene.show_axes = bool(on)
        self.settings_store.setValue("canvas/axes", "true" if on else "false")
        self.view.viewport().update()

    def set_app_style(self, key):
        self.theme = APP_THEMES.get(key, CLASSIC)
        self.settings_store.setValue("theme", key)
        apply_theme(QApplication.instance(), self.theme)
        self.scene.set_theme(self.theme)
        self.conv.theme = self.theme
        self.conv.update()
        self.profile.set_theme(self.theme)
        for a in self.findChildren(QAction):
            kind = getattr(a, "icon_kind", None)
            if kind and a is not self.a_solve:
                a.setIcon(tool_icon(kind, self.theme["ink"], 20))
        for k, a in self.a_styles:
            a.setChecked(k == key)
        self.library.build()
        self.library.sync(self.scene.mode)
        self.apply_results()
        self.props.refresh()

    def toggle_theme(self, dark):          # kept for scripts: modern dark / classic
        self.set_app_style("dark" if dark else "classic")

    def reset_layout(self):
        self.restoreState(self._default_state, LAYOUT_VERSION)
        for d in (self.library_dock, self.browser_dock, self.props_dock, self.output_dock):
            d.show()
        self.props_dock.raise_()

    def _raise(self, dock):
        dock.show()
        dock.raise_()

    def _show_tab(self, w):
        self.output_dock.show()
        self.tabs.setCurrentWidget(w)

    def edit_settings(self):
        dlg = SettingsDialog(self, self.net, self.units.choice)
        if dlg.exec() != SettingsDialog.Accepted:
            return
        try:
            rotors, gas, solver, units = dlg.values()
        except ValueError as ex:
            QMessageBox.warning(self, "Invalid value", str(ex))
            return
        self.push_undo()
        self.net.rotors = rotors
        self.net.settings.gas = gas
        for k, v in solver.items():
            setattr(self.net.settings, k, v)
        self.units = UnitSystem(units)
        self.net.display_units = dict(self.units.choice)
        self.settings_store.setValue("units", dict(self.units.choice))
        self.changed()

    def directions_from_drawing(self):
        """Element direction φ = angle of the a → b connection on the canvas (y up).
        Used by momentum chambers to project the through-flow head (cos²θ)."""
        if not self.net.elements:
            return
        self.push_undo()
        for el in self.net.elements.values():
            if "direction" not in el.params:
                continue
            a, b = self.net.chambers[el.a], self.net.chambers[el.b]
            el.params["direction"] = round(math.degrees(math.atan2(-(b.y - a.y), b.x - a.x)), 3)
        self.changed()
        self.logv.log("Element flow directions set from the canvas layout.")

    # ================================================================ background geometry
    def _attach_background(self, fit_view=False):
        """Show the background geometry of the current model (read in a child process, cached)."""
        bgs = self.net.background
        self.cad_loader.cancel()
        self.bg.attach(bgs)
        self._bg_summary = ""
        self._bg_fit_network = False
        self._bg_fit_view = fit_view
        self.a_bg_show.setChecked(bool(bgs and bgs.get("file") and bgs.get("visible", True)))
        if bgs and bgs.get("file"):
            self.bg_panel.set_state(bgs, None, busy=f"Reading {os.path.basename(bgs['file'])}…")
            self.cad_loader.load(bgs["file"], bgs.get("quality", "normal"))
        else:
            self.bg_panel.set_state(None, None)

    def load_background(self):
        cur = (self.net.background or {}).get("file", "")
        start = os.path.dirname(cur) if cur else self.settings_store.value("lastCadDir",
                                                                          os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, "Load background geometry", start, cad.FILE_FILTER)
        if path:
            self.open_background(path)

    def open_background(self, path: str):
        self.settings_store.setValue("lastCadDir", os.path.dirname(path))
        first = not (self.net.background and self.net.background.get("file"))
        settings = merged_settings(self.net.background)
        settings["file"] = os.path.abspath(path)
        settings["visible"] = True
        self.net.background = settings
        self.modified = True
        self._update_title()
        self._attach_background(fit_view=first)
        self._bg_fit_network = first
        self.show_background_panel()

    def remove_background(self):
        if not self.net.background:
            return
        self.cad_loader.cancel()
        self.net.background = None
        self.bg.attach(None)
        self.bg_panel.set_state(None, None)
        self.a_bg_show.setChecked(False)
        self.st_coord.setText("")
        if self.scene.mode == "bg_adjust":
            self.scene.set_mode("select")
        self.modified = True
        self._update_title()
        self.view.viewport().update()

    def show_background_panel(self):
        self.bg_dock.show()
        self.bg_dock.raise_()

    def _bg_loaded(self, path, geom):
        bgs = self.net.background
        if not bgs or os.path.normcase(os.path.abspath(bgs.get("file", ""))) != os.path.normcase(os.path.abspath(path)):
            return                                  # a newer request superseded this one
        self.bg.set_geometry(geom)
        if self._bg_fit_network:
            self._bg_fit_network = False
            self.fit_background_to_network()
        self._bg_summary = geom.summary()
        self.bg_panel.set_state(bgs, self._bg_summary)
        self.scene.ensure_rect(self.bg.scene_bounds())
        self.logv.log(f"Background geometry {os.path.basename(path)}: {self._bg_summary}")
        if self.thread is None:
            self._set_status("idle", f"Background geometry: {os.path.basename(path)}")
        if self._bg_fit_view:
            self._bg_fit_view = False
            QTimer.singleShot(0, self.view.fit)
        self.view.viewport().update()

    def _bg_progress(self, text):
        self.bg_panel.set_state(self.net.background, None, busy=text)
        self.st_text.setText(text)

    def _bg_failed(self, path, msg, missing):
        self.bg_panel.set_state(self.net.background, None, busy="The geometry could not be read.")
        self.logv.log(f"Background geometry {path}: {msg}")
        self._set_status("idle", "Ready")
        if not missing:
            QMessageBox.warning(self, "Background geometry", msg)
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("CAD reader needed")
        box.setText(msg)
        b_inst = box.addButton("Install cadquery-ocp now", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is b_inst:
            self.install_cad_backend()

    def install_cad_backend(self):
        if self.pip is not None:
            return
        self.logv.log("Installing cadquery-ocp (python -m pip install cadquery-ocp)…")
        self._set_status("busy", "Installing the CAD reader (cadquery-ocp)…")
        pr = QProcess(self)
        pr.setProcessChannelMode(QProcess.MergedChannels)
        pr.readyReadStandardOutput.connect(
            lambda: [self.logv.log("  " + ln) for ln in
                     bytes(pr.readAllStandardOutput()).decode("utf-8", "replace").splitlines() if ln.strip()])

        def done(code, _status):
            self.pip = None
            if code == 0:
                self._set_status("good", "CAD reader installed")
                if self.net.background and self.net.background.get("file"):
                    self._attach_background()
            else:
                self._set_status("error", "Installing cadquery-ocp failed - see the log")
                QMessageBox.warning(self, "Installation failed",
                                    "pip could not install cadquery-ocp (see the Log tab). Try "
                                    "'python -m pip install gmsh' instead, or convert the model to STL.")
        pr.finished.connect(done)
        self.pip = pr
        pr.start(sys.executable, ["-m", "pip", "install", "cadquery-ocp"])

    def bg_setting(self, key, value):
        bgs = self.net.background
        if not bgs:
            return
        if key in ("yaw", "pitch") and bgs.get("follow", True):
            new = dict(bgs)
            new[key] = value
            self._follow_view(bgs, new)
        if key == "unit_scale":
            old = float(bgs.get("unit_scale", 1.0) or 1.0)
            bgs["scale"] = float(bgs.get("scale", 1.0)) * old / float(value)   # keep the drawing size
        bgs[key] = value
        self.modified = True
        self._update_title()
        if key == "quality":
            self._attach_background()
            return
        if key in VIEW_KEYS or key == "unit_scale":
            self.bg.rebuild_view(delayed=True)
        if key == "visible":
            self.a_bg_show.setChecked(bool(value))
        if key == "scale":
            self.bg.placement_done()
        self.view.viewport().update()

    def _follow_view(self, old: dict, new: dict):
        """Keep the chambers on the same points of the cut plane when the view turns: the cut plane is
        mapped affinely onto the canvas, so the change of view is an affine map of the canvas."""
        a0 = view_rotation(float(old.get("yaw", 0.0)), float(old.get("pitch", 0.0)))[:2, :2]
        a1 = view_rotation(float(new.get("yaw", 0.0)), float(new.get("pitch", 0.0)))[:2, :2]
        if abs(np.linalg.det(a0)) < 1e-6 or np.allclose(a0, a1):
            return
        m = a1 @ np.linalg.inv(a0)
        s = float(old.get("scale", 1.0)) or 1.0
        ox, oy = (float(v) for v in old.get("offset", [0.0, 0.0]))

        def move(x, y):
            u, v = (x - ox) / s, (oy - y) / s
            u2, v2 = m @ (u, v)
            return float(ox + s * u2), float(oy - s * v2)
        for ch in self.net.chambers.values():
            ch.x, ch.y = move(ch.x, ch.y)
        for snap in self.undo_stack + self.redo_stack:     # keep undo consistent with the view
            for c in snap.get("chambers", []):
                c["x"], c["y"] = move(c["x"], c["y"])
        self.scene.rebuild(self.net)
        self.apply_results()

    def toggle_background(self, on):
        bgs = self.net.background
        if not bgs or not bgs.get("file"):
            self.a_bg_show.setChecked(False)
            self.load_background()
            return
        bgs["visible"] = bool(on)
        self.bg_panel.set_state(bgs, self._bg_summary)
        self.view.viewport().update()

    def fit_background_to_network(self):
        if not self.bg.has_geometry():
            return
        r = QRectF()
        for it in self.scene.chambers.values():
            r = r.united(it.mapRectToScene(it.shape().boundingRect()))
        if r.isEmpty():
            r = self.view.mapToScene(self.view.viewport().rect()).boundingRect().adjusted(80, 80, -80, -80)
        else:
            r = r.adjusted(-0.12 * r.width() - 40, -0.12 * r.height() - 40, 0.12 * r.width() + 40,
                           0.12 * r.height() + 40)
        self.bg.fit_into(r)
        self.bg.placement_done()

    def _bg_placement_changed(self):
        self.modified = True
        self._update_title()
        if self.net.background:
            self.bg_panel.set_state(self.net.background, self._bg_summary)

    def _cursor_moved(self, pt):
        if not self.bg.is_visible():
            if self.st_coord.text():
                self.st_coord.setText("")
            return
        pc = self.bg.plane_coords(pt)
        if pc is None:
            self.st_coord.setText("")
            return
        txt = f"axial {pc[0]:.1f} mm   r {abs(pc[1]):.1f} mm"
        self.st_coord.setText(txt + "  ")
        self.bg_panel.set_cursor_text("Cursor on the cut plane: " + txt)

    def radii_from_background(self):
        """Chamber reference radius = radial coordinate of its position in the cut plane."""
        if not self.bg.has_geometry():
            QMessageBox.information(self, "No background geometry",
                                    "Load a background geometry first (File → Load background geometry).")
            return
        sel = [it.cid for it in self.scene.selectedItems() if isinstance(it, ChamberItem)]
        ids = sel or list(self.net.chambers)
        self.push_undo()
        lines = []
        for cid in ids:
            ch = self.net.chambers[cid]
            pc = self.bg.plane_coords(QPointF(ch.x, ch.y))
            if pc is None:
                continue
            r = round(float(abs(pc[1])) / 1000.0, 6)
            ch.params["radius"] = r
            lines.append(f"  {ch.name}: r = {r * 1000:.1f} mm")
        self.changed(rebuild=False)
        self.logv.log(f"Chamber radii from the background geometry ({len(lines)} chambers):\n" + "\n".join(lines))
        self._set_status("good", f"Reference radius set for {len(lines)} chamber(s) from the geometry")

    def check_model(self):
        msgs = self.net.validate()
        if msgs:
            QMessageBox.warning(self, "Connectivity", "\n".join(msgs))
        else:
            QMessageBox.information(self, "Connectivity", "Every chamber is connected to a boundary.")

    def show_theory(self):
        TheoryDialog(self).exec()

    def about(self):
        QMessageBox.about(self, "About myFlowNet",
                          f"<b>myFlowNet {__version__}</b><br>1D flow network solver for gas turbine secondary "
                          "air systems.<br><br>Elements: orifices and rotating holes, K-losses, compressible pipes "
                          "with friction, heat transfer and rotation, labyrinth seals, free/forced vortices, "
                          "rotor-stator cavities, fixed flows and disc pumping.<br><br>Background CAD geometry: STEP / IGES / "
                          "BREP / STL, meridional section or 3D view, snapping and chamber radii from the "
                          "geometry.<br><br>See Help → Theory guide.")

    def closeEvent(self, e):
        if not self._confirm_discard():
            e.ignore()
            return
        self.settings_store.setValue("geometry", self.saveGeometry())
        self.settings_store.setValue("windowState", self.saveState(LAYOUT_VERSION))
        self.cad_loader.cancel()
        if self.thread is not None:
            self.stop_solve()
            self.thread.quit()
            self.thread.wait(2000)
        e.accept()


def run(argv=None):
    argv = argv if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("myFlowNet")
    net, path = None, None
    if len(argv) > 1 and os.path.exists(argv[1]):
        path = argv[1]
        net = Network.load(path)
    w = MainWindow(net, path)
    w.show()
    if net is None:
        QTimer.singleShot(200, w.solve)
    return app.exec()
