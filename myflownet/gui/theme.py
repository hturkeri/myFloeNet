"""Visual tokens, colour ramps and the Qt style sheet."""
from __future__ import annotations

import math

from PySide6.QtGui import QColor, QFont, QPalette

LIGHT = {
    "name": "light",
    "canvas": "#EDF0F2", "grid": "#C9D0D6", "panel": "#F7F8F9", "surface": "#FFFFFF",
    "border": "#D5DBE0", "ink": "#1C252E", "ink2": "#56626D", "muted": "#87919A",
    "accent": "#5B4BD1", "accent_soft": "#E6E3FA", "edge": "#5E6B76",
    "series1": "#2a78d6", "series2": "#eb6834",
    "good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b",
    "chart_grid": "#E3E7EA", "chart_axis": "#B9C1C8",
}
DARK = {
    "name": "dark",
    "canvas": "#151A1F", "grid": "#2B333B", "panel": "#1B2128", "surface": "#1F262E",
    "border": "#323B45", "ink": "#E8ECF0", "ink2": "#A9B3BD", "muted": "#7C8792",
    "accent": "#9085e9", "accent_soft": "#2E2A52", "edge": "#93A0AB",
    "series1": "#3987e5", "series2": "#d95926",
    "good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b",
    "chart_grid": "#2A3139", "chart_axis": "#3E4852",
}

# Compact engineering-desktop style (default): neutral grey panels, white fields, blue selection.
CLASSIC = {
    "name": "classic",
    "canvas": "#F4F6F8", "grid": "#C9D0D6", "panel": "#EEF0F2", "surface": "#FFFFFF",
    "border": "#C5CBD1", "ink": "#16191D", "ink2": "#4A525A", "muted": "#7E868E",
    "accent": "#1F64B5", "accent_soft": "#D6E6F7", "edge": "#4C5660",
    "series1": "#2a78d6", "series2": "#eb6834",
    "good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b",
    "chart_grid": "#E3E7EA", "chart_axis": "#B9C1C8", "required": "#1452B8", "radius": 3,
}
LIGHT.setdefault("required", "#3A4BC4")
DARK.setdefault("required", "#8FB4FF")
APP_THEMES = {"classic": CLASSIC, "light": LIGHT, "dark": DARK}

# Canvas (modelling window) backgrounds, independent of the application style.
# Each preset: background top / bottom colour (vertical gradient), text and line colours.
CANVAS_PRESETS = {
    "blue": {"label": "Blue", "bg1": "#2D5794", "bg2": "#132A4D", "ink": "#FFFFFF", "ink2": "#D5E1F0",
             "grid": "#4E73A8", "edge": "#E4ECF5", "surface": "#1C365E", "border": "#8FA9CC", "dark": True},
    "black": {"label": "Black", "bg1": "#000000", "bg2": "#000000", "ink": "#FFFFFF", "ink2": "#C9CED4",
              "grid": "#2A2F35", "edge": "#D8DDE2", "surface": "#15191D", "border": "#6A737C", "dark": True},
    "gradient": {"label": "Gradient", "bg1": "#5F7A96", "bg2": "#DDE4EA", "ink": "#0E1216", "ink2": "#2E3740",
                 "grid": "#9AAABA", "edge": "#28313A", "surface": "#F7F9FB", "border": "#59656F", "dark": False},
    "light": {"label": "Light", "bg1": None, "bg2": None, "dark": None},
}


def canvas_colors(theme: dict, preset: str = "light", custom: tuple | None = None) -> dict:
    """Theme dictionary for the modelling window: the application theme with the canvas preset applied.
    `custom` = (top, bottom) colours of the gradient preset."""
    t = dict(theme)
    c = CANVAS_PRESETS.get(preset, CANVAS_PRESETS["light"])
    if preset == "light" or c.get("bg1") is None:
        t["canvas2"] = t["canvas"]
        t["canvas_dark"] = t["name"] == "dark"
        return t
    for k in ("ink", "ink2", "grid", "edge", "surface", "border"):
        t[k] = c[k]
    t["canvas"], t["canvas2"] = c["bg1"], c["bg2"]
    if preset == "gradient" and custom:
        t["canvas"], t["canvas2"] = custom
        dark = luminance(QColor(custom[0])) + luminance(QColor(custom[1])) < 0.36
        if dark:
            t.update({"ink": "#FFFFFF", "ink2": "#D9E0E7", "edge": "#E8EDF2", "surface": "#1D2732",
                      "grid": "#7A8896", "border": "#9AA7B4"})
        t["canvas_dark"] = dark
    else:
        t["canvas_dark"] = bool(c["dark"])
    t["accent"] = "#FFB000" if t["canvas_dark"] else theme["accent"]
    return t


# Sequential ramps (light -> dark) anchored on the reference palette hues.
RAMPS = {
    "pressure": ("#cde2fb", "#0d366b"),     # blue
    "temperature": ("#fcdccb", "#7a2a0b"),  # orange
    "swirl": ("#c8efe0", "#0a573c"),        # aqua
    "flow": ("#cde2fb", "#0d366b"),
}


# ---------------------------------------------------------------- OKLab
def _srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lin_to_srgb(c):
    c = min(max(c, 0.0), 1.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _hex_to_oklab(h):
    q = QColor(h)
    r, g, b = (_srgb_to_lin(x) for x in (q.redF(), q.greenF(), q.blueF()))
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l_, m_, s_))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _oklab_to_qcolor(L, a, b):
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return QColor.fromRgbF(_lin_to_srgb(r), _lin_to_srgb(g), _lin_to_srgb(bb))


class Ramp:
    def __init__(self, lo_hex, hi_hex, n=64):
        a, b = _hex_to_oklab(lo_hex), _hex_to_oklab(hi_hex)
        self.lut = [_oklab_to_qcolor(*(a[k] + (b[k] - a[k]) * i / (n - 1) for k in range(3))) for i in range(n)]

    def color(self, t: float) -> QColor:
        t = min(max(t, 0.0), 1.0)
        return QColor(self.lut[int(round(t * (len(self.lut) - 1)))])


_RAMP_CACHE = {}


class Rainbow:
    """Classic CAE contour map blue -> cyan -> green -> yellow -> red, optionally in discrete bands."""
    STOPS = ["#1238C8", "#1E8FE6", "#22C7C2", "#3CC24A", "#C9D82B", "#F5A623", "#D7301F"]

    def __init__(self, levels: int = 0, reverse: bool = False):
        self.levels = levels
        self.reverse = reverse
        self.cols = [QColor(c) for c in self.STOPS]

    def color(self, t: float) -> QColor:
        t = min(max(t, 0.0), 1.0)
        if self.levels and self.levels > 1:
            k = min(int(t * self.levels), self.levels - 1)
            t = k / (self.levels - 1)
        if self.reverse:
            t = 1.0 - t
        x = t * (len(self.cols) - 1)
        i = min(int(x), len(self.cols) - 2)
        f = x - i
        a, b = self.cols[i], self.cols[i + 1]
        return QColor(int(a.red() + (b.red() - a.red()) * f), int(a.green() + (b.green() - a.green()) * f),
                      int(a.blue() + (b.blue() - a.blue()) * f))


def ramp(kind: str, dark: bool = False) -> Ramp:
    """Sequential ramp. On the dark canvas the ramp runs dark -> light so that
    larger values gain contrast against the background."""
    key = (kind, dark)
    if key not in _RAMP_CACHE:
        lo, hi = RAMPS.get(kind, RAMPS["pressure"])
        _RAMP_CACHE[key] = Ramp(hi, lo) if dark else Ramp(lo, hi)
    return _RAMP_CACHE[key]


def luminance(c: QColor) -> float:
    return 0.2126 * _srgb_to_lin(c.redF()) + 0.7152 * _srgb_to_lin(c.greenF()) + 0.0722 * _srgb_to_lin(c.blueF())


# ---------------------------------------------------------------- Qt theme
def ui_font(size=9.0, bold=False) -> QFont:
    f = QFont()
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"])
    f.setPointSizeF(size)
    if bold:
        f.setWeight(QFont.DemiBold)
    return f


def apply_theme(app, t: dict):
    app.setStyle("Fusion")
    pal = QPalette()
    c = lambda k: QColor(t[k])
    pal.setColor(QPalette.Window, c("panel"))
    pal.setColor(QPalette.WindowText, c("ink"))
    pal.setColor(QPalette.Base, c("surface"))
    pal.setColor(QPalette.AlternateBase, c("panel"))
    pal.setColor(QPalette.Text, c("ink"))
    pal.setColor(QPalette.Button, c("surface"))
    pal.setColor(QPalette.ButtonText, c("ink"))
    pal.setColor(QPalette.Highlight, c("accent"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, c("surface"))
    pal.setColor(QPalette.ToolTipText, c("ink"))
    pal.setColor(QPalette.PlaceholderText, c("muted"))
    pal.setColor(QPalette.Link, c("accent"))
    pal.setColor(QPalette.Disabled, QPalette.Text, c("muted"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, c("muted"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, c("muted"))
    app.setPalette(pal)
    app.setFont(ui_font(9.0))
    app.setStyleSheet(style_sheet(t))


def style_sheet(t: dict) -> str:
    r = t.get("radius", 6)
    r2 = max(r - 1, 2)
    return f"""
QMainWindow, QDialog {{ background: {t['panel']}; }}
QToolBar {{ background: {t['panel']}; border: none; border-bottom: 1px solid {t['border']};
           padding: 4px 6px; spacing: 2px; }}
QToolBar QToolButton {{ border: 1px solid transparent; border-radius: {r}px; padding: 4px 6px; color: {t['ink']}; }}
QToolBar QToolButton:hover {{ background: {t['surface']}; border-color: {t['border']}; }}
QToolBar QToolButton:checked {{ background: {t['accent_soft']}; border-color: {t['accent']}; }}
QToolButton#solveButton {{ background: {t['accent']}; color: #FFFFFF; font-weight: 600;
           padding: 5px 14px; border-radius: {r}px; }}
QToolButton#solveButton:hover {{ background: {t['accent']}; border-color: {t['ink']}; }}
QToolButton#solveButton:disabled {{ background: {t['border']}; color: {t['muted']}; }}
QDockWidget {{ color: {t['ink']}; font-weight: 600; }}
QDockWidget::title {{ background: {t['panel']}; padding: 6px 8px; border-bottom: 1px solid {t['border']}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {t['border']}; background: {t['surface']}; }}
QTabBar::tab {{ background: transparent; color: {t['ink2']}; padding: 6px 12px; border: none;
              border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t['ink']}; border-bottom: 2px solid {t['accent']}; }}
QTabBar::tab:hover {{ color: {t['ink']}; }}
QTableView, QTableWidget, QTreeWidget, QListWidget, QTextEdit, QTextBrowser, QPlainTextEdit {{
    background: {t['surface']}; border: none; gridline-color: {t['chart_grid']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']}; }}
QHeaderView::section {{ background: {t['panel']}; color: {t['ink2']}; border: none;
    border-bottom: 1px solid {t['border']}; border-right: 1px solid {t['chart_grid']}; padding: 4px 6px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {t['surface']}; border: 1px solid {t['border']};
    border-radius: {r2}px; padding: 3px 6px; color: {t['ink']}; min-height: 18px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {t['critical']}; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']}; }}
QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {r}px;
    padding: 5px 12px; color: {t['ink']}; }}
QPushButton:hover {{ border-color: {t['ink2']}; }}
QPushButton[primary="true"] {{ background: {t['accent']}; border-color: {t['accent']}; color: #FFFFFF; font-weight: 600; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: {t['panel']}; color: {t['ink2']}; border-top: 1px solid {t['border']}; }}
QStatusBar QLabel {{ color: {t['ink2']}; padding: 0 6px; }}
QMenuBar {{ background: {t['panel']}; color: {t['ink']}; }}
QMenuBar::item:selected {{ background: {t['surface']}; }}
QMenu {{ background: {t['surface']}; color: {t['ink']}; border: 1px solid {t['border']}; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['ink']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}
QToolTip {{ background: {t['surface']}; color: {t['ink']}; border: 1px solid {t['border']}; padding: 4px; }}
QPlainTextEdit#descEdit {{ border: 1px solid {t['border']}; border-radius: 5px; padding: 4px; }}
QLabel#sectionLabel {{ color: {t['ink']}; font-weight: 600; padding-top: 10px; }}
QLabel#unitLabel {{ color: {t['muted']}; }}
QLabel#hintLabel {{ color: {t['ink2']}; }}
QLabel#titleLabel {{ color: {t['ink']}; font-size: 12pt; font-weight: 600; }}
QLabel#typeLabel {{ color: {t['ink2']}; }}
QFrame#hairline {{ background: {t['border']}; max-height: 1px; min-height: 1px; border: none; }}
QGroupBox {{ border: 1px solid {t['border']}; border-radius: 6px; margin-top: 14px; padding: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {t['ink']}; font-weight: 600; }}
QCheckBox {{ color: {t['ink']}; }}
QSplitter::handle {{ background: {t['border']}; }}
QWidget#propHead {{ background: {t['panel']}; border-bottom: 1px solid {t['border']}; }}
QWidget#propFoot {{ background: {t['panel']}; border-top: 1px solid {t['border']}; }}
QLabel#idLabel {{ color: {t['accent']}; font-weight: 600; }}
QTreeWidget#propGrid {{ alternate-background-color: {t['panel']}; }}
QTreeWidget#propGrid QLineEdit, QTreeWidget#propGrid QComboBox {{ border: none; border-radius: 0; background: transparent;
    padding: 0 4px; min-height: 16px; }}
QTreeWidget#propGrid QLineEdit:focus {{ background: {t['surface']}; border: 1px solid {t['accent']}; }}
QTreeWidget#propGrid QLineEdit[invalid="true"] {{ border: 1px solid {t['critical']}; }}
QTreeView::item {{ padding: 2px 0; }}
QTreeView::item:selected {{ background: {t['accent_soft']}; color: {t['ink']}; }}
QDockWidget::close-button, QDockWidget::float-button {{ border: none; background: transparent; }}
""" + (CLASSIC_EXTRA.format(**t) if t.get("name") == "classic" else "")


CLASSIC_EXTRA = """
QDockWidget::title {{ background: {accent}; color: #FFFFFF; padding: 4px 8px; border: none; }}
QDockWidget {{ color: #FFFFFF; font-weight: 600; }}
QTabBar::tab {{ background: {panel}; color: {ink2}; padding: 4px 12px; border: 1px solid {border};
    border-bottom: none; margin-right: 1px; border-top-left-radius: 3px; border-top-right-radius: 3px; }}
QTabBar::tab:selected {{ background: {surface}; color: {ink}; border-bottom: 2px solid {accent}; }}
QToolBar {{ border-bottom: 1px solid {border}; padding: 2px 4px; }}
QHeaderView::section {{ background: {panel}; color: {ink}; font-weight: 600; }}
"""
