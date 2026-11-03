"""Background CAD geometry of the network canvas: drawing layer, file loader and side panel.

The geometry is read in a separate process (``python -m myflownet.cad``), projected with
:mod:`myflownet.geomview` and drawn behind the network in two layers:

* a raster layer (shaded faces + CAD edges, painter's algorithm), re-rendered when the zoom
  asks for more resolution;
* a vector layer (section faces and outlines of the cut plane), always sharp.

Canvas placement: scene = (ox + s·u, oy − s·v) with (u, v) the view coordinates in mm.
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PySide6.QtCore import QObject, QPointF, QProcess, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget)

from .. import cad
from ..geomview import GeometryView, ViewSpec

BG_DEFAULTS = {
    "file": "", "quality": "normal", "unit_scale": 1.0,
    "axis": "x", "origin": [0.0, 0.0, 0.0], "theta": 0.0, "yaw": 0.0, "pitch": 0.0,
    "cut": True, "upper_half": True,
    "show_faces": True, "show_edges": True, "show_section": True,
    "opacity": 0.9, "surface_opacity": 0.45, "scale": 1.0, "offset": [0.0, 0.0],
    "visible": True, "snap": True, "follow": True,
}
VIEW_KEYS = ("axis", "origin", "theta", "yaw", "pitch", "cut", "upper_half", "show_faces", "show_edges",
             "show_section")
MAX_IMAGE_PX = 4096

# muted part colours (light / dark canvas)
PART_LIGHT = ["#A9BCCD", "#CDBFA6", "#B3C9AE", "#C3B3CF", "#D0B2AE", "#A8C8C8", "#C9C3A3", "#B6B9D3"]
PART_DARK = ["#3E5466", "#5E5440", "#46593F", "#54475F", "#614643", "#3F5C5C", "#5A5641", "#45495F"]


def merged_settings(d: dict | None) -> dict:
    out = dict(BG_DEFAULTS)
    if d:
        out.update(d)
    return out


def render_view_image(view: GeometryView, res: float, theme: dict, max_px: int = MAX_IMAGE_PX):
    """Rasterise faces and edges of a GeometryView. Returns (QImage, (u0, v0, u1, v1), res)."""
    pts = [a.reshape(-1, 2) for a in (view.tri2d, view.seg2d) if len(a)]
    if not pts:
        return None, None, 0.0
    allp = np.vstack(pts)
    u0, v0 = allp.min(axis=0)
    u1, v1 = allp.max(axis=0)
    pad = 0.002 * max(u1 - u0, v1 - v0, 1e-9)
    u0, v0, u1, v1 = u0 - pad, v0 - pad, u1 + pad, v1 + pad
    span = max(u1 - u0, v1 - v0, 1e-9)
    res = float(min(res, max_px / span))
    w, h = max(1, int(np.ceil((u1 - u0) * res))), max(1, int(np.ceil((v1 - v0) * res)))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    dark = bool(theme.get("canvas_dark", theme.get("name") == "dark"))
    base = PART_DARK if dark else PART_LIGHT
    levels = 24
    lut = []
    for hexcol in base:
        c = QColor(hexcol)
        row = []
        for k in range(levels):
            f = 0.62 + 0.50 * k / (levels - 1) if not dark else 0.55 + 0.75 * k / (levels - 1)
            row.append(QColor(min(255, int(c.red() * f)), min(255, int(c.green() * f)), min(255, int(c.blue() * f))))
        lut.append(row)
    edge = QColor(theme["ink2"] if not dark else "#9AA6B1")
    edge.setAlpha(150 if not dark else 130)
    pen = QPen(edge, 1.1)
    pen.setCosmetic(True)
    # device coordinates: x = (u - u0) * res, y = (v1 - v) * res
    T = view.tri2d.astype(float)
    S = view.seg2d.astype(float)
    tx = (T[..., 0] - u0) * res
    ty = (v1 - T[..., 1]) * res
    sx = (S[..., 0] - u0) * res
    sy = (v1 - S[..., 1]) * res
    shade = np.clip((view.tri_shade * (levels - 1)).round().astype(int), 0, levels - 1)
    part = view.tri_part % len(base)
    p = QPainter(img)
    p.setPen(Qt.NoPen)
    n_tri = view.n_tri
    aa = False
    p.setRenderHint(QPainter.Antialiasing, False)
    for idx in view.order.tolist():
        if idx < n_tri:
            if aa:
                p.setRenderHint(QPainter.Antialiasing, False)
                p.setPen(Qt.NoPen)
                aa = False
            p.setBrush(lut[part[idx]][shade[idx]])
            x, y = tx[idx], ty[idx]
            p.drawPolygon(QPolygonF([QPointF(x[0], y[0]), QPointF(x[1], y[1]), QPointF(x[2], y[2])]))
        else:
            j = idx - n_tri
            if not aa:
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setPen(pen)
                aa = True
            p.drawLine(QPointF(sx[j, 0], sy[j, 0]), QPointF(sx[j, 1], sy[j, 1]))
    p.end()
    return img, (u0, v0, u1, v1), res


class BackgroundLayer(QObject):
    """Holds the background settings (a dict stored in the model), the geometry and its view."""
    changed = Signal()
    placementChanged = Signal()

    def __init__(self, scene):
        super().__init__()
        self.scene = scene
        self.settings: dict | None = None
        self.geom = None
        self.view: GeometryView | None = None
        self._img = None
        self._img_box = None
        self._img_res = 0.0
        self._want_res = 0.0
        self._caps = []
        self._outline = QPainterPath()
        self._wire = QPainterPath()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render_now)
        self._view_timer = QTimer(self)
        self._view_timer.setSingleShot(True)
        self._view_timer.setInterval(60)
        self._view_timer.timeout.connect(self.rebuild_view)

    # ------------------------------------------------------------- state
    def has_geometry(self) -> bool:
        return self.view is not None and self.settings is not None

    def is_visible(self) -> bool:
        return self.has_geometry() and bool(self.settings.get("visible", True))

    def attach(self, settings: dict | None):
        """Use `settings` (the model's background dict) - geometry must be set separately."""
        self.settings = settings
        self.geom = None
        self.view = None
        self._img = None
        self._caps, self._outline, self._wire = [], QPainterPath(), QPainterPath()
        self.scene.update()

    def set_geometry(self, geom):
        self.geom = geom
        self.rebuild_view()

    def _geom_scaled(self):
        f = float(self.settings.get("unit_scale", 1.0) or 1.0)
        return self.geom.scaled(f)

    def rebuild_view(self, delayed: bool = False):
        if delayed:
            self._view_timer.start()
            return
        if self.geom is None or self.settings is None:
            self.view = None
            self.scene.update()
            return
        s = merged_settings(self.settings)
        self.view = GeometryView(self._geom_scaled(), ViewSpec.from_dict(s), bool(s["show_faces"]),
                                 bool(s["show_edges"]), bool(s["show_section"]))
        self._make_paths()
        self._img = None
        self._img_res = 0.0
        self.changed.emit()
        self.scene.update()

    def _make_paths(self):
        caps = {}
        outline = QPainterPath()
        for pts, closed, part in self.view.loops:
            poly = QPolygonF([QPointF(float(x), float(y)) for x, y in pts])
            if closed:
                path = caps.setdefault(part, QPainterPath())
                path.setFillRule(Qt.OddEvenFill)
                path.addPolygon(poly)
                path.closeSubpath()
                outline.addPolygon(poly)
                outline.closeSubpath()
            else:
                outline.addPolygon(poly)
        self._caps = sorted(caps.items())
        self._outline = outline
        wire = QPainterPath()                 # wireframe models (2D drawings): vector edges
        if self.view.n_tri == 0:
            for a, b in self.view.seg2d.astype(float):
                wire.moveTo(a[0], a[1])
                wire.lineTo(b[0], b[1])
        self._wire = wire

    def set_theme(self, theme):
        self._img = None
        self._img_res = 0.0
        self.scene.update()

    # ------------------------------------------------------------- placement
    @property
    def scale(self) -> float:
        return float(self.settings.get("scale", 1.0)) or 1.0

    @property
    def offset(self):
        o = self.settings.get("offset", [0.0, 0.0])
        return float(o[0]), float(o[1])

    def view_to_scene(self, u, v) -> QPointF:
        ox, oy = self.offset
        return QPointF(ox + self.scale * u, oy - self.scale * v)

    def scene_to_view(self, pt: QPointF):
        ox, oy = self.offset
        return (pt.x() - ox) / self.scale, (oy - pt.y()) / self.scale

    def plane_coords(self, pt: QPointF):
        """(axial, radial) of a canvas point in the cut plane [mm]."""
        if not self.has_geometry():
            return None
        return self.view.view_to_plane(*self.scene_to_view(pt))

    def scene_bounds(self) -> QRectF:
        if not self.has_geometry():
            return QRectF()
        u0, v0, u1, v1 = self.view.bounds
        return QRectF(self.view_to_scene(u0, v1), self.view_to_scene(u1, v0)).normalized()

    def snap(self, pt: QPointF, tol_scene: float):
        if not self.is_visible() or not self.settings.get("snap", True):
            return None
        u, v = self.scene_to_view(pt)
        hit = self.view.nearest_snap(u, v, tol_scene / self.scale)
        return self.view_to_scene(*hit) if hit else None

    def fit_into(self, rect: QRectF):
        if not self.has_geometry():
            return
        u0, v0, u1, v1 = self.view.bounds
        du, dv = max(u1 - u0, 1e-9), max(v1 - v0, 1e-9)
        # cover the whole rectangle: grow its smaller side to the aspect ratio of the geometry
        s = max(rect.width() / du, rect.height() / dv)
        self.settings["scale"] = float(s)
        c = rect.center()
        self.settings["offset"] = [float(c.x() - s * (u0 + u1) / 2), float(c.y() + s * (v0 + v1) / 2)]
        self.scene.update()
        self.changed.emit()

    def move_by(self, dx, dy):
        ox, oy = self.offset
        self.settings["offset"] = [ox + dx, oy + dy]
        self.scene.update()

    def placement_done(self):
        self.scene.ensure_rect(self.scene_bounds())
        self.placementChanged.emit()

    def scale_about(self, pt: QPointF, f: float):
        ox, oy = self.offset
        self.settings["scale"] = self.scale * f
        self.settings["offset"] = [pt.x() + (ox - pt.x()) * f, pt.y() + (oy - pt.y()) * f]
        self.scene.update()

    # ------------------------------------------------------------- painting
    def _render_now(self):
        if not self.has_geometry():
            return
        img, box, res = render_view_image(self.view, self._want_res, self.scene.theme)
        self._img, self._img_box, self._img_res = img, box, res
        self.scene.update()

    def paint(self, p: QPainter, rect: QRectF):
        if not self.is_visible():
            return
        s = self.scale
        lod = abs(p.worldTransform().m11()) or 1.0
        try:
            dpr = p.device().devicePixelRatioF()
        except Exception:
            dpr = 1.0
        need = s * lod * dpr
        cap = MAX_IMAGE_PX / max(self.view.bounds[2] - self.view.bounds[0],
                                 self.view.bounds[3] - self.view.bounds[1], 1e-9)
        raster = self.view.n_tri > 0
        if raster and (self._img is None or (self._img_res < 0.7 * need and self._img_res < 0.98 * cap)):
            want = min(1.3 * need, cap)
            if not self._render_timer.isActive() or abs(want - self._want_res) > 0.05 * want:
                self._want_res = want
                self._render_timer.start(0 if self._img is None else 150)
        opacity = float(self.settings.get("opacity", 0.9))
        surf = float(self.settings.get("surface_opacity", 0.45))
        dark = bool(self.scene.theme.get("canvas_dark", self.scene.theme.get("name") == "dark"))
        p.save()
        if raster and self._img is not None and self._img_box is not None:
            # without a section the surfaces are the whole picture: draw them at full opacity
            p.setOpacity(opacity * (surf if (self._caps or not self._outline.isEmpty()) else 1.0))
            u0, v0, u1, v1 = self._img_box
            target = QRectF(self.view_to_scene(u0, v1), self.view_to_scene(u1, v0))
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawImage(target, self._img)
        p.setOpacity(opacity)
        if self._caps or not self._outline.isEmpty() or not self._wire.isEmpty():
            ox, oy = self.offset
            p.translate(ox, oy)
            p.scale(s, -s)
            base = PART_DARK if dark else PART_LIGHT
            for part, path in self._caps:
                c = QColor(base[part % len(base)])
                c = c.darker(118) if not dark else c.lighter(135)
                c.setAlpha(240)
                p.fillPath(path, c)
            pen = QPen(QColor("#2E3943" if not dark else "#C9D2DA"), 1.25)
            pen.setCosmetic(True)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.drawPath(self._outline)
            if not self._wire.isEmpty():
                wpen = QPen(QColor("#4A5661" if not dark else "#AEB9C3"), 1.15)
                wpen.setCosmetic(True)
                p.setPen(wpen)
                p.drawPath(self._wire)
        p.restore()


# =========================================================================== loader
class CadLoader(QObject):
    """Reads CAD files in a child process (cached), so the editor stays responsive."""
    loaded = Signal(str, object)           # path, CadGeometry
    failed = Signal(str, str, bool)        # path, message, backend missing
    progress = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self._path = None
        self._out = None
        self._buf = ""
        self._last = ""

    def busy(self) -> bool:
        return self.proc is not None

    def load(self, path: str, quality: str = "normal"):
        self.cancel()
        if not os.path.isfile(path):
            self.failed.emit(path, f"File not found:\n{path}", False)
            return
        g = cad.load_cached(path, quality)
        if g is not None:
            self.loaded.emit(path, g)
            return
        self._path, self._out, self._buf, self._last = path, cad.cache_file(path, quality), "", ""
        pr = QProcess(self)
        pr.setProcessChannelMode(QProcess.MergedChannels)
        pkg_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pr.setWorkingDirectory(pkg_parent)
        pr.readyReadStandardOutput.connect(self._read)
        pr.finished.connect(self._finished)
        self.proc = pr
        self.progress.emit(f"Reading {os.path.basename(path)}…")
        pr.start(sys.executable, ["-m", "myflownet.cad", path, self._out, quality])

    def cancel(self):
        if self.proc is not None:
            pr = self.proc
            self.proc = None
            pr.finished.disconnect()
            pr.kill()
            pr.waitForFinished(2000)

    def _read(self):
        if self.proc is None:
            return
        self._buf += bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line.startswith("PROGRESS"):
                parts = line.split(" ", 2)
                pct = int(float(parts[1]) * 100) if len(parts) > 1 else 0
                self.progress.emit(f"{parts[2] if len(parts) > 2 else ''}… {pct}%")
            elif line:
                self._last = line

    def _finished(self, code, status):
        self._read()
        path, out, last = self._path, self._out, (self._last + " " + self._buf).strip()
        self.proc = None
        if not last and out and os.path.isfile(out + ".log"):     # child without stdout (pythonw)
            try:
                lines = [ln.strip() for ln in open(out + ".log", encoding="utf-8", errors="replace")
                         if ln.strip() and not ln.startswith("PROGRESS")]
                last = lines[-1] if lines else ""
            except OSError:
                pass
        if code == 0 and out and os.path.isfile(out):
            try:
                g = cad.CadGeometry.load(out)
            except Exception as ex:
                self.failed.emit(path, str(ex), False)
                return
            self.loaded.emit(path, g)
            return
        if last.startswith("BACKEND_MISSING"):
            self.failed.emit(path, last[len("BACKEND_MISSING "):].replace("\\n", "\n"), True)
        elif last.startswith("ERROR"):
            self.failed.emit(path, last[6:], False)
        else:
            self.failed.emit(path, last or f"The CAD reader stopped (exit code {code}).", False)


# =========================================================================== panel
def _slider(lo, hi, val):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(int(round(val)))
    s.setMinimumWidth(110)
    return s


class BackgroundPanel(QWidget):
    """Side panel: file, section and view, display, placement and tools."""
    loadRequested = Signal()
    removeRequested = Signal()
    settingChanged = Signal(str, object)       # key, value
    fitRequested = Signal()
    adjustToggled = Signal(bool)
    radiiRequested = Signal()
    reloadRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sync = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(6)

        # ---- file
        self.file_label = QLabel("No background geometry")
        self.file_label.setObjectName("titleLabel")
        self.file_label.setWordWrap(True)
        lay.addWidget(self.file_label)
        self.info = QLabel("Load a STEP, IGES or STL model of the engine to draw the network on top of "
                           "its meridional section or a 3D view.")
        self.info.setWordWrap(True)
        self.info.setObjectName("hintLabel")
        lay.addWidget(self.info)
        row = QHBoxLayout()
        self.b_load = QPushButton("Load geometry…")
        self.b_load.clicked.connect(self.loadRequested)
        self.b_remove = QPushButton("Remove")
        self.b_remove.clicked.connect(self.removeRequested)
        row.addWidget(self.b_load)
        row.addWidget(self.b_remove)
        row.addStretch(1)
        lay.addLayout(row)

        self.controls = QWidget()
        cl = QVBoxLayout(self.controls)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        lay.addWidget(self.controls)

        # ---- section and view
        cl.addWidget(self._title("Section and view"))
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignLeft)
        f.setHorizontalSpacing(10)
        self.axis = QComboBox()
        for k in ("x", "y", "z", "-x", "-y", "-z"):
            self.axis.addItem(k.upper().replace("-", "−"), k)
        self.axis.setToolTip("Engine (rotation) axis of the CAD model. It is drawn horizontally.")
        self.axis.currentIndexChanged.connect(lambda i: self._emit("axis", self.axis.itemData(i)))
        f.addRow("Engine axis", self.axis)
        self.theta, self.theta_s = self._angle_row(f, "Cut angle θ", 0, 360, "theta",
                                                   "Angle of the meridional cut plane about the engine axis.")
        self.yaw, self.yaw_s = self._angle_row(f, "Turn (yaw)", -80, 80, "yaw",
                                               "Turns the model about the vertical canvas axis (3D view).")
        self.pitch, self.pitch_s = self._angle_row(f, "Tilt (pitch)", -80, 80, "pitch",
                                                   "Tilts the model about the horizontal canvas axis (3D view).")
        cl.addLayout(f)
        row = QHBoxLayout()
        b = QPushButton("Meridional")
        b.setToolTip("Look straight at the cut plane: canvas = axial × radial coordinates")
        b.clicked.connect(lambda: self._preset(0, 0))
        row.addWidget(b)
        b = QPushButton("3D view")
        b.setToolTip("Turned and tilted view of the cut model")
        b.clicked.connect(lambda: self._preset(-35, 22))
        row.addWidget(b)
        row.addStretch(1)
        cl.addLayout(row)
        self.follow = QCheckBox("Network follows the section when the view turns")
        self.follow.setToolTip("Chambers stay on the same points of the cut plane when yaw / tilt change")
        self.follow.toggled.connect(lambda v: self._emit("follow", v))
        cl.addWidget(self.follow)
        self.cut = QCheckBox("Cut at the section plane")
        self.cut.toggled.connect(lambda v: self._emit("cut", v))
        self.upper = QCheckBox("Upper half only (r ≥ 0)")
        self.upper.toggled.connect(lambda v: self._emit("upper_half", v))
        cl.addWidget(self.cut)
        cl.addWidget(self.upper)

        # ---- display
        cl.addWidget(self._title("Display"))
        g = QGridLayout()
        self.show_section = QCheckBox("Section")
        self.show_faces = QCheckBox("Surfaces")
        self.show_edges = QCheckBox("Edges")
        for i, (w, k) in enumerate(((self.show_section, "show_section"), (self.show_faces, "show_faces"),
                                    (self.show_edges, "show_edges"))):
            w.toggled.connect(lambda v, k=k: self._emit(k, v))
            g.addWidget(w, 0, i)
        cl.addLayout(g)
        f = QFormLayout()
        self.opacity = _slider(10, 100, 90)
        self.opacity.valueChanged.connect(lambda v: self._emit("opacity", v / 100.0))
        f.addRow("Opacity", self.opacity)
        self.surf_op = _slider(0, 100, 45)
        self.surf_op.setToolTip("Strength of the shaded surfaces behind the section")
        self.surf_op.valueChanged.connect(lambda v: self._emit("surface_opacity", v / 100.0))
        f.addRow("Surfaces behind", self.surf_op)
        self.quality = QComboBox()
        for k, lab in (("coarse", "Coarse"), ("normal", "Normal"), ("fine", "Fine")):
            self.quality.addItem(lab, k)
        self.quality.setToolTip("Tessellation fineness (re-reads the file)")
        self.quality.currentIndexChanged.connect(lambda i: self._emit("quality", self.quality.itemData(i)))
        f.addRow("Tessellation", self.quality)
        self.unit = QComboBox()
        for lab, v in (("mm", 1.0), ("m", 1000.0), ("inch", 25.4), ("cm", 10.0)):
            self.unit.addItem(lab, v)
        self.unit.setToolTip("Length unit of the file. STEP / IGES are converted to mm automatically; "
                             "STL has no unit.")
        self.unit.currentIndexChanged.connect(lambda i: self._emit("unit_scale", self.unit.itemData(i)))
        f.addRow("File unit", self.unit)
        cl.addLayout(f)
        self.visible = QCheckBox("Show background geometry")
        self.visible.toggled.connect(lambda v: self._emit("visible", v))
        cl.addWidget(self.visible)

        # ---- placement
        cl.addWidget(self._title("Placement on the canvas"))
        f = QFormLayout()
        self.scale = QDoubleSpinBox()
        self.scale.setDecimals(4)
        self.scale.setRange(1e-4, 1e4)
        self.scale.setSuffix(" px/mm")
        self.scale.setKeyboardTracking(False)
        self.scale.valueChanged.connect(lambda v: self._emit("scale", v))
        f.addRow("Scale", self.scale)
        cl.addLayout(f)
        row = QHBoxLayout()
        b = QPushButton("Fit to network")
        b.setToolTip("Scale and move the geometry so that it covers the network drawing")
        b.clicked.connect(self.fitRequested)
        row.addWidget(b)
        self.b_adjust = QPushButton("Move / scale on canvas")
        self.b_adjust.setCheckable(True)
        self.b_adjust.setToolTip("Drag on the canvas to move the geometry, turn the wheel to scale it. Esc ends.")
        self.b_adjust.toggled.connect(self.adjustToggled)
        row.addWidget(self.b_adjust)
        row.addStretch(1)
        cl.addLayout(row)

        # ---- tools
        cl.addWidget(self._title("Network tools"))
        self.snap = QCheckBox("Snap chambers to geometry points")
        self.snap.setToolTip("While moving or placing a chamber, snap it to CAD vertices and corners of the "
                             "section outline (like mapping chambers to CAD vertices in Flow Simulator).")
        self.snap.toggled.connect(lambda v: self._emit("snap", v))
        cl.addWidget(self.snap)
        b = QPushButton("Set chamber radii from the geometry")
        b.setToolTip("Reference radius of each chamber = its radial position in the cut plane "
                     "(selected chambers, or all when none is selected)")
        b.clicked.connect(self.radiiRequested)
        row = QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        cl.addLayout(row)
        self.cursor = QLabel("")
        self.cursor.setObjectName("hintLabel")
        cl.addWidget(self.cursor)
        lay.addStretch(1)
        self.set_state(None, None)

    # ------------------------------------------------------------- helpers
    def _title(self, text):
        lab = QLabel(text)
        lab.setObjectName("sectionLabel")
        return lab

    def _angle_row(self, form, label, lo, hi, key, tip):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        sl = _slider(lo, hi, 0)
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(1)
        sp.setSuffix("°")
        sp.setKeyboardTracking(False)
        sp.setFixedWidth(78)
        sl.valueChanged.connect(lambda v: (not self._sync) and sp.setValue(v))
        sp.valueChanged.connect(lambda v: self._angle_changed(key, v, sl))
        h.addWidget(sl, 1)
        h.addWidget(sp)
        w.setToolTip(tip)
        form.addRow(label, w)
        return sp, sl

    def _angle_changed(self, key, v, sl):
        if not self._sync:
            self._sync = True
            sl.setValue(int(round(v)))
            self._sync = False
        self._emit(key, float(v))

    def _emit(self, key, value):
        if not self._sync:
            self.settingChanged.emit(key, value)

    def _preset(self, yaw, pitch):
        self._sync = True
        self.yaw.setValue(yaw)
        self.yaw_s.setValue(yaw)
        self.pitch.setValue(pitch)
        self.pitch_s.setValue(pitch)
        self._sync = False
        self.settingChanged.emit("yaw", float(yaw))
        self.settingChanged.emit("pitch", float(pitch))

    def set_cursor_text(self, text):
        self.cursor.setText(text)

    def set_state(self, settings: dict | None, summary: str | None, busy: str = ""):
        """Refresh all widgets from the model's background settings."""
        self._sync = True
        has = settings is not None and bool(settings.get("file"))
        self.controls.setVisible(has)
        self.b_remove.setEnabled(has)
        if not has:
            self.file_label.setText("No background geometry")
            self.info.setText(busy or "Load a STEP, IGES or STL model of the engine to draw the network on top "
                                      "of its meridional section or a 3D view.")
            self._sync = False
            return
        s = merged_settings(settings)
        self.file_label.setText(os.path.basename(s["file"]))
        self.file_label.setToolTip(s["file"])
        self.info.setText(busy or summary or "")
        i = self.axis.findData(s["axis"])
        self.axis.setCurrentIndex(max(i, 0))
        for sp, sl, k in ((self.theta, self.theta_s, "theta"), (self.yaw, self.yaw_s, "yaw"),
                          (self.pitch, self.pitch_s, "pitch")):
            sp.setValue(float(s[k]))
            sl.setValue(int(round(float(s[k]))))
        self.cut.setChecked(bool(s["cut"]))
        self.follow.setChecked(bool(s["follow"]))
        self.upper.setChecked(bool(s["upper_half"]))
        self.show_section.setChecked(bool(s["show_section"]))
        self.show_faces.setChecked(bool(s["show_faces"]))
        self.show_edges.setChecked(bool(s["show_edges"]))
        self.opacity.setValue(int(round(100 * float(s["opacity"]))))
        self.surf_op.setValue(int(round(100 * float(s["surface_opacity"]))))
        self.quality.setCurrentIndex(max(self.quality.findData(s["quality"]), 0))
        j = next((k for k in range(self.unit.count()) if abs(self.unit.itemData(k) - float(s["unit_scale"])) < 1e-9), 0)
        self.unit.setCurrentIndex(j)
        self.visible.setChecked(bool(s["visible"]))
        self.scale.setValue(float(s["scale"]))
        self.snap.setChecked(bool(s["snap"]))
        self._sync = False

    def set_adjust_checked(self, on: bool):
        self.b_adjust.blockSignals(True)
        self.b_adjust.setChecked(on)
        self.b_adjust.blockSignals(False)
