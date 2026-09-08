import sys
import os
import re
import math
import logging
import xml.etree.ElementTree as ET

# 1. WICHTIG: PyQt5 muss registriert werden, BEVOR qt_material importiert wird!
os.environ['QT_API'] = 'pyqt5'
import PyQt5
from PyQt5 import QtCore, QtGui, QtWidgets, QtSvg

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QMessageBox,
    QScrollArea, QStackedWidget, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
    QToolButton, QSpacerItem
)
from PyQt5.QtGui import (
    QIcon, QPixmap, QDragEnterEvent, QDropEvent, QPainter, QColor, QPen,
    QFont, QLinearGradient, QPainterPath, QFontDatabase
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPoint, QEvent

# qt_material-Warnings ("must be imported after...", "QFontDatabase") unterdrücken
_log_level_backup = logging.root.level
logging.root.setLevel(logging.ERROR)
from qt_material import apply_stylesheet
logging.root.setLevel(_log_level_backup)


# ==============================================================================
#      KONFIGURATION & PFADE
# ==============================================================================
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
DEFAULT_FILE_PATH = os.path.join(BASE_DIR, "EDGE-Werkzeugliste-2026.gdml")
IMAGE_DIR = os.path.join(BASE_DIR, "images")


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = BASE_DIR
    return os.path.join(base_path, relative_path)


# ==============================================================================
#      FARBPALETTE: BLAUES BASIS-DESIGN + ORANGE AKZENTE
# ==============================================================================
BLUE          = "#448AFF"
BLUE_BRIGHT   = "#82B1FF"
ORANGE        = "#FF7A1A"
ORANGE_BRIGHT = "#FFA050"
BG_BASE       = "#0f1419"
BG_PANEL      = "#1e2433"
BG_PANEL_2    = "#141b24"
BORDER        = "#2d3748"
TEXT_MAIN     = "#e2e8f0"
TEXT_SEC      = "#64748b"
TEXT_MUTED    = "#475569"


# ==============================================================================
#      GDML PARSER
# ==============================================================================
def format_number(val):
    if val is None or val == '': return ''
    try:
        return f"{float(str(val).replace(',', '.')):.3f}"
    except (ValueError, TypeError):
        return str(val)


def normalize_str(s):
    return str(s).lower().replace(',', '.')


def clean_str(s):
    return re.sub(r'[^a-z0-9äöüß]', '', str(s).lower())


def _try_float(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(',', '.'))
    except (ValueError, TypeError):
        return None


def natural_sort_key(s):
    """Natürliche Sortierung: FR-D05 kommt vor FR-D040."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', str(s))]


def parse_technology_block(text):
    result = {}
    lines = text.splitlines()
    string_keys = []
    for line in lines:
        line = line.strip()
        if not line: continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\s*;\s*(\d+)\s*;\s*([^;]*)\s*;", line)
        if m: result[m.group(1)] = m.group(3).strip()
        if line.startswith('BEGIN_STRING;'):
            parts = line.split(';')
            if len(parts) >= 2: string_keys.append(parts[1].strip())
    for key in string_keys:
        marker = f"BEGIN_STRING; {key};;"
        idx = text.find(marker)
        if idx != -1:
            start = text.find(':', idx)
            end = text.find('\n', start)
            if start != -1 and end != -1:
                val = text[start + 1:end].strip()
                result[key] = val if val != '' else '—'
    return result


def parse_gdml(xml_content, filename):
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        raise ValueError(f"Fehler beim Parsen der XML: {e}")

    annotations = [el for el in root.iter() if el.tag.split('}')[-1] == 'Annotation']
    comps = [el for el in root.iter() if el.tag.split('}')[-1] == 'InterchangeableComponent']

    tool_data_map = {}
    assembly_map = {}

    for ann in annotations:
        name_attr = ann.attrib.get('name')
        if not name_attr: continue
        text = ann.text or ''

        if (m := re.match(r"^Tool_(\d+)_Technology$", name_attr)):
            tool_data_map.setdefault(m.group(1), {})['techText'] = text
        elif (m := re.match(r"^Tool_(\d+)_Name$", name_attr)):
            tool_data_map.setdefault(m.group(1), {})['name'] = text
        elif (m := re.match(r"^#cutter(\d+)$", name_attr)):
            tool_data_map.setdefault(m.group(1), {})['cutterXml'] = text
        elif (m := re.match(r"^ToolAssembly_(\d+)_Name$", name_attr)):
            assembly_map.setdefault(m.group(1), {})['name'] = text
        elif (m := re.match(r"^ToolAssembly_(\d+)_KbmDatabaseId$", name_attr)):
            assembly_map.setdefault(m.group(1), {})['kbmId'] = text
        elif (m := re.match(r"^ToolAssembly_(\d+)_Reference$", name_attr)):
            assembly_map.setdefault(m.group(1), {})['reference'] = text
        elif (m := re.match(r"^ToolAssembly_(\d+)_RootId$", name_attr)):
            assembly_map.setdefault(m.group(1), {})['rootId'] = text
        elif (m := re.match(r"^ToolAssembly_(\d+)_RootType$", name_attr)):
            assembly_map.setdefault(m.group(1), {})['rootType'] = text
        elif (m := re.match(r"^ToolAssembly_(\d+)_StationID$", name_attr)):
            assembly_map.setdefault(m.group(1), {})['stationId'] = text

    cutter_to_holder = {}
    node_file_map = {}   # PERFORMANCE: newNodeName -> componentFile nur EINMAL durchlaufen
    for comp in comps:
        file_attr = comp.attrib.get('componentFile', '')
        new_node = comp.attrib.get('newNodeName', '')
        if new_node:
            node_file_map[new_node] = file_attr
        if file_attr.startswith('#cutter'):
            cutter_num = file_attr.replace('#cutter', '')
            target = comp.attrib.get('targetNodeName', '')
            if target:
                parts = target.split(':')
                if len(parts) >= 3 and parts[2].isdigit():
                    cutter_to_holder[cutter_num] = parts[2]

    tools = []
    for num, data in tool_data_map.items():
        if not data.get('techText') and not data.get('name'): continue

        tech_data = parse_technology_block(data.get('techText', ''))
        tool_name = data.get('name') or tech_data.get('ToolID') or tech_data.get('Tool_2_Name') or f"Werkzeug {num}"
        holder_node = cutter_to_holder.get(num)
        assembly_name, assembly_root_id, assembly_station_id, assembly_type = '—', '—', '—', '—'

        if holder_node and holder_node in assembly_map:
            ass = assembly_map[holder_node]
            assembly_name = ass.get('name', '—')
            assembly_root_id = ass.get('rootId', '—')
            assembly_station_id = ass.get('stationId', '—')
            assembly_type = ass.get('rootType', '—')

        holder_path = '—'
        cf = node_file_map.get(holder_node, '')
        if cf and not cf.startswith('#'):
            holder_path = cf

        spindle = tech_data.get('SpindleDirection')
        spindle_str = 'Linkslauf (M4)' if spindle == '-1' else 'Rechtslauf (M3)' if spindle == '1' else spindle or '—'

        coolant_val = tech_data.get('NewCoolant') or tech_data.get('Coolant')
        coolant_str = 'vorhanden' if coolant_val == '1' else 'nicht vorhanden' if coolant_val == '0' else coolant_val or '—'

        status_machine = '—'
        if assembly_name:
            ass_upper = assembly_name.upper()
            if 'FIX' in ass_upper:
                status_machine = 'FIX'
            elif 'RÜST' in ass_upper:
                status_machine = 'RÜST'

        raw_length = tech_data.get('OverallLength')
        raw_shift_z = tech_data.get('ToolShiftZ')
        ausspann_str = '—'
        if raw_length or raw_shift_z:
            try:
                val_len = float(str(raw_length).replace(',', '.')) if raw_length else 0.0
                val_z = float(str(raw_shift_z).replace(',', '.')) if raw_shift_z else 0.0
                ausspann_str = f"{(val_len - val_z):.3f}"
            except ValueError:
                pass

        tool = {
            'Werkzeugname': tool_name,
            'Werkzeugnummer': format_number(tech_data.get('ToolNumber')),
            'Werkzeug-ID': tech_data.get('ToolID', '—'),
            'Durchmesser (mm)': format_number(tech_data.get('ToolDiameter')),
            'Schneidenlänge (mm)': format_number(tech_data.get('CuttingLength')),
            'Gesamtlänge (mm)': format_number(tech_data.get('OverallLength')),
            'Ausspannlänge (mm)': ausspann_str,
            'Schaftdurchmesser (mm)': format_number(tech_data.get('ShankDiameter')),
            'Anzahl Schneiden': format_number(tech_data.get('NumberOfFlutes')),
            'Werkzeugtyp': tech_data.get('ToolStyle', '—'),
            'Schafttyp': tech_data.get('ShankType', '—'),
            'Oberer Schaftdurchmesser (mm)': format_number(tech_data.get('ShankTopDiameter')),
            'Untere Länge (mm)': format_number(tech_data.get('ShankBottomLength')),
            'Schaftwinkel (°)': format_number(tech_data.get('ShankAngle')),
            'Längenkorrekturregister': tech_data.get('LengthCompRegister', '—'),
            'Spindeldrehrichtung': spindle_str,
            'Kühlung': coolant_str,
            'Beschichtung': tech_data.get('ToolMaterial', '—'),
            'Halterdurchmesser (mm)': format_number(tech_data.get('HolderDiameter')),
            'Versatz X (mm)': format_number(tech_data.get('ToolShiftX')),
            'Versatz Y (mm)': format_number(tech_data.get('ToolShiftY')),
            'Versatz Z (mm)': format_number(tech_data.get('ToolShiftZ')),
            'Offset X (mm)': format_number(tech_data.get('ToolOffsetX')),
            'Offset Y (mm)': format_number(tech_data.get('ToolOffsetY')),
            'Offset Z (mm)': format_number(tech_data.get('ToolOffsetZ')),
            'Rotation X (°)': format_number(tech_data.get('ToolRotationX')),
            'Rotation Y (°)': format_number(tech_data.get('ToolRotationY')),
            'Rotation Z (°)': format_number(tech_data.get('ToolRotationZ')),
            'Vektor X': tech_data.get('ToolVectorX', '—'),
            'Vektor Y': tech_data.get('ToolVectorY', '—'),
            'Vektor Z': tech_data.get('ToolVectorZ', '—'),
            'Simulationsfarbe': tech_data.get('SimulationColor', '—'),
            'Werkzeugausrichtung': tech_data.get('Orientation', '—'),
            'Einheit': tech_data.get('ToolUnit', '—'),
            'Schutzebene (mm)': format_number(tech_data.get('InitialClearance')),
            'Kühlungsdruck': tech_data.get('CoolantPressure', '—'),
            'Kühlungsdruck-Wert': format_number(tech_data.get('CoolantPressureValue')),
            'Standard-Kontrollpunkt': tech_data.get('DefaultControlPoint', '—'),
            'Kommentar': tech_data.get('Comment', '—'),
            'Aufnahme': holder_path,
            'Aufnahmegröße': assembly_name,
            'Baugruppe': assembly_name,
            'Baugruppentyp': assembly_type,
            'Root-ID': assembly_root_id,
            'Station-ID': assembly_station_id,
            'Status Maschine': status_machine,
            'Dateiname': filename
        }

        for k, v in tool.items():
            if v is None or v == '': tool[k] = '—'
        tools.append(tool)
    return tools


# ==============================================================================
#      RELEVANZ-SCORING FÜR DIE SUCHE
# ==============================================================================
def _token_score(tool, token):
    tn = normalize_str(token)
    tc = clean_str(token)
    if not tn:
        return 0
    tnum = _try_float(tn)

    score = 0
    matched = False

    raw_name = tool.get('Werkzeugname', '') or ''
    name = normalize_str(raw_name)
    name_clean = clean_str(raw_name)

    # ---------- 1) NAME (höchste Priorität) ----------
    if tn in name or (tc and tc in name_clean):
        matched = True
        if name == tn:
            score += 10000
        elif name.startswith(tn):
            score += 5000
        elif re.search(r'[^a-z0-9äöüß]' + re.escape(tn), name):
            score += 3000
        else:
            score += 2000

        if tnum is not None and tnum.is_integer():
            m = re.search(r'(\d+)$', name_clean)
            if m and int(m.group(1)) == int(tnum):
                score += 2500

    # ---------- 2) NUMERISCHE FELDER ----------
    if tnum is not None:
        diam_raw = tool.get('Durchmesser (mm)', '')
        diam = _try_float(diam_raw)
        if diam is not None:
            if abs(diam - tnum) < 1e-9:
                score += 4000
                matched = True
            elif normalize_str(diam_raw).startswith(tn):
                score += 1200
                matched = True

        num = _try_float(tool.get('Werkzeugnummer', ''))
        if num is not None and abs(num - tnum) < 1e-9:
            score += 3500
            matched = True

    # ---------- 3) WEITERE FELDER ----------
    for field, pts in (('Werkzeug-ID', 600),
                       ('Werkzeugtyp', 500),
                       ('Kommentar', 200),
                       ('Aufnahme', 100)):
        val = normalize_str(tool.get(field, ''))
        if val and tn in val:
            score += pts
            matched = True

    return score if matched else 0


# ==============================================================================
#      GLOW-HELPER
# ==============================================================================
def add_glow(widget, color=QColor(255, 122, 26), blur=30, alpha=90):
    eff = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    c.setAlpha(alpha)
    eff.setColor(c)
    eff.setBlurRadius(blur)
    eff.setOffset(0, 0)
    widget.setGraphicsEffect(eff)
    return eff


# ==============================================================================
#      PLATZHALTER-ICON (Detailseite, kein Text)
# ==============================================================================
class PlaceholderIconWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        w = self.width()
        h = self.height()
        size = min(w, h) * 0.5
        cx = w / 2
        cy = h / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(40, 50, 65, 180))
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(size * 0.55), int(size * 0.55))

        pen = QPen(QColor(255, 138, 66, 210))
        pen.setWidth(max(3, int(size * 0.04)))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        shaft_w = size * 0.12
        shaft_h = size * 0.3
        shaft_x = cx - shaft_w / 2
        shaft_y = cy - size * 0.35
        painter.drawRect(int(shaft_x), int(shaft_y), int(shaft_w), int(shaft_h))

        cut_w = size * 0.2
        cut_h = size * 0.25
        cut_x = cx - cut_w / 2
        cut_y = cy - size * 0.05
        painter.drawRect(int(cut_x), int(cut_y), int(cut_w), int(cut_h))

        pen2 = QPen(QColor(255, 138, 66, 140))
        pen2.setWidth(max(2, int(size * 0.025)))
        painter.setPen(pen2)
        for i in range(3):
            y_off = cut_y + cut_h * (0.2 + i * 0.3)
            painter.drawLine(int(cut_x + 2), int(y_off), int(cut_x + cut_w - 2), int(y_off + cut_h * 0.1))

        pen3 = QPen(QColor(255, 138, 66, 210))
        pen3.setWidth(max(3, int(size * 0.04)))
        painter.setPen(pen3)
        tip_y = cut_y + cut_h
        painter.drawLine(int(cx), int(tip_y), int(cx), int(tip_y + size * 0.08))

        painter.end()


# ==============================================================================
#      BILD-WIDGET (Detailseite)
# ==============================================================================
class ResizableImageLabel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._show_placeholder = True
        self._placeholder_widget = None
        self._image_label = None
        self._setup_ui()

    def _setup_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._placeholder_widget = PlaceholderIconWidget()
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setScaledContents(False)

        self._layout.addWidget(self._placeholder_widget)
        self._layout.addWidget(self._image_label)
        self._image_label.hide()

    def set_image(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._show_placeholder = False
        self._placeholder_widget.hide()
        self._image_label.show()
        self._update_image()

    def set_placeholder(self):
        self._pixmap = None
        self._show_placeholder = True
        self._image_label.hide()
        self._placeholder_widget.show()

    def resizeEvent(self, event):
        self._update_image()
        super().resizeEvent(event)

    def _update_image(self):
        if self._pixmap and not self._pixmap.isNull() and not self._show_placeholder:
            available = self._image_label.size()
            if available.width() > 0 and available.height() > 0:
                scaled = self._pixmap.scaled(
                    available, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self._image_label.setPixmap(scaled)


# ==============================================================================
#      WERKZEUG-KACHEL (Tile) – orange Umrandung, Name + ⌀ + Ausspannlänge
# ==============================================================================
class ToolTileWidget(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, tool_data, parent=None):
        super().__init__(parent)
        self.tool_data = tool_data
        self.setObjectName("toolTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(150)
        self.setMinimumWidth(220)

        self._full_name = self.tool_data.get('Werkzeugname', 'Unbenannt')
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        # Name (fett, wird bei Platzmangel gekürzt)
        self._name_label = QLabel(self._full_name)
        self._name_label.setObjectName("tileName")
        self._name_label.setToolTip(self._full_name)
        layout.addWidget(self._name_label)

        # Durchmesser
        diam = self.tool_data.get('Durchmesser (mm)', '—')
        diam_text = f"⌀ {diam} mm" if diam and diam != '—' else "⌀ —"
        diam_label = QLabel(diam_text)
        diam_label.setObjectName("tileDiam")
        layout.addWidget(diam_label)

        # Ausspannlänge
        aus = self.tool_data.get('Ausspannlänge (mm)', '—')
        aus_text = f"Ausspannlänge: {aus} mm" if aus and aus != '—' else "Ausspannlänge: —"
        aus_label = QLabel(aus_text)
        aus_label.setObjectName("tileAus")
        layout.addWidget(aus_label)

        layout.addStretch(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Namen sauber kürzen ("…") statt abschneiden
        fm = self._name_label.fontMetrics()
        available = max(self.width() - 40, 60)
        self._name_label.setText(fm.elidedText(self._full_name, Qt.ElideRight, available))

    def mouseReleaseEvent(self, event):
        if self.rect().contains(event.pos()):
            self.clicked.emit(self.tool_data)
        super().mouseReleaseEvent(event)


# ==============================================================================
#      HAUPTFENSTER
# ==============================================================================
class MainWindow(QMainWindow):
    RESULT_BATCH = 60
    TILE_MIN_WIDTH = 250    # Mindestbreite einer Kachel -> bestimmt Spaltenanzahl
    TILE_MAX_COLS = 6

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ToolService EDGE Werkzeugliste")
        self.setMinimumSize(1200, 800)
        self.resize(1600, 1000)

        # Icon nur setzen wenn eine echte Logo-Datei existiert
        app_icon_path = resource_path("assets/logo.png")
        if os.path.exists(app_icon_path):
            self.setWindowIcon(QIcon(app_icon_path))

        self._set_application_style()
        self.setAcceptDrops(True)

        self.all_tools = []
        self.filtered_tools = []
        self._current_results = []
        self._tile_widgets = []
        self._shown_count = 0
        self._pending_query = ""
        self._grid_cols = 0

        # ---------- Glow-Puls (Timer-basiert, kompatibel mit allen PyQt5-Versionen) ----------
        self._glow_targets = []   # [effect, lo, hi, speed, phase]
        self._glow_t = 0.0
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(40)
        self._glow_timer.timeout.connect(self._tick_glow)

        # ---------- Such-Debounce ----------
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._run_pending_search)

        # ---------- Relayout-Debounce fürs Kachel-Grid ----------
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(120)
        self._relayout_timer.timeout.connect(self._arrange_tiles)

        self._build_ui()

        # Resize des Scroll-Viewports beobachten -> Grid neu anordnen
        self.results_scroll.viewport().installEventFilter(self)

        self.load_gdml_file(DEFAULT_FILE_PATH, initial=True)

    # ------------------------------------------------------------------
    #  GLOW-PULS (sinusbasiert)
    # ------------------------------------------------------------------
    def _pulse_glow(self, effect, lo=22, hi=45, speed=0.002):
        phase = len(self._glow_targets) * 1.3
        self._glow_targets.append([effect, lo, hi, speed, phase])
        if not self._glow_timer.isActive():
            self._glow_timer.start()

    def _tick_glow(self):
        self._glow_t += 40.0
        dead = []
        for i, (eff, lo, hi, speed, phase) in enumerate(self._glow_targets):
            v = lo + (hi - lo) * (0.5 + 0.5 * math.sin(self._glow_t * speed + phase))
            try:
                eff.setBlurRadius(int(v))
            except RuntimeError:
                dead.append(i)
        for i in reversed(dead):
            self._glow_targets.pop(i)
        if not self._glow_targets:
            self._glow_timer.stop()

    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if obj is self.results_scroll.viewport() and event.type() == QEvent.Resize:
            self._relayout_timer.start()
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    def _set_application_style(self):
        app = QApplication.instance()

        fallback_font = "Helvetica" if sys.platform == "darwin" else "Segoe UI"
        extra = {
            'accent_color': BLUE,
            'secondaryLightColor': BG_PANEL,
            'font_family': fallback_font
        }

        # qt_material-Warnings unterdrücken
        prev_level = logging.root.level
        logging.root.setLevel(logging.ERROR)
        apply_stylesheet(app, theme='dark_blue.xml', extra=extra)
        logging.root.setLevel(prev_level)

        stylesheet = app.styleSheet()
        stylesheet = re.sub(r'image:\s*url\(.*?\.svg\);', 'image: none;', stylesheet)

        custom_css = stylesheet + f"""
        * {{
            font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
        }}

        QMainWindow {{
            background-color: {BG_BASE};
        }}

        QScrollArea {{
            border: none;
            background: transparent;
        }}

        QScrollBar:vertical {{
            background-color: {BG_BASE};
            width: 8px;
            border-radius: 4px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background-color: {BORDER};
            border-radius: 4px;
            min-height: 40px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {ORANGE};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}

        QPushButton {{
            padding: 14px 24px;
            border-radius: 12px;
            font-weight: bold;
            font-size: 13pt;
            border: none;
        }}
        QPushButton:hover {{
            background-color: rgba(68, 138, 255, 0.18);
        }}
        QPushButton:pressed {{
            background-color: rgba(68, 138, 255, 0.32);
        }}

        QLineEdit {{
            padding: 16px 20px;
            border: 2px solid {BORDER};
            border-radius: 16px;
            background-color: #1a2332;
            font-size: 16pt;
            color: {TEXT_MAIN};
            selection-background-color: {BLUE};
        }}
        QLineEdit:focus {{
            border: 2px solid {BLUE};
            background-color: #1e2a3a;
        }}
        QLineEdit::placeholder {{
            color: {TEXT_MUTED};
        }}

        QLabel {{
            color: {TEXT_MAIN};
        }}

        /* ---------- Werkzeug-Kacheln: ORANGE Umrandung ---------- */
        ToolTileWidget {{
            background-color: {BG_PANEL};
            border: 2px solid rgba(255, 122, 26, 0.50);
            border-radius: 14px;
        }}
        ToolTileWidget:hover {{
            background-color: #253045;
            border: 2px solid {ORANGE};
        }}
        ToolTileWidget:pressed {{
            background-color: #2a3a55;
            border: 2px solid {ORANGE_BRIGHT};
        }}
        QLabel#tileName {{
            font-size: 14pt;
            font-weight: bold;
            color: {TEXT_MAIN};
            background: transparent;
            border: none;
        }}
        QLabel#tileDiam {{
            font-size: 12pt;
            font-weight: bold;
            color: {BLUE_BRIGHT};
            background: transparent;
            border: none;
        }}
        QLabel#tileAus {{
            font-size: 11pt;
            color: {TEXT_SEC};
            background: transparent;
            border: none;
        }}
        QLabel#resultsFooter {{
            color: {TEXT_SEC};
            font-size: 12pt;
            padding: 14px;
            background: transparent;
        }}
        """
        app.setStyleSheet(custom_css)

    # ------------------------------------------------------------------
    def _build_ui(self):
        central_widget = QWidget()
        central_widget.setStyleSheet(f"background-color: {BG_BASE};")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.page_stack = QStackedWidget()
        main_layout.addWidget(self.page_stack)

        self._build_home_page()
        self._build_detail_page()

    # ------------------------------------------------------------------
    #  STARTSEITE
    # ------------------------------------------------------------------
    def _build_home_page(self):
        home_page = QWidget()
        home_page.setStyleSheet(f"background-color: {BG_BASE};")
        home_layout = QVBoxLayout(home_page)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.setSpacing(0)

        top_container = QWidget()
        top_container.setStyleSheet(f"background-color: {BG_BASE};")
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(40, 24, 40, 16)
        top_layout.setSpacing(0)

        # ---------- Header Zeile 1: Titel (OHNE Symbol) + Button ----------
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title_label = QLabel("ToolService EDGE Werkzeugliste")
        title_label.setStyleSheet(
            f"font-size: 18pt; font-weight: bold; color: {BLUE}; background: transparent;"
        )
        header_row.addWidget(title_label)
        header_row.addStretch()

        btn_open = QPushButton("📁 Datei öffnen")
        btn_open.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_PANEL};
                color: {TEXT_SEC};
                padding: 10px 18px;
                border-radius: 10px;
                font-size: 12pt;
                border: 1px solid {BORDER};
            }}
            QPushButton:hover {{
                background-color: #253045;
                color: {TEXT_MAIN};
                border: 1px solid {BLUE};
            }}
        """)
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(self._open_file_dialog)
        header_row.addWidget(btn_open)

        top_layout.addLayout(header_row)

        # ---------- Header Zeile 2: Autor klein, rechts UNTER dem Button ----------
        author_row = QHBoxLayout()
        author_row.addStretch()
        author_label = QLabel("by Gschwendtner Johannes")
        author_label.setStyleSheet(
            f"font-size: 10pt; color: {TEXT_MUTED}; background: transparent;"
        )
        author_row.addWidget(author_label)
        top_layout.addLayout(author_row)

        top_layout.addSpacing(14)

        # ---------- Zentrierte Such-Sektion ----------
        search_center = QWidget()
        search_center.setStyleSheet("background: transparent;")
        search_center_layout = QVBoxLayout(search_center)
        search_center_layout.setAlignment(Qt.AlignCenter)
        search_center_layout.setSpacing(12)

        headline = QLabel("Werkzeuge durchsuchen")
        headline.setStyleSheet(
            "font-size: 31pt; font-weight: bold; color: #f5f7fa; background: transparent;"
        )
        headline.setAlignment(Qt.AlignCenter)
        # Oranger Glut-Glow + Puls (Akzent)
        self._pulse_glow(add_glow(headline, QColor(255, 122, 26), blur=35, alpha=110))
        search_center_layout.addWidget(headline)

        self.subtitle_label = QLabel("Tippe um zu suchen – Ergebnisse erscheinen sofort")
        self.subtitle_label.setStyleSheet(
            f"font-size: 13pt; color: {TEXT_SEC}; background: transparent;"
        )
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        search_center_layout.addWidget(self.subtitle_label)

        search_center_layout.addSpacing(20)

        search_wrapper = QWidget()
        search_wrapper.setStyleSheet("background: transparent;")
        search_wrapper_layout = QHBoxLayout(search_wrapper)
        search_wrapper_layout.setContentsMargins(0, 0, 0, 0)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍  Werkzeugname, Durchmesser, ID, Typ...")
        self.search_edit.setMinimumHeight(68)
        self.search_edit.textChanged.connect(self._on_search_changed)
        add_glow(self.search_edit, QColor(68, 138, 255), blur=24, alpha=45)
        search_wrapper_layout.addWidget(self.search_edit)

        search_center_layout.addWidget(search_wrapper)

        search_center.setMaximumWidth(900)

        top_layout.addWidget(search_center, 0, Qt.AlignHCenter)

        home_layout.addWidget(top_container, 0)

        # ---------- Glühende Trennlinie (Oranger Akzent) ----------
        separator = QFrame()
        separator.setFixedHeight(2)
        separator.setStyleSheet(
            "background: qlineargradient(x0:0, y0:0, x1:1, y1:0, "
            "stop:0 rgba(255,122,26,0), stop:0.5 rgba(255,122,26,170), "
            "stop:1 rgba(255,122,26,0)); border: none;"
        )
        self._pulse_glow(add_glow(separator, QColor(255, 122, 26), blur=18, alpha=120),
                         lo=10, hi=26, speed=0.0015)
        home_layout.addWidget(separator, 0)

        # ---------- Ergebnisbereich (Kachel-Grid) ----------
        results_container = QWidget()
        results_container.setStyleSheet(f"background-color: {BG_BASE};")
        results_layout = QVBoxLayout(results_container)
        results_layout.setContentsMargins(20, 10, 20, 10)
        results_layout.setSpacing(0)

        self.results_info = QLabel("")
        self.results_info.setStyleSheet(
            f"font-size: 12pt; color: {TEXT_SEC}; padding: 8px 12px; background: transparent;"
        )
        results_layout.addWidget(self.results_info, 0)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setStyleSheet("background: transparent; border: none;")

        # Body: Kachel-Grid + Footer
        self.results_body = QWidget()
        self.results_body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(self.results_body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(8)

        self.tiles_widget = QWidget()
        self.tiles_widget.setStyleSheet("background: transparent;")
        self.tiles_grid = QGridLayout(self.tiles_widget)
        self.tiles_grid.setSpacing(14)
        self.tiles_grid.setContentsMargins(4, 4, 4, 4)
        body_layout.addWidget(self.tiles_widget)

        self.results_footer = QLabel("")
        self.results_footer.setObjectName("resultsFooter")
        self.results_footer.setAlignment(Qt.AlignCenter)
        body_layout.addWidget(self.results_footer)

        body_layout.addStretch(1)

        self.results_scroll.setWidget(self.results_body)
        results_layout.addWidget(self.results_scroll, 1)

        self.results_scroll.verticalScrollBar().valueChanged.connect(self._on_results_scrolled)

        home_layout.addWidget(results_container, 1)

        self.page_stack.addWidget(home_page)

    # ------------------------------------------------------------------
    #  DETAILSEITE
    # ------------------------------------------------------------------
    def _build_detail_page(self):
        detail_page = QWidget()
        detail_page.setStyleSheet(f"background-color: {BG_BASE};")
        detail_main_layout = QVBoxLayout(detail_page)
        detail_main_layout.setContentsMargins(0, 0, 0, 0)
        detail_main_layout.setSpacing(0)

        # ---------- Top-Bar: Zurück-Button + Autor rechts darunter ----------
        back_bar = QFrame()
        back_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL_2};
                border-bottom: 1px solid {BORDER};
            }}
        """)
        back_bar_layout = QVBoxLayout(back_bar)
        back_bar_layout.setContentsMargins(20, 12, 20, 8)
        back_bar_layout.setSpacing(4)

        row1 = QHBoxLayout()
        self.btn_back = QPushButton()
        self.btn_back.setText("←   Zurück zur Übersicht")
        self.btn_back.setMinimumHeight(64)
        self.btn_back.setMinimumWidth(360)
        self.btn_back.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_PANEL};
                color: {BLUE_BRIGHT};
                border: 2px solid {BORDER};
                border-radius: 14px;
                font-size: 15pt;
                font-weight: bold;
                padding: 18px 34px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: #253045;
                border: 2px solid {BLUE};
            }}
            QPushButton:pressed {{
                background-color: #2a3a55;
                border: 2px solid {ORANGE};
            }}
        """)
        add_glow(self.btn_back, QColor(255, 122, 26), blur=26, alpha=70)  # oranger Glut-Schein
        self.btn_back.clicked.connect(self._go_back)
        row1.addWidget(self.btn_back)
        row1.addStretch()
        back_bar_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addStretch()
        author_label = QLabel("by Gschwendtner Johannes")
        author_label.setStyleSheet(
            f"font-size: 10pt; color: {TEXT_MUTED}; background: transparent;"
        )
        row2.addWidget(author_label)
        back_bar_layout.addLayout(row2)

        detail_main_layout.addWidget(back_bar, 0)

        # ---------- Detail-Content ----------
        detail_content = QWidget()
        detail_content.setStyleSheet("background: transparent;")
        content_layout = QHBoxLayout(detail_content)
        content_layout.setContentsMargins(30, 20, 30, 20)
        content_layout.setSpacing(30)

        left_side = QWidget()
        left_side.setStyleSheet("background: transparent;")
        left_layout = QVBoxLayout(left_side)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.detail_title = QLabel("Werkzeug")
        self.detail_title.setStyleSheet(
            "font-size: 27pt; font-weight: bold; color: #f5f7fa; background: transparent;"
        )
        self.detail_title.setWordWrap(True)
        add_glow(self.detail_title, QColor(68, 138, 255), blur=28, alpha=60)
        left_layout.addWidget(self.detail_title)

        self.detail_subtitle = QLabel("")
        self.detail_subtitle.setStyleSheet(f"""
            QLabel {{
                font-size: 14pt;
                color: {BLUE};
                font-weight: bold;
                background: transparent;
                padding: 4px 0;
            }}
        """)
        left_layout.addWidget(self.detail_subtitle)

        left_layout.addSpacing(8)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(
            "background: qlineargradient(x0:0, y0:0, x1:1, y1:0, "
            "stop:0 rgba(255,122,26,170), stop:1 rgba(255,122,26,0)); border: none;"
        )
        left_layout.addWidget(sep)
        left_layout.addSpacing(8)

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setStyleSheet("background: transparent; border: none;")

        self.detail_grid_container = QWidget()
        self.detail_grid_container.setStyleSheet("background: transparent;")
        self.detail_grid_layout = QGridLayout(self.detail_grid_container)
        self.detail_grid_layout.setAlignment(Qt.AlignTop)
        self.detail_grid_layout.setHorizontalSpacing(20)
        self.detail_grid_layout.setVerticalSpacing(8)
        self.detail_grid_layout.setColumnStretch(0, 0)
        self.detail_grid_layout.setColumnStretch(1, 1)
        self.detail_grid_layout.setColumnStretch(2, 0)
        self.detail_grid_layout.setColumnStretch(3, 1)

        detail_scroll.setWidget(self.detail_grid_container)
        left_layout.addWidget(detail_scroll, 1)

        content_layout.addWidget(left_side, 3)

        right_side = QWidget()
        right_side.setStyleSheet("background: transparent;")
        right_side.setMaximumWidth(450)
        right_side.setMinimumWidth(280)
        right_layout = QVBoxLayout(right_side)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        img_header = QLabel("Abbildung")
        img_header.setStyleSheet(
            f"font-size: 12pt; color: {TEXT_SEC}; font-weight: bold; "
            f"letter-spacing: 1px; background: transparent;"
        )
        right_layout.addWidget(img_header)

        img_frame = QFrame()
        img_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_PANEL_2};
                border: 2px solid {BORDER};
                border-radius: 16px;
            }}
        """)
        img_frame_layout = QVBoxLayout(img_frame)
        img_frame_layout.setContentsMargins(16, 16, 16, 16)

        self.image_widget = ResizableImageLabel()
        self.image_widget.setMinimumSize(250, 250)
        img_frame_layout.addWidget(self.image_widget, 1)

        right_layout.addWidget(img_frame, 1)

        content_layout.addWidget(right_side, 1)

        detail_main_layout.addWidget(detail_content, 1)

        self.page_stack.addWidget(detail_page)

    # ==================================================================
    #  NAVIGATION
    # ==================================================================
    def _go_back(self):
        self.page_stack.setCurrentIndex(0)
        self.search_edit.setFocus()

    def _show_tool_detail(self, tool):
        self._render_tool_detail(tool)
        self.page_stack.setCurrentIndex(1)

    # ==================================================================
    #  SUCHE
    # ==================================================================
    def _on_search_changed(self, text):
        self._pending_query = text.strip()
        if not self._pending_query:
            self._search_timer.stop()
            self._show_all_results()
            return
        self._search_timer.start()

    def _run_pending_search(self):
        query = self._pending_query
        if not query:
            return
        tokens = query.split()
        scored = []

        for tool in self.all_tools:
            total_score = 0
            all_match = True
            for token in tokens:
                s = _token_score(tool, token)
                if s <= 0:
                    all_match = False
                    break
                total_score += s
            if all_match:
                scored.append((total_score, tool))

        scored.sort(key=lambda pair: (-pair[0], natural_sort_key(pair[1].get('Werkzeugname', ''))))

        self.filtered_tools = [t for _, t in scored]
        self._display_results(self.filtered_tools)

    def _show_all_results(self):
        if self.all_tools:
            self.subtitle_label.setText(f"{len(self.all_tools)} Werkzeuge geladen – tippe um zu filtern")
            self._display_results(self.all_tools)
        else:
            self.subtitle_label.setText("Tippe um zu suchen – Ergebnisse erscheinen sofort")
            self._display_results([])

    # ==================================================================
    #  KACHEL-GRID (Lazy Loading + responsive Spalten)
    # ==================================================================
    def _arrange_tiles(self):
        """Ordnet alle Kacheln abhängig von der verfügbaren Breite an."""
        vp_width = self.results_scroll.viewport().width() or 1200
        cols = max(1, min(self.TILE_MAX_COLS,
                          int((vp_width - 16) // (self.TILE_MIN_WIDTH + 14))))

        grid = self.tiles_grid

        # Grid leeren (Widgets bleiben erhalten)
        while grid.count():
            grid.takeAt(0)

        # Alte Spalten-Stretches zurücksetzen
        for c in range(self._grid_cols):
            grid.setColumnStretch(c, 0)

        for idx, tile in enumerate(self._tile_widgets):
            r, c = divmod(idx, cols)
            grid.addWidget(tile, r, c)

        for c in range(cols):
            grid.setColumnStretch(c, 1)

        self._grid_cols = cols

    def _display_results(self, tools):
        self._current_results = tools
        self._shown_count = 0

        sb = self.results_scroll.verticalScrollBar()
        sb.blockSignals(True)
        self.results_body.setUpdatesEnabled(False)

        self._clear_results()

        count = len(tools)
        self.results_info.setText(f"{count} Werkzeug{'e' if count != 1 else ''} gefunden")

        batch = tools[:self.RESULT_BATCH]
        self._create_tiles(batch)
        self._shown_count = len(batch)
        self._arrange_tiles()
        self._update_footer()

        self.results_body.setUpdatesEnabled(True)
        sb.blockSignals(False)
        sb.setValue(0)

        QTimer.singleShot(0, self._ensure_scrollable)

    def _create_tiles(self, batch):
        for tool in batch:
            tile = ToolTileWidget(tool)
            tile.clicked.connect(self._show_tool_detail)
            self._tile_widgets.append(tile)

    def _append_results_batch(self):
        total = len(self._current_results)
        if self._shown_count >= total:
            return

        sb = self.results_scroll.verticalScrollBar()
        sb.blockSignals(True)
        self.results_body.setUpdatesEnabled(False)

        batch = self._current_results[self._shown_count:self._shown_count + self.RESULT_BATCH]
        self._create_tiles(batch)
        self._shown_count += len(batch)
        self._arrange_tiles()
        self._update_footer()

        self.results_body.setUpdatesEnabled(True)
        sb.blockSignals(False)

    def _ensure_scrollable(self):
        sb = self.results_scroll.verticalScrollBar()
        guard = 0
        while (sb.maximum() == 0
               and self._shown_count < len(self._current_results)
               and guard < 30):
            self._append_results_batch()
            guard += 1

    def _on_results_scrolled(self, value):
        sb = self.results_scroll.verticalScrollBar()
        if value >= sb.maximum() - 150:
            self._append_results_batch()

    def _update_footer(self):
        remaining = len(self._current_results) - self._shown_count
        if remaining > 0:
            self.results_footer.setText(f"⬇  {remaining} weitere Werkzeuge – scrollen zum Laden")
            self.results_footer.show()
        else:
            self.results_footer.setText("")

    def _clear_results(self):
        for tile in self._tile_widgets:
            self.tiles_grid.removeWidget(tile)
            tile.deleteLater()
        self._tile_widgets.clear()

    # ==================================================================
    #  DATEI LADEN
    # ==================================================================
    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "GDML-Datei auswählen", BASE_DIR, "GDML / XML Dateien (*.gdml *.xml);;Alle Dateien (*.*)"
        )
        if path:
            self.load_gdml_file(path)

    def load_gdml_file(self, path, initial=False):
        if not os.path.exists(path):
            if initial:
                self.subtitle_label.setText(f"⚠ Datei nicht gefunden: {os.path.basename(path)}")
            else:
                QMessageBox.critical(self, "Fehler", f"Konnte die Datei nicht finden:\n{path}")
            return

        try:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(path, "r", encoding="iso-8859-1") as f:
                    content = f.read()

            filename = os.path.basename(path)
            tools = parse_gdml(content, filename)
            tools.sort(key=lambda t: natural_sort_key(t.get('Werkzeugname', '')))

            if not tools:
                QMessageBox.warning(self, "Keine Daten", f"Keine Werkzeuge in {filename} gefunden.")
                return

            self.all_tools = tools
            self.subtitle_label.setText(f"{len(tools)} Werkzeuge geladen – tippe um zu filtern")
            self.search_edit.clear()
            self._display_results(tools)

            self.page_stack.setCurrentIndex(0)

        except Exception as e:
            QMessageBox.critical(self, "Ladefehler", f"Fehler beim Lesen der GDML-Datei:\n{e}")

    # ==================================================================
    #  DRAG & DROP
    # ==================================================================
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and event.mimeData().urls()[0].isLocalFile():
            path = event.mimeData().urls()[0].toLocalFile()
            if path.lower().endswith('.gdml') or path.lower().endswith('.xml'):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        path = event.mimeData().urls()[0].toLocalFile()
        self.load_gdml_file(path)

    # ==================================================================
    #  BILD LADEN
    # ==================================================================
    def _load_image(self, tool_name):
        if not tool_name or tool_name == '—':
            self.image_widget.set_placeholder()
            return

        extensions = [".png", ".jpg", ".jpeg", ".bmp"]
        safe_name = tool_name.replace("/", "_").replace("\\", "_")

        img_path = None
        for name in [tool_name, safe_name]:
            for ext in extensions:
                path = os.path.join(IMAGE_DIR, f"{name}{ext}")
                if os.path.exists(path):
                    img_path = path
                    break
                path_up = os.path.join(IMAGE_DIR, f"{name}{ext.upper()}")
                if os.path.exists(path_up):
                    img_path = path_up
                    break
            if img_path: break

        if img_path:
            pixmap = QPixmap(img_path)
            if not pixmap.isNull():
                self.image_widget.set_image(pixmap)
            else:
                self.image_widget.set_placeholder()
        else:
            self.image_widget.set_placeholder()

    # ==================================================================
    #  DETAIL-RENDERING
    # ==================================================================
    def _render_tool_detail(self, tool):
        tool_name = tool.get('Werkzeugname', 'Unbenanntes Werkzeug')
        self.detail_title.setText(tool_name)
        d = tool.get('Durchmesser (mm)', '—')
        typ = tool.get('Werkzeugtyp', '—')
        if d and d != '—':
            self.detail_subtitle.setText(f"⌀ {d} mm  ·  {typ}")
        else:
            self.detail_subtitle.setText(f"{typ}")

        self._load_image(tool_name)

        for i in reversed(range(self.detail_grid_layout.count())):
            widget = self.detail_grid_layout.itemAt(i).widget()
            if widget: widget.deleteLater()

        categories = {
            'Basisdaten': ['Werkzeugnummer', 'Werkzeug-ID', 'Werkzeugname', 'Werkzeugtyp', 'Einheit', 'Kommentar'],
            'Geometrie': ['Durchmesser (mm)', 'Schneidenlänge (mm)', 'Gesamtlänge (mm)', 'Ausspannlänge (mm)',
                          'Schaftdurchmesser (mm)', 'Oberer Schaftdurchmesser (mm)', 'Untere Länge (mm)',
                          'Schaftwinkel (°)', 'Halterdurchmesser (mm)', 'Anzahl Schneiden'],
            'Aufnahme & Halter': ['Aufnahme', 'Aufnahmegröße', 'Baugruppe', 'Baugruppentyp', 'Root-ID', 'Station-ID'],
            'Maschinenparameter': ['Längenkorrekturregister', 'Spindeldrehrichtung', 'Werkzeugausrichtung',
                                   'Schutzebene (mm)'],
            'Versatz & Offset': ['Versatz X (mm)', 'Versatz Y (mm)', 'Versatz Z (mm)', 'Offset X (mm)', 'Offset Y (mm)',
                                 'Offset Z (mm)'],
            'Rotation & Vektor': ['Rotation X (°)', 'Rotation Y (°)', 'Rotation Z (°)', 'Vektor X', 'Vektor Y',
                                  'Vektor Z'],
            'Kühlung & Material': ['Kühlung', 'Kühlungsdruck', 'Kühlungsdruck-Wert', 'Beschichtung'],
            'Status & Sonstiges': ['Status Maschine', 'Simulationsfarbe', 'Standard-Kontrollpunkt', 'Dateiname']
        }

        row = 0
        for cat_name, fields in categories.items():
            valid_fields = [f for f in fields if f in tool]
            if not valid_fields: continue

            if row > 0:
                spacer = QFrame()
                spacer.setFixedHeight(16)
                spacer.setStyleSheet("background: transparent;")
                self.detail_grid_layout.addWidget(spacer, row, 0, 1, 4)
                row += 1

            cat_frame = QFrame()
            cat_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {BG_PANEL_2};
                    border-radius: 8px;
                    padding: 4px;
                }}
            """)
            cat_layout_h = QHBoxLayout(cat_frame)
            cat_layout_h.setContentsMargins(12, 6, 12, 6)
            cat_label = QLabel(cat_name.upper())
            cat_label.setStyleSheet(
                f"font-weight: bold; color: {BLUE}; font-size: 11pt; "
                f"letter-spacing: 1.5px; background: transparent; border: none;"
            )
            cat_layout_h.addWidget(cat_label)
            cat_layout_h.addStretch()
            self.detail_grid_layout.addWidget(cat_frame, row, 0, 1, 4)
            row += 1

            for i in range(0, len(valid_fields), 2):
                f1 = valid_fields[i]
                v1 = tool.get(f1, '—')

                l1 = QLabel(f1)
                l1.setStyleSheet(
                    f"color: {TEXT_SEC}; font-size: 11pt; background: transparent; "
                    f"border: none; padding: 2px 0;"
                )
                l1.setWordWrap(True)

                val1 = QLabel(str(v1))
                if v1 != '—':
                    val1.setStyleSheet(
                        f"font-weight: 600; color: {TEXT_MAIN}; font-size: 13pt; "
                        f"background: transparent; border: none; padding: 2px 0;"
                    )
                else:
                    val1.setStyleSheet(
                        "color: #475569; font-size: 13pt; background: transparent; "
                        "border: none; padding: 2px 0;"
                    )
                val1.setWordWrap(True)
                val1.setTextInteractionFlags(Qt.TextSelectableByMouse)

                self.detail_grid_layout.addWidget(l1, row, 0, alignment=Qt.AlignTop | Qt.AlignLeft)
                self.detail_grid_layout.addWidget(val1, row, 1, alignment=Qt.AlignTop | Qt.AlignLeft)

                if i + 1 < len(valid_fields):
                    f2 = valid_fields[i + 1]
                    v2 = tool.get(f2, '—')

                    l2 = QLabel(f2)
                    l2.setStyleSheet(
                        f"color: {TEXT_SEC}; font-size: 11pt; background: transparent; "
                        f"border: none; padding: 2px 0;"
                    )
                    l2.setWordWrap(True)

                    val2 = QLabel(str(v2))
                    if v2 != '—':
                        val2.setStyleSheet(
                            f"font-weight: 600; color: {TEXT_MAIN}; font-size: 13pt; "
                            f"background: transparent; border: none; padding: 2px 0;"
                        )
                    else:
                        val2.setStyleSheet(
                            "color: #475569; font-size: 13pt; background: transparent; "
                            "border: none; padding: 2px 0;"
                        )
                    val2.setWordWrap(True)
                    val2.setTextInteractionFlags(Qt.TextSelectableByMouse)

                    self.detail_grid_layout.addWidget(l2, row, 2, alignment=Qt.AlignTop | Qt.AlignLeft)
                    self.detail_grid_layout.addWidget(val2, row, 3, alignment=Qt.AlignTop | Qt.AlignLeft)

                row += 1

        bottom_spacer = QFrame()
        bottom_spacer.setFixedHeight(30)
        bottom_spacer.setStyleSheet("background: transparent;")
        self.detail_grid_layout.addWidget(bottom_spacer, row, 0, 1, 4)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # High-DPI Support
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())