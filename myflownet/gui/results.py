"""Result tables and lightweight line charts (QPainter, no extra dependency)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..units import fmt
from .theme import LIGHT, ui_font


# ---------------------------------------------------------------- ticks
def nice_ticks(lo, hi, n=5):
    if not math.isfinite(lo) or not math.isfinite(hi):
        return [0.0, 1.0]
    if hi <= lo:
        hi = lo + (abs(lo) * 0.1 or 1.0)
    span = hi - lo
    raw = span / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=10 * mag)
    start = math.floor(lo / step) * step
    out = []
    v = start
    while v <= hi + step * 0.5 and len(out) < 50:
        out.append(round(v, 12))
        v += step
    return out


class LinePlot(QWidget):
    """Single-axis line chart with optional log y, legend for >=2 series and a hover read-out."""

    def __init__(self, theme=LIGHT):
        super().__init__()
        self.theme = theme
        self.title = ""
        self.xlabel = ""
        self.ylabel = ""
        self.series = []        # (name, xs, ys, color_key)
        self.log_y = False
        self.markers = False
        self.hover_x = None
        self.setMouseTracking(True)
        self.setMinimumHeight(160)

    def set_data(self, title, xlabel, ylabel, series, log_y=False, markers=False):
        self.title, self.xlabel, self.ylabel = title, xlabel, ylabel
        self.series = [s for s in series if len(s[1]) > 0]
        self.log_y = log_y
        self.markers = markers
        self.update()

    def _ranges(self):
        xs = [x for s in self.series for x in s[1]]
        ys = [y for s in self.series for y in s[2] if (not self.log_y or y > 0) and math.isfinite(y)]
        if not xs or not ys:
            return None
        x0, x1 = min(xs), max(xs)
        if x1 == x0:
            x1 = x0 + 1
        if self.log_y:
            y0 = 10 ** math.floor(math.log10(min(ys)))
            y1 = 10 ** math.ceil(math.log10(max(ys)))
            if y1 <= y0:
                y1 = y0 * 10
            return x0, x1, y0, y1, None
        y0, y1 = min(ys), max(ys)
        pad = (y1 - y0) * 0.08 or abs(y0) * 0.05 or 1.0
        ticks = nice_ticks(y0 - pad, y1 + pad, 4)
        return x0, x1, ticks[0], ticks[-1], ticks

    def paintEvent(self, ev):
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(t["surface"]))
        f_small = ui_font(8.2)
        f_title = ui_font(9.0, bold=True)
        fm = QFontMetricsF(f_small)
        p.setFont(f_title)
        p.setPen(QColor(t["ink"]))
        p.drawText(QRectF(14, 8, self.width() - 28, 18), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        rng = self._ranges()
        if rng is None:
            p.setFont(f_small)
            p.setPen(QColor(t["ink2"]))
            p.drawText(self.rect(), Qt.AlignCenter, "No data yet")
            return
        x0, x1, y0, y1, yt = rng
        left, right, top, bottom = 64, 16, 52, 34
        if len(self.series) >= 2:
            top = 70
        plot = QRectF(left, top, max(self.width() - left - right, 10), max(self.height() - top - bottom, 10))

        def X(x):
            return plot.left() + (x - x0) / (x1 - x0) * plot.width()

        def Y(y):
            if self.log_y:
                y = max(y, y0)
                return plot.bottom() - (math.log10(y) - math.log10(y0)) / (math.log10(y1) - math.log10(y0)) * plot.height()
            return plot.bottom() - (y - y0) / (y1 - y0) * plot.height()

        p.setFont(f_small)
        # grid + y ticks
        if self.log_y:
            yt = [10 ** k for k in range(int(round(math.log10(y0))), int(round(math.log10(y1))) + 1)]
            if len(yt) > 7:
                stride = math.ceil(len(yt) / 6)
                yt = yt[::stride]
        for v in yt:
            yy = Y(v)
            p.setPen(QPen(QColor(t["chart_grid"]), 1))
            p.drawLine(QPointF(plot.left(), yy), QPointF(plot.right(), yy))
            p.setPen(QColor(t["muted"]))
            lab = f"1e{int(round(math.log10(v)))}" if self.log_y else fmt(v, 4)
            p.drawText(QRectF(0, yy - 8, left - 8, 16), Qt.AlignRight | Qt.AlignVCenter, lab)
        xt = nice_ticks(x0, x1, 5)
        for v in xt:
            if v < x0 - 1e-12 or v > x1 + 1e-12:
                continue
            xx = X(v)
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(xx - 40, plot.bottom() + 4, 80, 14), Qt.AlignHCenter | Qt.AlignTop, fmt(v, 4))
        p.setPen(QPen(QColor(t["chart_axis"]), 1))
        p.drawLine(plot.bottomLeft(), plot.bottomRight())
        # axis labels
        p.setPen(QColor(t["ink2"]))
        p.drawText(QRectF(plot.left(), plot.bottom() + 17, plot.width(), 14), Qt.AlignRight | Qt.AlignTop, self.xlabel)
        p.drawText(QRectF(14, top - 20, 300, 14), Qt.AlignLeft | Qt.AlignVCenter, self.ylabel)
        # series
        for name, xs, ys, ck in self.series:
            col = QColor(t.get(ck, ck))
            path = QPainterPath()
            started = False
            for x, y in zip(xs, ys):
                if self.log_y and y <= 0:
                    continue
                pt = QPointF(X(x), Y(y))
                if not started:
                    path.moveTo(pt)
                    started = True
                else:
                    path.lineTo(pt)
            pen = QPen(col, 2.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            if self.markers:
                p.setBrush(col)
                p.setPen(QPen(QColor(t["surface"]), 1.5))
                for x, y in zip(xs, ys):
                    if self.log_y and y <= 0:
                        continue
                    p.drawEllipse(QPointF(X(x), Y(y)), 4, 4)
        # legend (>= 2 series)
        if len(self.series) >= 2:
            lx = plot.left()
            for name, xs, ys, ck in self.series:
                col = QColor(t.get(ck, ck))
                p.setPen(QPen(col, 2.0))
                p.drawLine(QPointF(lx, 39), QPointF(lx + 16, 39))
                p.setPen(QColor(t["ink"]))
                w = fm.horizontalAdvance(name)
                p.drawText(QRectF(lx + 22, 32, w + 4, 14), Qt.AlignLeft | Qt.AlignVCenter, name)
                lx += 22 + w + 18
        # hover read-out
        if self.hover_x is not None and plot.left() <= self.hover_x <= plot.right():
            xv = x0 + (self.hover_x - plot.left()) / plot.width() * (x1 - x0)
            p.setPen(QPen(QColor(t["chart_axis"]), 1, Qt.DashLine))
            p.drawLine(QPointF(self.hover_x, plot.top()), QPointF(self.hover_x, plot.bottom()))
            lines = []
            for name, xs, ys, ck in self.series:
                k = min(range(len(xs)), key=lambda i: abs(xs[i] - xv))
                col = QColor(t.get(ck, ck))
                p.setBrush(col)
                p.setPen(QPen(QColor(t["surface"]), 1.5))
                p.drawEllipse(QPointF(X(xs[k]), Y(ys[k])), 4.5, 4.5)
                lines.append((f"{name}: {fmt(ys[k], 5)}", col, xs[k]))
            head = f"{self.xlabel.split(' [')[0] or 'x'} = {fmt(lines[0][2], 5)}" if lines else ""
            txts = [head] + [l[0] for l in lines]
            w = max(fm.horizontalAdvance(s) for s in txts) + 20
            h = 8 + 16 * len(txts)
            bx = self.hover_x + 12 if self.hover_x + 12 + w < self.width() else self.hover_x - 12 - w
            box = QRectF(bx, plot.top() + 6, w, h)
            p.setPen(QPen(QColor(t["border"]), 1))
            p.setBrush(QColor(t["surface"]))
            p.drawRoundedRect(box, 6, 6)
            for i, s in enumerate(txts):
                p.setPen(QColor(t["ink"] if i else t["ink2"]))
                p.drawText(QRectF(box.left() + 10, box.top() + 4 + 16 * i, w - 14, 16), Qt.AlignLeft | Qt.AlignVCenter, s)

    def mouseMoveEvent(self, e):
        self.hover_x = e.position().x()
        self.update()

    def leaveEvent(self, e):
        self.hover_x = None
        self.update()


class ProfilePanel(QWidget):
    def __init__(self, theme=LIGHT):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.p1 = LinePlot(theme)
        self.p2 = LinePlot(theme)
        lay.addWidget(self.p1)
        lay.addWidget(self.p2)
        self.empty()

    def set_theme(self, theme):
        for p in (self.p1, self.p2):
            p.theme = theme
            p.update()

    def empty(self, msg="Select a cavity, pipe or labyrinth after solving to see its distribution."):
        self.p1.set_data(msg, "", "", [])
        self.p2.set_data("", "", "", [])
        self.p2.hide()

    def show_profile(self, el_type, name, prof, units):
        lu, pu = units.label("length"), units.label("pressure")
        self.p2.show()
        if el_type == "cavity":
            r = [units.to_display("length", x) for x in prof["r"]]
            self.p1.set_data(f"{name}: core swirl ratio", f"Radius [{lu}]", "K = Vθ / Ωr",
                             [("K", r, prof["K"], "series1")], markers=False)
            self.p2.set_data(f"{name}: static pressure", f"Radius [{lu}]", f"p [{pu}]",
                             [("p", r, [units.to_display("pressure", v) for v in prof["p"]], "series1")])
        elif el_type == "pipe":
            x = [units.to_display("length", v) for v in prof["x"]]
            self.p1.set_data(f"{name}: static pressure", f"Distance from inlet [{lu}]", f"p [{pu}]",
                             [("p", x, [units.to_display("pressure", v) for v in prof["p"]], "series1")])
            self.p2.set_data(f"{name}: Mach number", f"Distance from inlet [{lu}]", "Mach",
                             [("M", x, prof["M"], "series1")])
        elif el_type == "labyrinth":
            self.p1.set_data(f"{name}: pressure in each pocket", "Tooth", f"p [{pu}]",
                             [("p", prof["tooth"], [units.to_display("pressure", v) for v in prof["p"]], "series1")],
                             markers=True)
            self.p2.hide()
        else:
            self.empty()


class ResultTable(QTableWidget):
    rowActivated = Signal(int)

    def __init__(self):
        super().__init__()
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setSortingEnabled(True)
        self.ids = []
        self.itemSelectionChanged.connect(self._sel)

    def _sel(self):
        rows = {i.row() for i in self.selectedItems()}
        if rows:
            it = self.item(next(iter(rows)), 0)
            if it is not None:
                self.rowActivated.emit(int(it.data(Qt.UserRole)))

    def fill(self, headers, rows):
        """rows: list of (id, [cells]) where a cell is str or (str, align_left)"""
        self.blockSignals(True)
        self.setSortingEnabled(False)
        self.clear()
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))
        for r, (oid, cells) in enumerate(rows):
            for c, val in enumerate(cells):
                if isinstance(val, tuple):
                    txt, sortv = val
                else:
                    txt, sortv = val, val
                it = _SortItem(txt, sortv)
                it.setData(Qt.UserRole, oid)
                it.setTextAlignment((Qt.AlignLeft if c < 2 else Qt.AlignRight) | Qt.AlignVCenter)
                self.setItem(r, c, it)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(False)
        for c in range(min(2, len(headers))):
            self.horizontalHeaderItem(c).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSortingEnabled(True)
        self.blockSignals(False)


class _SortItem(QTableWidgetItem):
    def __init__(self, txt, sortv):
        super().__init__(str(txt))
        self.sortv = sortv

    def __lt__(self, other):
        a, b = self.sortv, getattr(other, "sortv", other.text())
        try:
            return float(a) < float(b)
        except (TypeError, ValueError):
            return str(a) < str(b)


class LogView(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)

    def log(self, msg):
        self.appendPlainText(msg)
