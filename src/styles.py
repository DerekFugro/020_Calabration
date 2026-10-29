"""styles.py — Dark-mode colour constants, QPalette, and Qt stylesheet.

Import this module in every widget file instead of hard-coding colours.
"""

from PySide6.QtGui import QColor, QPalette

# ── Colour palette (R, G, B) ─────────────────────────────────────────────────
C_BG           = (30, 30, 30)
C_BG_WIDGET    = (45, 45, 45)
C_BG_BASE      = (22, 22, 22)
C_BG_INPUT     = (38, 38, 38)
C_TEXT         = (220, 220, 220)
C_TEXT_DIM     = (140, 140, 140)
C_ACCENT       = (66, 165, 245)
C_ACCENT_DARK  = (21, 101, 192)
C_BORDER       = (65, 65, 65)
C_GREEN        = (76, 175, 80)
C_AMBER        = (230, 119, 0)
C_RED          = (183, 28, 28)
C_GREEN_BG     = (27, 94, 32)
C_AMBER_BG     = (102, 60, 0)
C_RED_BG       = (74, 20, 20)

# ── Layout constants ─────────────────────────────────────────────────────────
MARGIN      = 14
SPACING     = 8
ROW_H       = 28
BUTTON_H    = 32
INPUT_H     = 28
SECTION_H   = 24
BADGE_H     = 40

# ── Verdict → (text_rgb, bg_rgb) ─────────────────────────────────────────────
VERDICT_COLOURS = {
    "Excellent":          (C_GREEN, C_GREEN_BG),
    "Acceptable":         (C_AMBER, C_AMBER_BG),
    "Needs Improvement":  (C_RED,   C_RED_BG),
}


def build_dark_palette() -> QPalette:
    """Return a QPalette suitable for dark-mode with Fusion style."""
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(*C_BG))
    p.setColor(QPalette.ColorRole.WindowText,      QColor(*C_TEXT))
    p.setColor(QPalette.ColorRole.Base,            QColor(*C_BG_BASE))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(*C_BG_WIDGET))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(*C_TEXT))
    p.setColor(QPalette.ColorRole.ToolTipText,     QColor(*C_TEXT))
    p.setColor(QPalette.ColorRole.Text,            QColor(*C_TEXT))
    p.setColor(QPalette.ColorRole.Button,          QColor(*C_BG_WIDGET))
    p.setColor(QPalette.ColorRole.ButtonText,      QColor(*C_TEXT))
    p.setColor(QPalette.ColorRole.BrightText,      QColor(*C_RED))
    p.setColor(QPalette.ColorRole.Link,            QColor(*C_ACCENT))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(*C_ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    return p


def _rgb(t: tuple) -> str:
    return f"rgb({t[0]},{t[1]},{t[2]})"


STYLESHEET_MAIN = f"""
QWidget {{
    background-color: {_rgb(C_BG)};
    color: {_rgb(C_TEXT)};
    font-size: 10pt;
    font-family: Segoe UI, Arial, sans-serif;
}}
QGroupBox {{
    border: 1px solid {_rgb(C_BORDER)};
    border-radius: 5px;
    margin-top: 10px;
    padding-top: 6px;
    font-weight: bold;
    font-size: 9pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {_rgb(C_TEXT_DIM)};
}}
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {_rgb(C_BG_INPUT)};
    border: 1px solid {_rgb(C_BORDER)};
    border-radius: 3px;
    padding: 3px 7px;
    color: {_rgb(C_TEXT)};
    min-height: {INPUT_H}px;
    selection-background-color: {_rgb(C_ACCENT)};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {_rgb(C_ACCENT)};
}}
QPushButton {{
    background-color: {_rgb(C_BG_WIDGET)};
    border: 1px solid {_rgb(C_BORDER)};
    border-radius: 4px;
    padding: 4px 16px;
    min-height: {BUTTON_H}px;
    color: {_rgb(C_TEXT)};
}}
QPushButton:hover {{
    background-color: rgb(60,60,60);
    border-color: {_rgb(C_ACCENT)};
}}
QPushButton:pressed {{
    background-color: {_rgb(C_ACCENT_DARK)};
}}
QPushButton:disabled {{
    color: rgb(80,80,80);
    border-color: rgb(50,50,50);
    background-color: rgb(35,35,35);
}}
QPushButton#primary_button {{
    background-color: {_rgb(C_ACCENT)};
    color: rgb(0,0,0);
    font-weight: bold;
    border: none;
}}
QPushButton#primary_button:hover {{
    background-color: rgb(100,181,246);
}}
QPushButton#primary_button:disabled {{
    background-color: rgb(40,70,100);
    color: rgb(80,80,80);
}}
QScrollArea {{
    border: none;
    background-color: {_rgb(C_BG)};
}}
QScrollBar:vertical {{
    width: 10px;
    background: {_rgb(C_BG)};
    border: none;
}}
QScrollBar::handle:vertical {{
    background: rgb(70,70,70);
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QStatusBar {{
    background-color: rgb(20,20,20);
    color: {_rgb(C_TEXT_DIM)};
    font-size: 9pt;
}}
QMessageBox {{
    background-color: {_rgb(C_BG_WIDGET)};
}}
"""
