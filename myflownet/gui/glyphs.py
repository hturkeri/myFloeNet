"""Vector symbols for elements, chambers and tool buttons (drawn with QPainter)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QBrush


def _pen(color, w=1.6):
    p = QPen(QColor(color), w)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def draw_element_symbol(p: QPainter, kind: str, rect: QRectF, color, accent=None):
    """Draw the symbol of element `kind` centred in rect."""
    cx, cy = rect.center().x(), rect.center().y()
    w, h = rect.width(), rect.height()
    s = min(w / 40.0, h / 24.0)
    p.save()
    p.translate(cx, cy)
    p.scale(s, s)
    pen = _pen(color, 1.6)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if kind == "orifice":
        p.setPen(_pen(color, 3.0))
        p.drawLine(QPointF(0, -10), QPointF(0, -3))
        p.drawLine(QPointF(0, 3), QPointF(0, 10))
        p.setPen(_pen(color, 1.2))
        p.drawLine(QPointF(-14, 0), QPointF(14, 0))
    elif kind == "kloss":
        path = QPainterPath(QPointF(-15, 0))
        xs = [-10, -6, -2, 2, 6, 10]
        for i, x in enumerate(xs):
            path.lineTo(x, -6 if i % 2 == 0 else 6)
        path.lineTo(15, 0)
        p.drawPath(path)
    elif kind == "pipe":
        p.drawRoundedRect(QRectF(-16, -6, 32, 12), 6, 6)
        p.setPen(_pen(color, 1.0))
        p.drawLine(QPointF(-10, 0), QPointF(10, 0))
    elif kind == "labyrinth":
        p.drawLine(QPointF(-16, -8), QPointF(16, -8))
        p.drawLine(QPointF(-16, 9), QPointF(16, 9))
        for x in (-11, -4, 3, 10):
            p.drawLine(QPointF(x, 9), QPointF(x, -4))
    elif kind == "vortex":
        path = QPainterPath()
        n = 60
        for i in range(n + 1):
            t = i / n * 2.6 * math.pi
            r = 1.5 + 3.4 * t / math.pi
            pt = QPointF(r * math.cos(t), r * math.sin(t) * 0.95)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        p.drawPath(path)
    elif kind == "cavity":
        p.setBrush(QBrush(QColor(color)))
        p.drawRect(QRectF(-9, -10, 4, 20))
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(color, 2.4))
        p.drawLine(QPointF(8, -10), QPointF(8, 10))
        p.setPen(_pen(color, 1.2))
        path = QPainterPath(QPointF(-2, 6))
        path.cubicTo(QPointF(-1, -4), QPointF(4, -4), QPointF(4, 3))
        p.drawPath(path)
        p.drawLine(QPointF(4, 3), QPointF(2, 1))
        p.drawLine(QPointF(4, 3), QPointF(5.5, 0.5))
    elif kind == "fixedflow":
        p.drawEllipse(QPointF(0, 0), 9, 9)
        p.drawLine(QPointF(-5, 0), QPointF(5, 0))
        p.drawLine(QPointF(5, 0), QPointF(1.5, -3.5))
        p.drawLine(QPointF(5, 0), QPointF(1.5, 3.5))
    elif kind == "discpump":
        p.drawEllipse(QPointF(0, 0), 3, 3)
        for k in range(6):
            a = k * math.pi / 3
            p.drawLine(QPointF(5 * math.cos(a), 5 * math.sin(a)), QPointF(10 * math.cos(a), 10 * math.sin(a)))
    else:
        p.drawRect(QRectF(-10, -6, 20, 12))
    p.restore()


def draw_chamber_symbol(p: QPainter, kind: str, rect: QRectF, line, fill, angle: float = 0.0):
    p.save()
    r = rect.adjusted(2, 2, -2, -2)
    p.setBrush(QBrush(QColor(fill)))
    p.setPen(_pen(line, 1.6))
    if kind == "boundary":
        p.drawRoundedRect(r, 4, 4)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(3.5, 3.5, -3.5, -3.5), 2, 2)
    else:
        p.drawEllipse(r)
        if kind == "momentum":
            # through-flow arrow, turned to the solved flow direction (meridional plane, y up)
            c = r.center()
            L = r.width() * 0.30
            a = math.radians(angle)
            dx, dy = math.cos(a), -math.sin(a)
            tail = QPointF(c.x() - dx * L, c.y() - dy * L)
            tip = QPointF(c.x() + dx * L, c.y() + dy * L)
            p.drawLine(tail, tip)
            hs = r.width() * 0.13
            for sgn in (1, -1):
                ang = a + math.pi + sgn * 0.5
                p.drawLine(tip, QPointF(tip.x() + hs * math.cos(ang), tip.y() - hs * math.sin(ang)))
        if kind == "inertial":
            p.setBrush(Qt.NoBrush)
            rr = r.adjusted(r.width() * 0.25, r.height() * 0.25, -r.width() * 0.25, -r.height() * 0.25)
            p.drawArc(rr, 30 * 16, 260 * 16)
            # arrow head at the arc end
            a = math.radians(30)
            ex = rr.center().x() + rr.width() / 2 * math.cos(a)
            ey = rr.center().y() - rr.height() / 2 * math.sin(a)
            sz = r.width() * 0.09
            p.drawLine(QPointF(ex, ey), QPointF(ex - sz, ey - sz * 0.2))
            p.drawLine(QPointF(ex, ey), QPointF(ex + sz * 0.1, ey - sz))
    p.restore()


def _pixmap(size):
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    return pm


def element_icon(kind, color, size=28) -> QIcon:
    pm = _pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw_element_symbol(p, kind, QRectF(1, 4, size - 2, size - 8), color)
    p.end()
    return QIcon(pm)


def chamber_icon(kind, color, fill, size=28) -> QIcon:
    pm = _pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw_chamber_symbol(p, kind, QRectF(3, 3, size - 6, size - 6), color, fill)
    p.end()
    return QIcon(pm)


def tool_icon(kind, color, size=20) -> QIcon:
    pm = _pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 20.0, size / 20.0)
    p.setPen(_pen(color, 1.5))
    p.setBrush(Qt.NoBrush)
    if kind == "new":
        path = QPainterPath(QPointF(5, 2.5))
        path.lineTo(12, 2.5); path.lineTo(15.5, 6); path.lineTo(15.5, 17.5); path.lineTo(5, 17.5); path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(12, 2.5), QPointF(12, 6)); p.drawLine(QPointF(12, 6), QPointF(15.5, 6))
    elif kind == "open":
        path = QPainterPath(QPointF(2.5, 5))
        path.lineTo(7.5, 5); path.lineTo(9, 6.5); path.lineTo(16, 6.5); path.lineTo(16, 15.5)
        path.lineTo(2.5, 15.5); path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(2.5, 9), QPointF(16, 9))
    elif kind == "save":
        p.drawRoundedRect(QRectF(3, 3, 14, 14), 2, 2)
        p.drawRect(QRectF(6, 3, 8, 4.5))
        p.drawRect(QRectF(6, 11, 8, 6))
    elif kind in ("undo", "redo"):
        if kind == "redo":
            p.translate(20, 0); p.scale(-1, 1)
        path = QPainterPath(QPointF(6, 8))
        path.cubicTo(QPointF(10, 4.5), QPointF(17, 6), QPointF(16, 12))
        path.cubicTo(QPointF(15.5, 15), QPointF(12, 16.5), QPointF(9, 16))
        p.drawPath(path)
        p.drawLine(QPointF(6, 8), QPointF(6.5, 3.5)); p.drawLine(QPointF(6, 8), QPointF(10.5, 8.5))
    elif kind == "play":
        p.setBrush(QBrush(QColor(color)))
        path = QPainterPath(QPointF(6, 4)); path.lineTo(16, 10); path.lineTo(6, 16); path.closeSubpath()
        p.drawPath(path)
    elif kind == "stop":
        p.setBrush(QBrush(QColor(color)))
        p.drawRoundedRect(QRectF(5, 5, 10, 10), 1.5, 1.5)
    elif kind == "fit":
        for (x, y, dx, dy) in ((3, 3, 1, 1), (17, 3, -1, 1), (3, 17, 1, -1), (17, 17, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 4.5 * dx, y)); p.drawLine(QPointF(x, y), QPointF(x, y + 4.5 * dy))
        p.drawRect(QRectF(7.5, 7.5, 5, 5))
    elif kind == "settings":
        for y, x in ((5, 12), (10, 6), (15, 10)):
            p.drawLine(QPointF(3, y), QPointF(17, y))
            p.setBrush(QBrush(QColor(color))); p.drawEllipse(QPointF(x, y), 1.9, 1.9); p.setBrush(Qt.NoBrush)
    elif kind == "export":
        p.drawLine(QPointF(10, 3), QPointF(10, 12)); p.drawLine(QPointF(10, 3), QPointF(6.5, 6.5))
        p.drawLine(QPointF(10, 3), QPointF(13.5, 6.5))
        path = QPainterPath(QPointF(4, 10)); path.lineTo(4, 17); path.lineTo(16, 17); path.lineTo(16, 10)
        p.drawPath(path)
    elif kind == "select":
        path = QPainterPath(QPointF(5, 3)); path.lineTo(15, 11); path.lineTo(10.5, 11.5); path.lineTo(13, 16.5)
        path.lineTo(11, 17.5); path.lineTo(8.5, 12.5); path.lineTo(5, 15.5); path.closeSubpath()
        p.drawPath(path)
    elif kind == "theme":
        p.drawEllipse(QPointF(10, 10), 6.5, 6.5)
        path = QPainterPath(QPointF(10, 3.5)); path.arcTo(QRectF(3.5, 3.5, 13, 13), 90, 180); path.closeSubpath()
        p.setBrush(QBrush(QColor(color))); p.drawPath(path)
    elif kind == "labels":
        p.drawRoundedRect(QRectF(3, 5, 14, 10), 2, 2)
        p.drawLine(QPointF(6, 8.5), QPointF(14, 8.5)); p.drawLine(QPointF(6, 11.5), QPointF(11, 11.5))
    elif kind in ("zoomin", "zoomout"):
        p.drawEllipse(QPointF(8.5, 8.5), 5.2, 5.2)
        p.drawLine(QPointF(12.3, 12.3), QPointF(16.5, 16.5))
        p.drawLine(QPointF(6.2, 8.5), QPointF(10.8, 8.5))
        if kind == "zoomin":
            p.drawLine(QPointF(8.5, 6.2), QPointF(8.5, 10.8))
    elif kind == "legend":
        cols = ["#D7301F", "#F5A623", "#C9D82B", "#3CC24A", "#22C7C2", "#1E8FE6", "#1238C8"]
        p.setPen(Qt.NoPen)
        for i, c in enumerate(cols):
            p.setBrush(QBrush(QColor(c)))
            p.drawRect(QRectF(4, 3 + i * 2, 5, 2.05))
        p.setPen(_pen(color, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(4, 3, 5, 14))
        for y in (4, 10, 16):
            p.drawLine(QPointF(11, y), QPointF(16, y))
    elif kind == "geometry":
        # isometric block with a cut-away corner
        path = QPainterPath(QPointF(10, 2.8))
        path.lineTo(16.5, 6.3); path.lineTo(16.5, 13.7); path.lineTo(10, 17.2)
        path.lineTo(3.5, 13.7); path.lineTo(3.5, 6.3); path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(3.5, 6.3), QPointF(10, 9.8)); p.drawLine(QPointF(10, 9.8), QPointF(16.5, 6.3))
        p.drawLine(QPointF(10, 9.8), QPointF(10, 17.2))
        c = QColor(color)
        c.setAlpha(110)
        p.setBrush(QBrush(c))
        cut = QPainterPath(QPointF(10, 9.8)); cut.lineTo(16.5, 6.3); cut.lineTo(16.5, 13.7); cut.lineTo(10, 17.2)
        cut.closeSubpath()
        p.drawPath(cut)
    elif kind == "help":
        p.drawEllipse(QPointF(10, 10), 7, 7)
        path = QPainterPath(QPointF(7.6, 8)); path.cubicTo(QPointF(7.6, 5), QPointF(12.6, 5), QPointF(12.4, 8))
        path.cubicTo(QPointF(12.2, 10), QPointF(10, 10), QPointF(10, 12))
        p.drawPath(path)
        p.setBrush(QBrush(QColor(color))); p.drawEllipse(QPointF(10, 14.6), 0.9, 0.9)
    p.end()
    return QIcon(pm)
