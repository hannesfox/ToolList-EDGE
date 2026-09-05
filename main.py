import sys
import os
import re
import xml.etree.ElementTree as ET

# 1. WICHTIG: PyQt5 muss registriert werden, BEVOR qt_material importiert wird!
os.environ['QT_API'] = 'pyqt5'
import PyQt5
from PyQt5 import QtCore, QtGui, QtWidgets, QtSvg

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea, QStackedWidget,
    QFrame, QSizePolicy
)
from PyQt5.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent
from PyQt5.QtCore import Qt

from qt_material import apply_stylesheet


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
    for comp in comps:
        file_attr = comp.attrib.get('componentFile', '')
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
        for comp in comps:
            if comp.attrib.get('newNodeName') == holder_node:
                cf = comp.attrib.get('componentFile', '')
                if cf and not cf.startswith('#'):
                    holder_path = cf
                break

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
#      LABEL MIT AUTOMATISCHER KÜRZUNG (statt fragilem Word-Wrap)
# ==============================================================================
class ElidedLabel(QLabel):
    """
    QLabel, das lange Texte statt umzubrechen sauber mit '…' kürzt und den
    vollständigen Text als Tooltip anzeigt. Dadurch bleibt die Zeilenhöhe im
    QGridLayout immer konstant (ein bekanntes Qt-Problem: setWordWrap(True)
    in Kombination mit variabler Spaltenbreite berechnet die Zeilenhöhe nicht
    zuverlässig neu -> Textzeilen können sich überlappen).
    """
    def __init__(self, full_text="", parent=None):
        super().__init__(parent)
        self._full_text = str(full_text)
        self.setWordWrap(False)
        self._apply_elided_text()

    def setFullText(self, text):
        self._full_text = str(text)
        self._apply_elided_text()

    def _apply_elided_text(self):
        fm = self.fontMetrics()
        available_width = max(self.width(), 40)
        elided = fm.elidedText(self._full_text, Qt.ElideRight, available_width)
        super().setText(elided)
        self.setToolTip(self._full_text if elided != self._full_text else "")

    def resizeEvent(self, event):
        self._apply_elided_text()
        super().resizeEvent(event)


# ==============================================================================
#      BILD-WIDGET
# ==============================================================================
class ResizableImageLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(250, 250)
        self._pixmap = None

    def set_image(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self.update_image()

    def set_placeholder(self, text: str):
        self._pixmap = None
        self.setText(text)

    def resizeEvent(self, event):
        self.update_image()
        super().resizeEvent(event)

    def update_image(self):
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.setPixmap(scaled)


# ==============================================================================
#      HAUPTFENSTER
# ==============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ToolService EDGE Werkzeugliste")
        self.setMinimumSize(1200, 750)

        app_icon_path = resource_path("assets/logo.png")
        if os.path.exists(app_icon_path):
            self.setWindowIcon(QIcon(app_icon_path))

        self._set_application_style()
        self.setAcceptDrops(True)

        self.all_tools = []
        self.filtered_tools = []

        self._build_ui()
        self.load_gdml_file(DEFAULT_FILE_PATH, initial=True)

    def _set_application_style(self):
        app = QApplication.instance()

        fallback_font = "Helvetica" if sys.platform == "darwin" else "Arial"
        extra = {
            'accent_color': '#448AFF',
            'secondaryLightColor': '#31363B',
            'font_family': fallback_font
        }
        apply_stylesheet(app, theme='dark_blue.xml', extra=extra)

        stylesheet = app.styleSheet()
        stylesheet = re.sub(r'image:\s*url\(.*?\.svg\);', 'image: none;', stylesheet)

        custom_css = stylesheet + """
        QSplitter::handle { background-color: #31363B; image: none; }
        QSplitter::handle:horizontal { width: 3px; }
        QSplitter::handle:vertical { height: 3px; }

        QTableWidget {
            border: 1px solid #31363B;
            border-radius: 6px;
            background-color: #1e1e1e;
            alternate-background-color: #262a30;
            gridline-color: transparent;
            outline: 0;
        }
        QTableWidget::item { padding: 8px 6px; border: none; }
        QTableWidget::item:selected { background-color: #448AFF; color: white; border: none; }
        QHeaderView::section {
            background-color: #31363B;
            color: #94a3b8;
            padding: 6px;
            border: none;
            font-weight: bold;
        }

        QPushButton {
            padding: 8px 14px;
            border-radius: 6px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: rgba(68, 138, 255, 0.15);
        }
        QPushButton:pressed {
            background-color: rgba(68, 138, 255, 0.30);
        }

        QLineEdit {
            padding: 6px 8px;
            border: 1px solid #31363B;
            border-radius: 6px;
            background-color: #1e1e1e;
        }
        QLineEdit:focus {
            border: 1px solid #448AFF;
        }

        #leftCard {
            background-color: #262a30;
            border: 1px solid #31363B;
            border-radius: 8px;
        }
        """
        app.setStyleSheet(custom_css)

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 5, 15, 10)
        main_layout.setSpacing(5)

        # ---------------- HEADER ----------------
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        title_label = QLabel("🔧 ToolService EDGE Werkzeugliste")
        title_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #448AFF;")
        author_label = QLabel("by Gschwendtner Johannes")
        author_label.setStyleSheet("color: #64748b; font-size: 9pt;")
        author_label.setAlignment(Qt.AlignBottom)

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(author_label)
        main_layout.addLayout(header_layout, 0)

        # Trennlinie unter dem Header für klare visuelle Struktur
        header_line = QFrame()
        header_line.setFrameShape(QFrame.HLine)
        header_line.setStyleSheet("color: #31363B; background-color: #31363B; max-height: 1px;")
        main_layout.addWidget(header_line, 0)
        main_layout.addSpacing(6)

        # ---------------- HAUPT-SPLITTER ----------------
        # WICHTIG: stretch=1, sonst teilt Qt den Platz 50/50 zwischen Header
        # und Splitter auf (QSplitter hat KEINE "Expanding"-Size-Policy!),
        # wodurch oben ein riesiger leerer Abstand entsteht.
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter, 1)

        # --- LINKE SEITE (Werkzeugliste) ---
        # Als "Card" gestaltet: eigener Hintergrund + Rahmen, damit sie sich
        # klar vom Detailbereich rechts abhebt.
        left_outer = QWidget()
        left_outer_layout = QVBoxLayout(left_outer)
        left_outer_layout.setContentsMargins(0, 0, 15, 0)

        left_widget = QFrame()
        left_widget.setObjectName("leftCard")
        left_outer_layout.addWidget(left_widget)

        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_open = QPushButton("📁 GDML wählen")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(self._open_file_dialog)

        btn_reload = QPushButton("🔄 Neu laden")
        btn_reload.setCursor(Qt.PointingHandCursor)
        btn_reload.clicked.connect(lambda: self.load_gdml_file(DEFAULT_FILE_PATH))

        btn_layout.addWidget(btn_open)
        btn_layout.addWidget(btn_reload)
        left_layout.addLayout(btn_layout)

        self.status_label = QLabel("Keine Datei geladen")
        self.status_label.setStyleSheet("color: #64748b; font-size: 10pt;")
        left_layout.addWidget(self.status_label)

        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)
        search_icon = QLabel("🔍")
        search_icon.setAlignment(Qt.AlignCenter)
        search_layout.addWidget(search_icon)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Suchen...")
        self.search_edit.textChanged.connect(self._filter_tools)
        search_layout.addWidget(self.search_edit)
        left_layout.addLayout(search_layout)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["NAME", "⌀"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.verticalHeader().setDefaultSectionSize(32)
        left_layout.addWidget(self.table)

        # Linke Seite: flexible Breite mit sinnvollem Minimum
        left_outer.setMinimumWidth(320)
        self.splitter.addWidget(left_outer)

        # --- RECHTE SEITE (Details) ---
        self.stacked_widget = QStackedWidget()
        self.splitter.addWidget(self.stacked_widget)

        # Splitter: Rechte Seite bekommt mehr Platz beim Resizen
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        # 1) Leerer Zustand
        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_icon = QLabel("🔧")
        empty_icon.setStyleSheet("font-size: 64pt; color: #31363B;")
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_text = QLabel("Wähle ein Werkzeug aus der Liste\noder ziehe eine GDML-Datei hierher.")
        empty_text.setAlignment(Qt.AlignCenter)
        empty_text.setStyleSheet("color: #64748b; font-size: 12pt;")
        empty_layout.addStretch()
        empty_layout.addWidget(empty_icon)
        empty_layout.addWidget(empty_text)
        empty_layout.addStretch()
        self.stacked_widget.addWidget(empty_widget)

        # 2) Detailansicht
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(10, 0, 0, 0)

        # Detail Header
        self.detail_title = QLabel("Werkzeug")
        self.detail_title.setStyleSheet("font-size: 20pt; font-weight: bold; color: white;")
        self.detail_subtitle = QLabel("⌀ -- mm · --")
        self.detail_subtitle.setStyleSheet("font-size: 11pt; color: #448AFF; font-weight: bold;")
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_subtitle)
        detail_layout.addSpacing(5)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #31363B;")
        detail_layout.addWidget(line)
        detail_layout.addSpacing(10)

        # Content Splitter (Links: Text-Raster, Rechts: Bild)
        # WICHTIG: stretch=1 aus demselben Grund wie beim Haupt-Splitter oben
        # (sonst konkurriert er mit Titel/Untertitel/Linie um den Platz).
        self.content_splitter = QSplitter(Qt.Horizontal)
        detail_layout.addWidget(self.content_splitter, 1)

        # Text-Raster (Scroll Area)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setMinimumWidth(400)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setAlignment(Qt.AlignTop)
        self.grid_layout.setHorizontalSpacing(15)
        self.grid_layout.setVerticalSpacing(8)

        # Spalten-Verhältnis im Grid definieren
        self.grid_layout.setColumnStretch(0, 0)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setColumnStretch(2, 0)
        self.grid_layout.setColumnStretch(3, 1)

        scroll_area.setWidget(self.grid_container)
        self.content_splitter.addWidget(scroll_area)

        # Bild Area
        img_container = QWidget()
        img_layout = QVBoxLayout(img_container)
        img_layout.setContentsMargins(15, 0, 0, 0)

        img_title = QLabel("Werkzeug-Abbildung")
        img_title.setStyleSheet("font-weight: bold; color: #64748b; font-size: 11pt;")

        self.image_label = ResizableImageLabel()
        self.image_label.setStyleSheet("border: 2px dashed #31363B; border-radius: 8px; background-color: #1e1e1e;")
        self.image_label.setMinimumWidth(300)

        img_layout.addWidget(img_title)
        img_layout.addWidget(self.image_label, 1)
        self.content_splitter.addWidget(img_container)

        # Content Splitter: Text bekommt mehr Gewicht, Bild bleibt flexibel
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)

        self.stacked_widget.addWidget(detail_widget)

        # Initiale Splitter-Größen (verhältnismäßiger)
        self.splitter.setSizes([350, 850])
        self.content_splitter.setSizes([550, 350])

    # ----------------- DRAG & DROP -----------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and event.mimeData().urls()[0].isLocalFile():
            path = event.mimeData().urls()[0].toLocalFile()
            if path.lower().endswith('.gdml') or path.lower().endswith('.xml'):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        path = event.mimeData().urls()[0].toLocalFile()
        self.load_gdml_file(path)

    # ----------------- LOGIK -----------------
    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "GDML-Datei auswählen", BASE_DIR, "GDML / XML Dateien (*.gdml *.xml);;Alle Dateien (*.*)"
        )
        if path:
            self.load_gdml_file(path)

    def load_gdml_file(self, path, initial=False):
        if not os.path.exists(path):
            if initial:
                self.status_label.setText(f"Datei nicht gefunden:\n{os.path.basename(path)}")
            else:
                QMessageBox.critical(self, "Fehler", f"Konnte die Datei nicht finden:\n{path}")
            return

        try:
            # FIX: Zuerst als UTF-8 versuchen, dann Fallback auf ISO
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(path, "r", encoding="iso-8859-1") as f:
                    content = f.read()

            filename = os.path.basename(path)
            tools = parse_gdml(content, filename)

            if not tools:
                QMessageBox.warning(self, "Keine Daten", f"Keine Werkzeuge in {filename} gefunden.")
                return

            self.all_tools = tools
            self.status_label.setText(f"{len(tools)} Werkzeuge geladen")
            self.search_edit.clear()
            self._filter_tools()

        except Exception as e:
            QMessageBox.critical(self, "Ladefehler", f"Fehler beim Lesen der GDML-Datei:\n{e}")

    def _filter_tools(self):
        query = self.search_edit.text().strip()
        if not query:
            self.filtered_tools = self.all_tools[:]
        else:
            tokens = query.split()
            filtered = []
            for tool in self.all_tools:
                searchable = " ".join([
                    tool.get('Werkzeugname', ''), tool.get('Durchmesser (mm)', ''),
                    tool.get('Werkzeug-ID', ''), tool.get('Werkzeugnummer', ''),
                    tool.get('Werkzeugtyp', ''), tool.get('Kommentar', ''), tool.get('Aufnahme', '')
                ])
                raw_comb = normalize_str(searchable)
                clean_comb = clean_str(searchable)

                match_all = True
                for token in tokens:
                    tn = normalize_str(token)
                    tc = clean_str(token)
                    if not (tn in raw_comb or (len(tc) > 0 and tc in clean_comb)):
                        match_all = False
                        break
                if match_all:
                    filtered.append(tool)

            self.filtered_tools = filtered

        self.table.setRowCount(0)
        for idx, tool in enumerate(self.filtered_tools):
            self.table.insertRow(idx)
            self.table.setItem(idx, 0, QTableWidgetItem(tool.get('Werkzeugname', '—')))
            item_diam = QTableWidgetItem(tool.get('Durchmesser (mm)', '—'))
            item_diam.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(idx, 1, item_diam)

        if not self.filtered_tools:
            self.stacked_widget.setCurrentIndex(0)
        else:
            self.table.selectRow(0)

    def _on_table_selection_changed(self):
        selected = self.table.selectedItems()
        if not selected:
            self.stacked_widget.setCurrentIndex(0)
            return
        row = selected[0].row()
        if 0 <= row < len(self.filtered_tools):
            self._render_tool_detail(self.filtered_tools[row])

    def _load_image(self, tool_name):
        if not tool_name or tool_name == '—':
            self.image_label.set_placeholder("Kein Werkzeugname\ndefiniert.")
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
                self.image_label.set_image(pixmap)
            else:
                self.image_label.set_placeholder("Fehler beim Laden\ndes Bildes.")
        else:
            self.image_label.set_placeholder(
                f"Kein Bild gefunden für:\n'{tool_name}'\n\nErwarteter Ordner:\n{IMAGE_DIR}")

    def _render_tool_detail(self, tool):
        self.stacked_widget.setCurrentIndex(1)

        tool_name = tool.get('Werkzeugname', 'Unbenanntes Werkzeug')
        self.detail_title.setText(tool_name)
        d = tool.get('Durchmesser (mm)', '—')
        typ = tool.get('Werkzeugtyp', '—')
        self.detail_subtitle.setText(f"⌀ {d} mm  |  {typ}")

        self._load_image(tool_name)

        # Grid leeren
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget: widget.setParent(None)

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
                spacer.setFixedHeight(8)
                self.grid_layout.addWidget(spacer, row, 0, 1, 4)
                row += 1

            cat_label = QLabel(cat_name.upper())
            cat_label.setStyleSheet("font-weight: bold; color: #448AFF; font-size: 10pt; letter-spacing: 1px;")
            self.grid_layout.addWidget(cat_label, row, 0, 1, 4)
            row += 1

            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setStyleSheet("color: #31363B;")
            self.grid_layout.addWidget(line, row, 0, 1, 4)
            row += 1

            for i in range(0, len(valid_fields), 2):
                f1 = valid_fields[i]
                v1 = tool.get(f1, '—')

                l1 = QLabel(f1)
                l1.setStyleSheet("color: #94a3b8; font-size: 9pt;")
                val1 = ElidedLabel(v1)
                if v1 != '—':
                    val1.setStyleSheet("font-weight: bold; color: white; font-size: 10pt;")
                else:
                    val1.setStyleSheet("color: #475569; font-size: 10pt;")

                self.grid_layout.addWidget(l1, row, 0, alignment=Qt.AlignTop | Qt.AlignLeft)
                self.grid_layout.addWidget(val1, row, 1, alignment=Qt.AlignTop | Qt.AlignLeft)

                if i + 1 < len(valid_fields):
                    f2 = valid_fields[i + 1]
                    v2 = tool.get(f2, '—')

                    l2 = QLabel(f2)
                    l2.setStyleSheet("color: #94a3b8; font-size: 9pt;")
                    val2 = ElidedLabel(v2)
                    if v2 != '—':
                        val2.setStyleSheet("font-weight: bold; color: white; font-size: 10pt;")
                    else:
                        val2.setStyleSheet("color: #475569; font-size: 10pt;")

                    self.grid_layout.addWidget(l2, row, 2, alignment=Qt.AlignTop | Qt.AlignLeft)
                    self.grid_layout.addWidget(val2, row, 3, alignment=Qt.AlignTop | Qt.AlignLeft)

                row += 1


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())