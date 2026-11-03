"""Network editor canvas: chambers as nodes, elements as connections with symbols."""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal, QObject
from PySide6.QtGui import (QBrush, QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QTransform)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView, QMenu

from .glyphs import draw_chamber_symbol, draw_element_symbol
from .browser import MIME
from .theme import LIGHT, canvas_colors, luminance, ramp, ui_font

NODE_R = 22.0
GRID = 20.0


def draw_extreme_tag(p: QPainter, at: QPointF, tag: str, t: dict):
    """Small MAX / MIN flag of the contoured quantity."""
    p.save()
    f = ui_font(7.2, bold=True)
    p.setFont(f)
    text = tag.upper()
    w = QFontMetricsF(f).horizontalAdvance(text) + 8
    box = QRectF(at.x(), at.y() - 13, w, 13)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#D7301F") if tag == "max" else QColor("#1238C8"))
    p.drawRoundedRect(box, 3, 3)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(box, Qt.AlignCenter, text)
    p.restore()


class ChamberItem(QGraphicsObject):
    def __init__(self, scene_ref, cid: int):
        super().__init__()
        self.sc = scene_ref
        self.cid = cid
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.hover = False
        self.fill = None
        self.extreme = None          # "min" / "max" marker of the contour
        self.flow_dir = 0.0
        self.result_lines: list[str] = []
        self.edges: list["ElementItem"] = []

    @property
    def ch(self):
        return self.sc.net.chambers[self.cid]

    def boundingRect(self):
        return QRectF(-90, -NODE_R - 6, 180, NODE_R * 2 + 62)

    def shape(self):
        p = QPainterPath()
        p.addEllipse(QPointF(0, 0), NODE_R + 3, NODE_R + 3)
        return p

    def paint(self, p: QPainter, opt, widget=None):
        t = self.sc.theme
        p.setRenderHint(QPainter.Antialiasing)
        kind = self.ch.kind
        fill = self.fill or QColor(t["surface"])
        line = QColor(t["ink"] if kind == "boundary" else t["ink2"])
        if self.fill is not None:
            line = fill.darker(150) if luminance(fill) > 0.25 else fill.lighter(140)
            if kind == "boundary":
                line = QColor(t["ink"])
        if self.sc.wireframe:                       # symbols as wireframe: outline only
            line = self.fill if self.fill is not None else QColor(t["ink"])
            fill = QColor(Qt.transparent)
        rect = QRectF(-NODE_R, -NODE_R, 2 * NODE_R, 2 * NODE_R)
        if self.isSelected() or self.hover:
            halo = QColor(t["accent"])
            halo.setAlpha(255 if self.isSelected() else 90)
            p.setPen(QPen(halo, 2.4))
            p.setBrush(Qt.NoBrush)
            if kind == "boundary":
                p.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 7, 7)
            else:
                p.drawEllipse(rect.adjusted(-4, -4, 4, 4))
        if self.sc.wireframe:
            p.save()
            p.setPen(QPen(line, 2.0))
            p.setBrush(Qt.NoBrush)
            r2 = rect.adjusted(2, 2, -2, -2)
            p.drawRoundedRect(r2, 4, 4) if kind == "boundary" else p.drawEllipse(r2)
            p.restore()
        draw_chamber_symbol(p, kind, rect, line, fill, self.flow_dir)
        if self.extreme:
            draw_extreme_tag(p, QPointF(NODE_R * 0.55, -NODE_R - 4), self.extreme, t)
        # labels on a canvas-coloured backing so connection lines never cut through text
        fm = QFontMetricsF(self.sc.font_name)
        fs = QFontMetricsF(self.sc.font_small)
        name = fm.elidedText(self.sc.label_text("C", self.cid, self.ch.name), Qt.ElideRight, 176)
        lines = self.result_lines if self.sc.show_results else []
        if not name and not lines:
            return
        y0 = NODE_R + 6
        wmax = max([fm.horizontalAdvance(name)] + [fs.horizontalAdvance(l) for l in lines])
        hh = (fm.height() if name else 0) + fs.height() * len(lines)
        p.setPen(Qt.NoPen)
        p.setBrush(self.sc.label_back())
        p.drawRoundedRect(QRectF(-wmax / 2 - 4, y0 - 1, wmax + 8, hh + 2), 4, 4)
        p.setPen(QColor(t["ink"]))
        p.setFont(self.sc.font_name)
        y = y0
        if name:
            p.drawText(QRectF(-90, y, 180, fm.height()), Qt.AlignHCenter | Qt.AlignTop, name)
            y += fm.height()
        p.setFont(self.sc.font_small)
        p.setPen(QColor(t["ink2"]))
        for ln in lines:
            p.drawText(QRectF(-90, y, 180, fs.height()), Qt.AlignHCenter | Qt.AlignTop, ln)
            y += fs.height()

    def hoverEnterEvent(self, e):
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, e):
        self.hover = False
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and not self.sc.building:
            v = QPointF(value)
            hit = self.sc.geometry_snap(v)
            if hit is not None:
                return hit
            if self.sc.snap:
                return QPointF(round(v.x() / (GRID / 2)) * (GRID / 2), round(v.y() / (GRID / 2)) * (GRID / 2))
        if change == QGraphicsItem.ItemPositionHasChanged:
            ch = self.sc.net.chambers.get(self.cid)
            if ch is not None:
                ch.x, ch.y = self.pos().x(), self.pos().y()
            for e in self.edges:
                e.update_geometry()
        return super().itemChange(change, value)


class ElementItem(QGraphicsObject):
    def __init__(self, scene_ref, eid: int, ia: ChamberItem, ib: ChamberItem):
        super().__init__()
        self.sc = scene_ref
        self.eid = eid
        self.ia, self.ib = ia, ib
        ia.edges.append(self)
        ib.edges.append(self)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.hover = False
        self.offset = 0.0
        self.width = 1.6
        self.direction = 1          # +1 a->b, -1 b->a
        self.flow_label = ""
        self.warn = False
        self.color = None            # contour colour of the connection (Post-Processing → Colorize)
        self.extreme = None
        self.path = QPainterPath()
        self.mid = QPointF()
        self.tangent = QPointF(1, 0)
        self._br = QRectF()
        self.update_geometry()

    @property
    def el(self):
        return self.sc.net.elements[self.eid]

    def update_geometry(self):
        self.prepareGeometryChange()
        a, b = self.ia.pos(), self.ib.pos()
        d = b - a
        L = math.hypot(d.x(), d.y()) or 1.0
        n = QPointF(-d.y() / L, d.x() / L)
        c = (a + b) / 2 + n * (2.0 * self.offset)
        # trim at node borders
        def trim(p0, toward, r):
            v = toward - p0
            l = math.hypot(v.x(), v.y()) or 1.0
            return p0 + v * (r / l)
        a2 = trim(a, c, NODE_R + 3)
        b2 = trim(b, c, NODE_R + 3)
        path = QPainterPath(a2)
        path.quadTo(c, b2)
        self.path = path
        self.mid = path.pointAtPercent(0.5)
        t = path.angleAtPercent(0.5)
        self.tangent = QPointF(math.cos(math.radians(t)), -math.sin(math.radians(t)))
        self._br = path.boundingRect().adjusted(-12, -12, 12, 12).united(
            QRectF(self.mid.x() - 90, self.mid.y() - 34, 300, 74))
        self.update()

    def boundingRect(self):
        return self._br

    def chip_rect(self):
        return QRectF(self.mid.x() - 20, self.mid.y() - 12, 40, 24)

    def shape(self):
        st = QPainterPathStroker()
        st.setWidth(10)
        s = st.createStroke(self.path)
        s.addRoundedRect(self.chip_rect().adjusted(-2, -2, 2, 2), 6, 6)
        return s

    def paint(self, p: QPainter, opt, widget=None):
        t = self.sc.theme
        p.setRenderHint(QPainter.Antialiasing)
        sel = self.isSelected()
        col = QColor(t["accent"]) if sel else (QColor(self.color) if self.color is not None else QColor(t["edge"]))
        if self.hover and not sel:
            col = QColor(t["ink"]) if self.color is None else QColor(self.color).lighter(120)
        width = self.width * self.sc.line_scale + (1.5 if self.color is not None else 0.0)
        pen = QPen(col, width)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.path)
        # arrow head at 78% along the path in flow direction
        pct = 0.80 if self.direction > 0 else 0.20
        pt = self.path.pointAtPercent(pct)
        ang = math.radians(self.path.angleAtPercent(pct))
        dx, dy = math.cos(ang) * self.direction, -math.sin(ang) * self.direction
        size = 7 + width
        tip = QPointF(pt.x() + dx * size * 0.5, pt.y() + dy * size * 0.5)
        left = QPointF(tip.x() - dx * size - dy * size * 0.55, tip.y() - dy * size + dx * size * 0.55)
        right = QPointF(tip.x() - dx * size + dy * size * 0.55, tip.y() - dy * size - dx * size * 0.55)
        head = QPainterPath(tip)
        head.lineTo(left)
        head.lineTo(right)
        head.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPath(head)
        # chip
        r = self.chip_rect()
        p.setBrush(Qt.NoBrush if self.sc.wireframe else QColor(t["surface"]))
        p.setPen(QPen(QColor(t["accent"]) if sel else QColor(t["border"]).darker(115 if not t.get("canvas_dark") else 70),
                      2.0 if sel else 1.2))
        p.drawRoundedRect(r, 6, 6)
        draw_element_symbol(p, self.el.type, r.adjusted(4, 2, -4, -2), t["ink"])
        if self.extreme:
            draw_extreme_tag(p, QPointF(r.left() - 4, r.top() - 6), self.extreme, t)
        if self.warn:
            # status badge: warning colour + exclamation glyph
            b = QRectF(r.right() - 7, r.top() - 7, 13, 13)
            p.setBrush(QColor(t["warning"]))
            p.setPen(QPen(QColor(t["surface"]), 1.5))
            p.drawEllipse(b)
            p.setPen(QPen(QColor("#1C252E"), 1.6))
            p.drawLine(QPointF(b.center().x(), b.top() + 3), QPointF(b.center().x(), b.bottom() - 5.2))
            p.drawPoint(QPointF(b.center().x(), b.bottom() - 3.2))
        # labels: name above / flow below the chip; beside the chip on steep connections
        p.setFont(self.sc.font_small)
        fm = QFontMetricsF(self.sc.font_small)
        name = fm.elidedText(self.sc.label_text("E", self.eid, self.el.name), Qt.ElideRight, 176)
        show_flow = bool(self.flow_label and self.sc.show_flow_labels and self.sc.show_results)
        back = self.sc.label_back()

        def backing(rect, text):
            w = fm.horizontalAdvance(text) + 6
            if rect.width() >= 179:          # centred label
                x0 = rect.center().x() - w / 2
            else:
                x0 = rect.left() - 3
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(back)
            p.drawRoundedRect(QRectF(x0, rect.top(), w, rect.height()), 3, 3)
            p.restore()
        if self.vertical():
            x = r.right() + 8
            y = self.mid.y() - (fm.height() if show_flow else fm.height() / 2)
            rn = QRectF(x, y, 178, fm.height())
            if name:
                backing(rn, name)
                p.setPen(QColor(t["ink"]))
                p.drawText(rn, Qt.AlignLeft | Qt.AlignVCenter, name)
            if show_flow:
                rf = QRectF(x, y + fm.height(), 178, fm.height())
                backing(rf, self.flow_label)
                p.setPen(QColor(t["ink2"]))
                p.drawText(rf, Qt.AlignLeft | Qt.AlignVCenter, self.flow_label)
        else:
            rn = QRectF(self.mid.x() - 90, r.top() - fm.height() - 2, 180, fm.height())
            if name:
                backing(rn, name)
                p.setPen(QColor(t["ink"]))
                p.drawText(rn, Qt.AlignHCenter | Qt.AlignBottom, name)
            if show_flow:
                rf = QRectF(self.mid.x() - 90, r.bottom() + 2, 180, fm.height())
                backing(rf, self.flow_label)
                p.setPen(QColor(t["ink2"]))
                p.drawText(rf, Qt.AlignHCenter | Qt.AlignTop, self.flow_label)

    def vertical(self):
        return abs(self.tangent.y()) > 0.75

    def hoverEnterEvent(self, e):
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, e):
        self.hover = False
        self.update()


class NetworkScene(QGraphicsScene):
    selectionIds = Signal(object)                 # ("chamber"|"element"|None, id)
    addChamberRequested = Signal(str, QPointF)
    addElementRequested = Signal(str, int, int)
    deleteRequested = Signal()
    reverseRequested = Signal(int)
    duplicateRequested = Signal(int)
    moveFinished = Signal(object)                 # {cid: (x0, y0)} original positions
    modeChanged = Signal(str)
    selectionListChanged = Signal(object)         # [(kind, id), ...]

    def __init__(self, net, theme=LIGHT):
        super().__init__()
        self.net = net
        self.app_theme = theme
        self.canvas_preset = "light"
        self.canvas_custom = None
        self.theme = canvas_colors(theme, self.canvas_preset)
        self.snap = True
        self.show_flow_labels = True
        self.show_results = True      # results printed next to chambers and elements
        self.label_mode = "name"      # name | id | id_name | none
        self.wireframe = False        # symbols as wireframe
        self.line_scale = 1.0         # connection-line thickness
        self.show_axes = True
        self.mode = "select"          # select | add:<kind> | connect:<type>
        self.font_name = ui_font(9.4, bold=True)
        self.font_small = ui_font(8.8)
        self.chambers: dict[int, ChamberItem] = {}
        self.elements: dict[int, ElementItem] = {}
        self._temp_line = None
        self._connect_src = None
        self._press_pos = {}
        self._bg_drag = None
        self.building = False         # True while items are (re)created: no snapping
        self.background = None        # BackgroundLayer (CAD geometry behind the network)
        self.setSceneRect(-3000, -2000, 6000, 4000)
        self.selectionChanged.connect(self._on_sel)

    # ----------------------------------------------------------- building
    def rebuild(self, net=None, keep_selection=True):
        sel = self.current_selection() if keep_selection else (None, None)
        if net is not None:
            self.net = net
        self.blockSignals(True)
        self.building = True
        self.clear()
        self._temp_line = None
        self.chambers.clear()
        self.elements.clear()
        for cid, ch in self.net.chambers.items():
            it = ChamberItem(self, cid)
            it.setPos(ch.x, ch.y)
            self.addItem(it)
            self.chambers[cid] = it
        for eid, el in self.net.elements.items():
            it = ElementItem(self, eid, self.chambers[el.a], self.chambers[el.b])
            self.addItem(it)
            self.elements[eid] = it
        self._assign_offsets()
        self.building = False
        self.blockSignals(False)
        if sel[0] == "chamber" and sel[1] in self.chambers:
            self.chambers[sel[1]].setSelected(True)
        elif sel[0] == "element" and sel[1] in self.elements:
            self.elements[sel[1]].setSelected(True)
        self._on_sel()

    def _assign_offsets(self):
        groups = {}
        for eid, el in self.net.elements.items():
            key = tuple(sorted((el.a, el.b)))
            groups.setdefault(key, []).append(eid)
        for key, ids in groups.items():
            n = len(ids)
            for k, eid in enumerate(sorted(ids)):
                el = self.net.elements[eid]
                off = (k - (n - 1) / 2.0) * 34.0
                if el.a != key[0]:
                    off = -off
                it = self.elements[eid]
                it.offset = off
                it.update_geometry()

    def set_theme(self, theme):
        self.app_theme = theme
        self.theme = canvas_colors(theme, self.canvas_preset, self.canvas_custom)
        if self.background is not None:
            self.background.set_theme(self.theme)
        self.update()

    def set_canvas(self, preset: str, custom=None):
        self.canvas_preset = preset
        self.canvas_custom = custom
        self.set_theme(self.app_theme)

    def label_text(self, prefix: str, oid: int, name: str) -> str:
        m = self.label_mode
        if m == "id":
            return f"{prefix}{oid}"
        if m == "id_name":
            return f"{prefix}{oid}  {name}"
        if m == "none":
            return ""
        return name

    def label_back(self) -> QColor:
        if self.theme.get("canvas_dark"):
            return QColor(0, 0, 0, 120)
        c = QColor(self.theme["canvas2"] if self.canvas_preset == "gradient" else self.theme["canvas"])
        c.setAlpha(205)
        return c

    def selection_list(self):
        out = []
        for it in self.selectedItems():
            if isinstance(it, ChamberItem):
                out.append(("chamber", it.cid))
            elif isinstance(it, ElementItem):
                out.append(("element", it.eid))
        return sorted(out, key=lambda x: (x[0] != "chamber", x[1]))

    def select_many(self, sel, center=False):
        self.blockSignals(True)
        self.clearSelection()
        first = None
        for kind, oid in sel:
            it = (self.chambers if kind == "chamber" else self.elements).get(oid)
            if it is not None:
                it.setSelected(True)
                first = first or it
        self.blockSignals(False)
        self._on_sel()
        if center and first is not None:
            for v in self.views():
                v.centerOn(first.mapRectToScene(first.boundingRect()).center() if isinstance(first, ChamberItem)
                           else first.mid)

    def view_scale(self) -> float:
        vs = self.views()
        return abs(vs[0].transform().m11()) if vs else 1.0

    def geometry_snap(self, pos: QPointF, px: float = 11.0):
        """Nearest CAD vertex / section corner within `px` screen pixels, or None."""
        bg = self.background
        if bg is None:
            return None
        return bg.snap(pos, px / max(self.view_scale(), 1e-3))

    def ensure_rect(self, rect: QRectF):
        r = self.sceneRect()
        if not r.contains(rect):
            self.setSceneRect(r.united(rect.adjusted(-800, -800, 800, 800)))

    # ----------------------------------------------------------- selection
    def current_selection(self):
        items = self.selectedItems()
        if not items:
            return (None, None)
        it = items[0]
        if isinstance(it, ChamberItem):
            return ("chamber", it.cid)
        if isinstance(it, ElementItem):
            return ("element", it.eid)
        return (None, None)

    def _on_sel(self):
        self.selectionIds.emit(self.current_selection())
        self.selectionListChanged.emit(self.selection_list())

    def select(self, kind, oid):
        self.clearSelection()
        it = (self.chambers if kind == "chamber" else self.elements).get(oid)
        if it is not None:
            it.setSelected(True)
            for v in self.views():
                v.ensureVisible(it, 80, 80)

    # ----------------------------------------------------------- modes
    def set_mode(self, mode):
        self.mode = mode
        self._cancel_connect()
        for v in self.views():
            v.setDragMode(QGraphicsView.RubberBandDrag if mode == "select" else QGraphicsView.NoDrag)
            v.viewport().setCursor(Qt.ArrowCursor if mode == "select" else
                                   Qt.SizeAllCursor if mode == "bg_adjust" else Qt.CrossCursor)
        self.modeChanged.emit(mode)

    def begin_connect(self, src, pos):
        self._cancel_connect()
        self._connect_src = src
        pen = QPen(QColor(self.theme["accent"]), 1.8, Qt.DashLine)
        self._temp_line = self.addLine(QLineF(src.pos(), pos), pen)
        self._temp_line.setZValue(5)

    def _cancel_connect(self):
        if self._temp_line is not None:
            self.removeItem(self._temp_line)
            self._temp_line = None
        self._connect_src = None

    def chamber_at(self, pos):
        for it in self.items(pos):
            if isinstance(it, ChamberItem):
                return it
        return None

    def mousePressEvent(self, e):
        if self.mode == "bg_adjust":
            if e.button() == Qt.LeftButton:
                self._bg_drag = e.scenePos()
            e.accept()
            return
        if e.button() == Qt.LeftButton and self.mode.startswith("add:"):
            kind = self.mode.split(":", 1)[1]
            pos = e.scenePos()
            hit = self.geometry_snap(pos)
            pos = hit if hit is not None else QPointF(round(pos.x() / GRID) * GRID, round(pos.y() / GRID) * GRID)
            self.addChamberRequested.emit(kind, pos)
            if not (e.modifiers() & Qt.ShiftModifier):
                self.set_mode("select")
            e.accept()
            return
        if e.button() == Qt.LeftButton and self.mode.startswith("connect:"):
            it = self.chamber_at(e.scenePos())
            if it is None:
                self._cancel_connect()
                e.accept()
                return
            if self._connect_src is None:
                self._connect_src = it
                pen = QPen(QColor(self.theme["accent"]), 1.8, Qt.DashLine)
                self._temp_line = self.addLine(QLineF(it.pos(), e.scenePos()), pen)
                self._temp_line.setZValue(5)
            elif it is not self._connect_src:
                self._finish_connect(it, e.modifiers())
            e.accept()
            return
        if e.button() == Qt.LeftButton:
            self._press_pos = {cid: (it.pos().x(), it.pos().y()) for cid, it in self.chambers.items()}
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.mode == "bg_adjust":
            if self._bg_drag is not None and self.background is not None:
                d = e.scenePos() - self._bg_drag
                self._bg_drag = e.scenePos()
                self.background.move_by(d.x(), d.y())
            e.accept()
            return
        if self._temp_line is not None and self._connect_src is not None:
            self._temp_line.setLine(QLineF(self._connect_src.pos(), e.scenePos()))
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.mode == "bg_adjust":
            if self._bg_drag is not None and self.background is not None:
                self.background.placement_done()
            self._bg_drag = None
            e.accept()
            return
        if self.mode.startswith("connect:") and self._connect_src is not None and e.button() == Qt.LeftButton:
            it = self.chamber_at(e.scenePos())
            if it is not None and it is not self._connect_src:
                self._finish_connect(it, e.modifiers())
            e.accept()
            return
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton and self._press_pos:
            moved = {cid: xy for cid, xy in self._press_pos.items()
                     if cid in self.chambers and (abs(self.chambers[cid].pos().x() - xy[0]) > 0.1
                                                  or abs(self.chambers[cid].pos().y() - xy[1]) > 0.1)}
            self._press_pos = {}
            if moved:
                self.moveFinished.emit(moved)

    def _finish_connect(self, target, modifiers=Qt.NoModifier):
        mode = self.mode
        etype = mode.split(":", 1)[1]
        src = self._connect_src
        self._cancel_connect()
        if not (modifiers & Qt.ShiftModifier):
            self.set_mode("select")
        self.addElementRequested.emit(etype, src.cid, target.cid)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.set_mode("select")
            e.accept()
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selectedItems():
            self.deleteRequested.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        if self.mode == "bg_adjust":
            return
        items = [i for i in self.items(e.scenePos()) if isinstance(i, (ChamberItem, ElementItem))]
        m = QMenu()
        if items:
            it = items[0]
            if not it.isSelected():
                self.clearSelection()
                it.setSelected(True)
            if isinstance(it, ElementItem):
                m.addAction("Reverse direction", lambda: self.reverseRequested.emit(it.eid))
            else:
                m.addAction("Duplicate", lambda: self.duplicateRequested.emit(it.cid))
            m.addSeparator()
            m.addAction("Delete", self.deleteRequested.emit)
        else:
            pos = e.scenePos()
            for kind, label in (("boundary", "Add boundary"), ("plenum", "Add plenum"),
                                ("momentum", "Add momentum chamber"), ("inertial", "Add inertial chamber")):
                m.addAction(label, lambda k=kind: self.addChamberRequested.emit(k, pos))
        m.exec(e.screenPos())

    # ----------------------------------------------------------- drawing
    def drawBackground(self, p: QPainter, rect: QRectF):
        t = self.theme
        if t.get("canvas2", t["canvas"]) != t["canvas"]:
            g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            g.setColorAt(0.0, QColor(t["canvas"]))
            g.setColorAt(1.0, QColor(t["canvas2"]))
            p.fillRect(rect, QBrush(g))
        else:
            p.fillRect(rect, QColor(t["canvas"]))
        scale = p.transform().m11()
        if scale >= 0.35:
            self._draw_grid(p, rect, scale)
        if self.background is not None:
            self.background.paint(p, rect)

    def _draw_grid(self, p: QPainter, rect: QRectF, scale: float):
        t = self.theme
        pen = QPen(QColor(t["grid"]), 1.6 / scale if scale > 0 else 1.0)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        left = math.floor(rect.left() / GRID) * GRID
        top = math.floor(rect.top() / GRID) * GRID
        pts = []
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                pts.append(QPointF(x, y))
                y += GRID
            x += GRID
        p.drawPoints(pts)

    # ----------------------------------------------------------- results
    def clear_results(self):
        for it in self.chambers.values():
            it.fill = None
            it.extreme = None
            it.flow_dir = 0.0
            it.result_lines = []
            it.update()
        for it in self.elements.values():
            it.width = 1.6
            it.direction = 1
            it.flow_label = ""
            it.warn = False
            it.color = None
            it.extreme = None
            it.update()


class NetworkView(QGraphicsView):
    cursorMoved = Signal(QPointF)

    def __init__(self, scene: NetworkScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self._pan = None
        self.legend = None      # dict(title, unit, labels, color(t) or bands)
        self.hint = ""
        self.axes_labels = ("x", "y")
        self.setAcceptDrops(True)

    # ------------------------------------------------------------ drag & drop from the Element Library
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(MIME):
            super().dropEvent(e)
            return
        mode = bytes(e.mimeData().data(MIME)).decode("utf-8")
        sc = self.scene()
        pos = self.mapToScene(e.position().toPoint())
        e.acceptProposedAction()
        if mode.startswith("add:"):
            hit = sc.geometry_snap(pos)
            pos = hit if hit is not None else QPointF(round(pos.x() / GRID) * GRID, round(pos.y() / GRID) * GRID)
            sc.addChamberRequested.emit(mode.split(":", 1)[1], pos)
        elif mode.startswith("connect:"):
            sc.set_mode(mode)
            it = sc.chamber_at(pos)
            if it is not None:          # dropped on a chamber: it is the upstream end, click the downstream one
                sc.begin_connect(it, pos)

    def zoom_by(self, f):
        s = self.transform().m11() * f
        if 0.1 < s < 6.0:
            self.scale(f, f)

    def wheelEvent(self, e):
        sc = self.scene()
        if sc.mode == "bg_adjust" and sc.background is not None:
            f = 1.0 + e.angleDelta().y() / 1200.0
            sc.background.scale_about(self.mapToScene(e.position().toPoint()), f)
            sc.background.placement_done()
            return
        f = 1.0 + e.angleDelta().y() / 1200.0
        s = self.transform().m11() * f
        if 0.15 < s < 4.0:
            self.scale(f, f)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and e.modifiers() & Qt.AltModifier):
            self._pan = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self.cursorMoved.emit(self.mapToScene(e.position().toPoint()))
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan is not None and e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self.viewport().setCursor(Qt.ArrowCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def fit(self):
        sc = self.scene()
        items = list(sc.chambers.values())
        bg = sc.background
        bgr = bg.scene_bounds() if bg is not None and bg.is_visible() else QRectF()
        if not items and bgr.isEmpty():
            self.resetTransform()
            self.centerOn(0, 0)
            return
        r = QRectF()
        for it in items:
            r = r.united(it.mapRectToScene(it.boundingRect()))
        for it in sc.elements.values():
            r = r.united(it.boundingRect())
        if not bgr.isEmpty():
            r = r.united(bgr) if not r.isEmpty() else bgr
        r = r.adjusted(-60, -60, 60, 60)
        self.fitInView(r, Qt.KeepAspectRatio)
        s = self.transform().m11()
        if s > 1.4:
            self.setTransform(QTransform.fromScale(1.4, 1.4))
            self.centerOn(r.center())

    def drawForeground(self, p: QPainter, rect: QRectF):
        sc = self.scene()
        t = sc.theme
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.Antialiasing)
        vp = self.viewport().rect()
        if sc.show_axes:
            self._draw_axes(p, vp, t)
        if self.hint:
            p.setFont(ui_font(9.0))
            fm = QFontMetricsF(p.font())
            w = fm.horizontalAdvance(self.hint) + 24
            box = QRectF((vp.width() - w) / 2, 12, w, 28)
            p.setPen(QPen(QColor(t["border"]), 1))
            p.setBrush(QColor(t["surface"]))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor(t["ink"]))
            p.drawText(box, Qt.AlignCenter, self.hint)
        lg = self.legend
        if lg:
            self._draw_legend(p, vp, t, lg)
        p.restore()

    def _draw_axes(self, p, vp, t):
        """Global axes triad (bottom right): canvas x to the right, y up."""
        o = QPointF(vp.width() - 70, vp.height() - 22)
        L = 34
        p.setFont(ui_font(8.4, bold=True))
        for (dx, dy), col, lab in (((1, 0), "#E5533D", self.axes_labels[0]), ((0, -1), "#36B24A", self.axes_labels[1])):
            tip = QPointF(o.x() + dx * L, o.y() + dy * L)
            pen = QPen(QColor(col), 2.0)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(o, tip)
            head = QPainterPath(tip)
            head.lineTo(tip.x() - dx * 7 - dy * 3.5, tip.y() - dy * 7 + dx * 3.5)
            head.lineTo(tip.x() - dx * 7 + dy * 3.5, tip.y() - dy * 7 - dx * 3.5)
            head.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawPath(head)
            p.setPen(QColor(t["ink"]))
            p.drawText(QRectF(tip.x() + (4 if dx else -20), tip.y() - (16 if dy else 8), 40, 16),
                       Qt.AlignLeft | Qt.AlignVCenter, lab)
        p.setBrush(QColor(t["ink"]))
        p.setPen(Qt.NoPen)
        p.drawEllipse(o, 2.5, 2.5)

    def _draw_legend(self, p, vp, t, lg):
        """Vertical contour legend (top left): coloured bands with their limits."""
        labels = lg["labels"]
        n = max(len(labels) - 1, 1)
        band_h = max(10.0, min(22.0, 220.0 / n))
        fm = QFontMetricsF(ui_font(8.2))
        lw = max(fm.horizontalAdvance(x) for x in labels) if labels else 40
        title = f"{lg['title']} [{lg['unit']}]" if lg.get("unit") else lg["title"]
        p.setFont(ui_font(8.8, bold=True))
        tw = QFontMetricsF(p.font()).horizontalAdvance(title)
        w = max(tw + 24, 18 + 16 + 8 + lw + 14)
        h = 30 + n * band_h + 12
        box = QRectF(14, 14, w, h)
        bg = QColor(t["surface"]) if not t.get("canvas_dark") else QColor(0, 0, 0, 150)
        if not t.get("canvas_dark"):
            bg.setAlpha(235)
        p.setPen(QPen(QColor(t["border"]), 1))
        p.setBrush(bg)
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor(t["ink"]))
        p.drawText(QRectF(box.left() + 10, box.top() + 7, w - 20, 16), Qt.AlignLeft | Qt.AlignVCenter, title)
        x0, y0 = box.left() + 12, box.top() + 30
        for k in range(n):
            # top band = maximum
            c = lg["color"]((n - 1 - k + 0.5) / n)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRect(QRectF(x0, y0 + k * band_h, 16, band_h + 0.5))
        p.setPen(QPen(QColor(t["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x0, y0, 16, n * band_h))
        p.setFont(ui_font(8.2))
        p.setPen(QColor(t["ink2"]))
        step = max(1, int(round(n / max(1.0, (n * band_h) / 14.0))))
        for k, lab in enumerate(reversed(labels)):
            if k % step and k != n:
                continue
            y = y0 + k * band_h
            p.drawText(QRectF(x0 + 22, y - 8, lw + 6, 16), Qt.AlignLeft | Qt.AlignVCenter, lab)
