import os
import re
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Bildverarbeitung importieren (Pillow)
try:
    from PIL import Image, ImageTk
except ImportError:
    messagebox.showerror("Fehlendes Modul",
                         "Das Modul 'Pillow' fehlt.\nBitte öffne dein Terminal und installiere es mit:\n\npip install pillow")
    raise

# ==============================================================================
# KONFIGURATION
# ==============================================================================
DEFAULT_FILE_PATH = "EDGE-Werkzeugliste-2026.gdml"
IMAGE_DIR = "images"


def format_number(val):
    if val is None or val == '':
        return ''
    try:
        val_str = str(val).replace(',', '.')
        num = float(val_str)
        return f"{num:.3f}"
    except (ValueError, TypeError):
        return str(val)


# --- Hilfsfunktionen für die tolerante Suche ---
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
        if not line:
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\s*;\s*(\d+)\s*;\s*([^;]*)\s*;", line)
        if m:
            result[m.group(1)] = m.group(3).strip()
        if line.startswith('BEGIN_STRING;'):
            parts = line.split(';')
            if len(parts) >= 2:
                string_keys.append(parts[1].strip())

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
        raise ValueError(f"Fehler beim Parsen der XML-Struktur: {e}")

    annotations = [el for el in root.iter() if el.tag.split('}')[-1] == 'Annotation']
    comps = [el for el in root.iter() if el.tag.split('}')[-1] == 'InterchangeableComponent']

    tool_data_map = {}
    assembly_map = {}

    for ann in annotations:
        name_attr = ann.attrib.get('name')
        if not name_attr:
            continue
        text = ann.text or ''

        m = re.match(r"^Tool_(\d+)_Technology$", name_attr)
        if m:
            num = m.group(1)
            tool_data_map.setdefault(num, {})['techText'] = text
            continue

        m = re.match(r"^Tool_(\d+)_Name$", name_attr)
        if m:
            num = m.group(1)
            tool_data_map.setdefault(num, {})['name'] = text
            continue

        m = re.match(r"^#cutter(\d+)$", name_attr)
        if m:
            num = m.group(1)
            tool_data_map.setdefault(num, {})['cutterXml'] = text
            continue

        m = re.match(r"^ToolAssembly_(\d+)_Name$", name_attr)
        if m:
            assembly_map.setdefault(m.group(1), {})['name'] = text
            continue

        m = re.match(r"^ToolAssembly_(\d+)_KbmDatabaseId$", name_attr)
        if m:
            assembly_map.setdefault(m.group(1), {})['kbmId'] = text
            continue

        m = re.match(r"^ToolAssembly_(\d+)_Reference$", name_attr)
        if m:
            assembly_map.setdefault(m.group(1), {})['reference'] = text
            continue

        m = re.match(r"^ToolAssembly_(\d+)_RootId$", name_attr)
        if m:
            assembly_map.setdefault(m.group(1), {})['rootId'] = text
            continue

        m = re.match(r"^ToolAssembly_(\d+)_RootType$", name_attr)
        if m:
            assembly_map.setdefault(m.group(1), {})['rootType'] = text
            continue

        m = re.match(r"^ToolAssembly_(\d+)_StationID$", name_attr)
        if m:
            assembly_map.setdefault(m.group(1), {})['stationId'] = text
            continue

    cutter_to_holder = {}
    for comp in comps:
        file_attr = comp.attrib.get('componentFile', '')
        if file_attr.startswith('#cutter'):
            cutter_num = file_attr.replace('#cutter', '')
            target = comp.attrib.get('targetNodeName', '')
            if target:
                parts = target.split(':')
                if len(parts) >= 3:
                    holder_node = parts[2]
                    if holder_node.isdigit():
                        cutter_to_holder[cutter_num] = holder_node

    tools = []
    for num, data in tool_data_map.items():
        if not data.get('techText') and not data.get('name'):
            continue

        tech_data = parse_technology_block(data.get('techText', ''))
        tool_name = data.get('name') or tech_data.get('ToolID') or tech_data.get('Tool_2_Name') or f"Werkzeug {num}"

        holder_node = cutter_to_holder.get(num)
        assembly_name = '—'
        assembly_root_id = '—'
        assembly_station_id = '—'
        assembly_type = '—'

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
        if spindle == '-1':
            spindle_str = 'Linkslauf (M4)'
        elif spindle == '1':
            spindle_str = 'Rechtslauf (M3)'
        else:
            spindle_str = spindle or '—'

        coolant_val = tech_data.get('NewCoolant') or tech_data.get('Coolant')
        if coolant_val == '1':
            coolant_str = 'vorhanden'
        elif coolant_val == '0':
            coolant_str = 'nicht vorhanden'
        else:
            coolant_str = coolant_val or '—'

        status_machine = '—'
        if assembly_name:
            ass_upper = assembly_name.upper()
            if 'FIX' in ass_upper:
                status_machine = 'FIX'
            elif 'RÜST' in ass_upper:
                status_machine = 'RÜST'

        # --- Ausspannlänge berechnen (Gesamtlänge - Versatz Z) ---
        raw_length = tech_data.get('OverallLength')
        raw_shift_z = tech_data.get('ToolShiftZ')
        if raw_length or raw_shift_z:
            try:
                val_len = float(str(raw_length).replace(',', '.')) if raw_length else 0.0
                val_z = float(str(raw_shift_z).replace(',', '.')) if raw_shift_z else 0.0
                ausspann_str = f"{(val_len - val_z):.3f}"
            except ValueError:
                ausspann_str = '—'
        else:
            ausspann_str = '—'

        tool = {
            'Werkzeugname': tool_name,
            'Werkzeugnummer': format_number(tech_data.get('ToolNumber')),
            'Werkzeug-ID': tech_data.get('ToolID', '—'),
            'Durchmesser (mm)': format_number(tech_data.get('ToolDiameter')),
            'Schneidenlänge (mm)': format_number(tech_data.get('CuttingLength')),
            'Gesamtlänge (mm)': format_number(tech_data.get('OverallLength')),
            'Ausspannlänge (mm)': ausspann_str,  # <--- HIER HINZUGEFÜGT
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
            if v is None or v == '':
                tool[k] = '—'

        tools.append(tool)

    return tools


class ToolApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ToolService EDGE Werkzeugliste")
        self.geometry("1400x800")
        self.minsize(1000, 600)

        self.COLOR_BG = "#f4f7fc"
        self.COLOR_HEADER = "#0b2b4a"
        self.COLOR_ACCENT = "#2563eb"
        self.COLOR_TEXT = "#0f172a"
        self.COLOR_MUTED = "#64748b"
        self.COLOR_PANEL = "#ffffff"

        self.configure(bg=self.COLOR_BG)

        self.all_tools = []
        self.filtered_tools = []
        self.current_tool = None

        # Bild-Referenzen, damit der Garbage Collector sie nicht löscht
        self.original_image = None
        self.current_photo = None
        self.current_tool_name = None

        self.build_ui()
        self.load_file_from_path(DEFAULT_FILE_PATH, initial=True)

    def build_ui(self):
        # Header
        header_frame = tk.Frame(self, bg=self.COLOR_BG, padx=16, pady=8)
        header_frame.pack(fill=tk.X)

        title_lbl = tk.Label(header_frame, text="🔧 ToolService EDGE Werkzeugliste",
                             font=("Segoe UI", 16, "bold"), fg=self.COLOR_HEADER, bg=self.COLOR_BG)
        title_lbl.pack(side=tk.LEFT)

        author_lbl = tk.Label(header_frame, text="by Gschwendtner Johannes",
                              font=("Segoe UI", 9), fg=self.COLOR_MUTED, bg=self.COLOR_BG)
        author_lbl.pack(side=tk.RIGHT, pady=(6, 0))

        # Hauptcontainer
        main_container = tk.Frame(self, bg=self.COLOR_PANEL, bd=1, relief=tk.SOLID)
        main_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

        paned = ttk.PanedWindow(main_container, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ----------------- SIDEBAR -----------------
        sidebar = tk.Frame(paned, bg=self.COLOR_PANEL, width=340)
        sidebar.pack_propagate(False)
        paned.add(sidebar, weight=0)

        sb_header = tk.Frame(sidebar, bg=self.COLOR_PANEL, padx=12, pady=12)
        sb_header.pack(fill=tk.X)

        sb_title = tk.Label(sb_header, text="📂 Werkzeuge", font=("Segoe UI", 11, "bold"),
                            fg=self.COLOR_HEADER, bg=self.COLOR_PANEL)
        sb_title.pack(anchor=tk.W)

        btn_frame = tk.Frame(sb_header, bg=self.COLOR_PANEL, pady=6)
        btn_frame.pack(fill=tk.X)

        open_btn = tk.Button(btn_frame, text="📁 GDML wählen", bg=self.COLOR_ACCENT, fg="white",
                             font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=8, pady=3,
                             cursor="hand2", command=self.open_file_dialog)
        open_btn.pack(side=tk.LEFT)

        reload_btn = tk.Button(btn_frame, text="🔄 Neu laden", bg="#e2e8f0", fg=self.COLOR_TEXT,
                               font=("Segoe UI", 8), relief=tk.FLAT, padx=6, pady=3,
                               cursor="hand2", command=lambda: self.load_file_from_path(DEFAULT_FILE_PATH))
        reload_btn.pack(side=tk.LEFT, padx=6)

        self.status_lbl = tk.Label(sb_header, text="Keine Datei geladen", font=("Segoe UI", 8),
                                   fg=self.COLOR_MUTED, bg=self.COLOR_PANEL, anchor=tk.W)
        self.status_lbl.pack(fill=tk.X, pady=(2, 6))

        # Sucheingabe
        search_frame = tk.Frame(sb_header, bg=self.COLOR_PANEL)
        search_frame.pack(fill=tk.X)

        tk.Label(search_frame, text="🔍", bg=self.COLOR_PANEL, font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.filter_tools())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # Werkzeug-Tabelle
        tree_frame = tk.Frame(sidebar, bg=self.COLOR_PANEL, padx=12)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        columns = ("Name", "Diameter")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("Name", text="NAME")
        self.tree.heading("Diameter", text="⌀")
        self.tree.column("Name", width=210, anchor=tk.W)
        self.tree.column("Diameter", width=70, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_tool_selected)

        # ----------------- DETAIL VIEW -----------------
        detail_panel = tk.Frame(paned, bg=self.COLOR_PANEL)
        paned.add(detail_panel, weight=1)

        # Empty State
        self.empty_state_frame = tk.Frame(detail_panel, bg=self.COLOR_PANEL)
        self.empty_state_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(self.empty_state_frame, text="🔧", font=("Segoe UI", 48), bg=self.COLOR_PANEL, fg="#cbd5e1").pack(
            expand=True, pady=(150, 0))
        tk.Label(self.empty_state_frame, text="Wähle ein Werkzeug aus der Liste", font=("Segoe UI", 12),
                 bg=self.COLOR_PANEL, fg=self.COLOR_MUTED).pack(expand=True, pady=(0, 150))

        # Detail Content Container
        self.content_frame = tk.Frame(detail_panel, bg=self.COLOR_PANEL, padx=20, pady=16)

        # Detail-Header
        self.detail_header_frame = tk.Frame(self.content_frame, bg=self.COLOR_PANEL)
        self.detail_header_frame.pack(fill=tk.X, pady=(0, 10))

        self.detail_title_lbl = tk.Label(self.detail_header_frame, text="Werkzeug", font=("Segoe UI", 16, "bold"),
                                         fg=self.COLOR_HEADER, bg=self.COLOR_PANEL, anchor=tk.W)
        self.detail_title_lbl.pack(fill=tk.X)

        self.detail_subtitle_lbl = tk.Label(self.detail_header_frame, text="", font=("Segoe UI", 10),
                                            fg=self.COLOR_MUTED, bg=self.COLOR_PANEL, anchor=tk.W)
        self.detail_subtitle_lbl.pack(fill=tk.X, pady=(2, 8))

        sep = tk.Frame(self.detail_header_frame, height=2, bg="#edf2f7")
        sep.pack(fill=tk.X, pady=(0, 10))

        # --- PANED WINDOW FÜR TEXT & BILD ---
        self.detail_split = ttk.PanedWindow(self.content_frame, orient=tk.HORIZONTAL)
        self.detail_split.pack(fill=tk.BOTH, expand=True)

        # LINKER BEREICH: TEXT-GRID
        self.text_container = tk.Frame(self.detail_split, bg=self.COLOR_PANEL)
        self.detail_split.add(self.text_container, weight=3)

        self.canvas_text = tk.Canvas(self.text_container, bg=self.COLOR_PANEL, highlightthickness=0)
        self.detail_scroll = ttk.Scrollbar(self.text_container, orient=tk.VERTICAL, command=self.canvas_text.yview)
        self.grid_frame = tk.Frame(self.canvas_text, bg=self.COLOR_PANEL)

        self.grid_frame.bind("<Configure>",
                             lambda e: self.canvas_text.configure(scrollregion=self.canvas_text.bbox("all")))
        self.canvas_text_window = self.canvas_text.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.canvas_text.configure(yscrollcommand=self.detail_scroll.set)

        self.canvas_text.bind('<Configure>', self._on_canvas_configure)
        self.canvas_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # RECHTER BEREICH: BILD
        self.image_container = tk.Frame(self.detail_split, bg=self.COLOR_PANEL)
        self.detail_split.add(self.image_container, weight=2)

        tk.Label(self.image_container, text="Werkzeug-Abbildung", font=("Segoe UI", 10, "bold"),
                 fg=self.COLOR_MUTED, bg=self.COLOR_PANEL, anchor="w").pack(fill=tk.X, padx=10, pady=(0, 5))

        self.canvas_image = tk.Canvas(self.image_container, bg="#ffffff", bd=1, relief=tk.SOLID, highlightthickness=0)
        self.canvas_image.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Bei Größenänderung des Fensters das Bild skalieren
        self.canvas_image.bind("<Configure>", self._resize_and_show_image)

        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_canvas_configure(self, event):
        self.canvas_text.itemconfig(self.canvas_text_window, width=event.width)

    def _on_mousewheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        if not widget:
            return

        delta = int(-1 * (event.delta / 120)) if event.delta else 0
        if delta == 0:
            return

        w = widget
        while w is not None:
            if w == self.canvas_text or w == self.grid_frame:
                if self.content_frame.winfo_ismapped():
                    self.canvas_text.yview_scroll(delta, "units")
                return
            # Das rechte Bild-Canvas darf das Scroll-Event nicht stören
            if w == self.canvas_image:
                return
            w = getattr(w, "master", None)

    def load_file_from_path(self, path, initial=False):
        if not os.path.exists(path):
            if initial:
                self.status_lbl.config(text=f"Datei nicht gefunden: {os.path.basename(path)}")
            else:
                messagebox.showerror("Datei nicht gefunden", f"Konnte die Datei nicht finden:\n{path}")
            return

        try:
            with open(path, "r", encoding="iso-8859-1") as f:
                content = f.read()

            filename = os.path.basename(path)
            tools = parse_gdml(content, filename)

            if not tools:
                messagebox.showwarning("Keine Daten", f"Keine Werkzeuge in {filename} gefunden.")
                return

            self.all_tools = tools
            self.status_lbl.config(text=f"{len(tools)} Werkzeuge geladen ({filename})")
            self.search_var.set("")
            self.filter_tools()

            if self.tree.get_children():
                first_item = self.tree.get_children()[0]
                self.tree.selection_set(first_item)
                self.tree.focus(first_item)

        except Exception as e:
            messagebox.showerror("Fehler beim Laden", f"Fehler beim Lesen der GDML-Datei:\n{e}")

    def open_file_dialog(self):
        filename = filedialog.askopenfilename(
            title="GDML-Datei auswählen",
            filetypes=[("GDML / XML Dateien", "*.gdml *.xml"), ("Alle Dateien", "*.*")]
        )
        if filename:
            self.load_file_from_path(filename)

    def filter_tools(self):
        query = self.search_var.get().strip()
        if not query:
            self.filtered_tools = self.all_tools[:]
        else:
            tokens = query.split()
            filtered = []

            for tool in self.all_tools:
                searchable_values = [
                    tool.get('Werkzeugname', ''),
                    tool.get('Durchmesser (mm)', ''),
                    tool.get('Werkzeug-ID', ''),
                    tool.get('Werkzeugnummer', ''),
                    tool.get('Werkzeugtyp', ''),
                    tool.get('Kommentar', ''),
                    tool.get('Aufnahme', '')
                ]

                raw_combined = normalize_str(" ".join(searchable_values))
                clean_combined = clean_str(" ".join(searchable_values))

                matches_all_tokens = True
                for token in tokens:
                    token_norm = normalize_str(token)
                    token_clean = clean_str(token)

                    in_raw = token_norm in raw_combined
                    in_clean = (len(token_clean) > 0 and token_clean in clean_combined)

                    if not (in_raw or in_clean):
                        matches_all_tokens = False
                        break

                if matches_all_tokens:
                    filtered.append(tool)

            self.filtered_tools = filtered

        self.tree.delete(*self.tree.get_children())
        for idx, tool in enumerate(self.filtered_tools):
            name = tool.get('Werkzeugname', '—')
            diam = tool.get('Durchmesser (mm)', '—')
            self.tree.insert("", tk.END, iid=str(idx), values=(name, diam))

        if not self.filtered_tools:
            self.show_empty_state()
        else:
            first_item = self.tree.get_children()[0]
            self.tree.selection_set(first_item)
            self.tree.focus(first_item)

    def on_tool_selected(self, event):
        selected_items = self.tree.selection()
        if not selected_items:
            return
        idx = int(selected_items[0])
        if 0 <= idx < len(self.filtered_tools):
            self.current_tool = self.filtered_tools[idx]
            self.render_tool_detail(self.current_tool)

    def show_empty_state(self):
        self.content_frame.pack_forget()
        self.empty_state_frame.pack(fill=tk.BOTH, expand=True)

    # ----------------- BILD-LOGIK -----------------
    def load_and_display_image(self, tool_name):
        self.original_image = None
        self.current_photo = None
        self.current_tool_name = tool_name
        self.canvas_image.delete("all")

        if not tool_name or tool_name == '—':
            self._draw_placeholder("Kein Werkzeugname\ndefiniert.")
            return

        # Mögliche Dateiendungen durchprobieren
        extensions = [".png", ".jpg", ".jpeg", ".bmp", ".PNG", ".JPG", ".JPEG", ".BMP"]
        img_path = None

        # Zuerst exakter Name, dann zur Sicherheit einen "gesäuberten" probieren
        safe_name = tool_name.replace("/", "_").replace("\\", "_")

        for ext in extensions:
            path = os.path.join(IMAGE_DIR, f"{tool_name}{ext}")
            if os.path.exists(path):
                img_path = path
                break

            path_safe = os.path.join(IMAGE_DIR, f"{safe_name}{ext}")
            if os.path.exists(path_safe):
                img_path = path_safe
                break

        if not img_path:
            self._draw_placeholder(f"Kein Bild gefunden im Ordner\nBilder-WZ für:\n\n'{tool_name}'")
            return

        try:
            self.original_image = Image.open(img_path)
            self._resize_and_show_image()
        except Exception as e:
            self._draw_placeholder(f"Fehler beim Laden:\n{e}")

    def _draw_placeholder(self, text):
        self.canvas_image.delete("all")
        w = self.canvas_image.winfo_width()
        h = self.canvas_image.winfo_height()
        if w < 10 or h < 10:
            w, h = 300, 300

        self.canvas_image.create_text(w / 2, h / 2, text=text, justify=tk.CENTER,
                                      fill=self.COLOR_MUTED, font=("Segoe UI", 10))

    def _resize_and_show_image(self, event=None):
        if not self.original_image:
            if self.current_tool_name:
                self.load_and_display_image(self.current_tool_name)
            return

        w = self.canvas_image.winfo_width()
        h = self.canvas_image.winfo_height()

        if w < 10 or h < 10:
            return

        img_w, img_h = self.original_image.size

        ratio = min((w * 0.95) / img_w, (h * 0.95) / img_h)
        new_w = int(img_w * ratio)
        new_h = int(img_h * ratio)

        if new_w <= 0 or new_h <= 0:
            return

        resized_img = self.original_image.resize((new_w, new_h), Image.LANCZOS)

        self.current_photo = ImageTk.PhotoImage(resized_img)
        self.canvas_image.delete("all")
        self.canvas_image.create_image(w / 2, h / 2, image=self.current_photo, anchor=tk.CENTER)

    # ----------------- TOOL DETAIL ANSICHT -----------------
    def render_tool_detail(self, tool):
        self.empty_state_frame.pack_forget()
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        tool_name = tool.get('Werkzeugname', 'Unbenanntes Werkzeug')
        self.detail_title_lbl.config(text=tool_name)
        d = tool.get('Durchmesser (mm)', '—')
        typ = tool.get('Werkzeugtyp', '—')
        self.detail_subtitle_lbl.config(text=f"⌀ {d} mm · {typ}")

        # --- BILD LADEN ---
        self.load_and_display_image(tool_name)

        # --- TEXTTABELLE ---
        for widget in self.grid_frame.winfo_children():
            widget.destroy()

        # HIER WURDE 'Ausspannlänge (mm)' HINZUGEFÜGT
        categories = {
            'Basisdaten': ['Werkzeugnummer', 'Werkzeug-ID', 'Werkzeugname', 'Werkzeugtyp', 'Einheit', 'Kommentar'],
            'Geometrie': ['Durchmesser (mm)', 'Schneidenlänge (mm)', 'Gesamtlänge (mm)', 'Ausspannlänge (mm)',
                          'Schaftdurchmesser (mm)', 'Oberer Schaftdurchmesser (mm)', 'Untere Länge (mm)',
                          'Schaftwinkel (°)', 'Halterdurchmesser (mm)', 'Anzahl Schneiden'],
            'Aufnahme & Halter': ['Aufnahme', 'Aufnahmegröße', 'Baugruppe', 'Baugruppentyp', 'Root-ID', 'Station-ID'],
            'Maschinenparameter': ['Längenkorrekturregister', 'Spindeldrehrichtung', 'Werkzeugausrichtung',
                                   'Schutzebene (mm)'],
            'Versatz & Offset': ['Versatz X (mm)', 'Versatz Y (mm)', 'Versatz Z (mm)', 'Offset X (mm)',
                                 'Offset Y (mm)', 'Offset Z (mm)'],
            'Rotation & Vektor': ['Rotation X (°)', 'Rotation Y (°)', 'Rotation Z (°)', 'Vektor X', 'Vektor Y',
                                  'Vektor Z'],
            'Kühlung & Material': ['Kühlung', 'Kühlungsdruck', 'Kühlungsdruck-Wert', 'Beschichtung'],
            'Status & Sonstiges': ['Status Maschine', 'Simulationsfarbe', 'Standard-Kontrollpunkt', 'Dateiname']
        }

        self.grid_frame.columnconfigure(0, weight=0, minsize=140)
        self.grid_frame.columnconfigure(1, weight=1)
        self.grid_frame.columnconfigure(2, weight=0, minsize=140)
        self.grid_frame.columnconfigure(3, weight=1)

        row = 0
        for cat_name, fields in categories.items():
            valid_fields = [f for f in fields if f in tool]
            if not valid_fields:
                continue

            title_lbl = tk.Label(self.grid_frame, text=cat_name, font=("Segoe UI", 10, "bold"),
                                 fg="#1e293b", bg=self.COLOR_PANEL, anchor="w", pady=4)
            title_lbl.grid(row=row, column=0, columnspan=4, sticky="we", pady=(12, 4))
            row += 1

            title_sep = tk.Frame(self.grid_frame, height=1, bg="#e2e8f0")
            title_sep.grid(row=row, column=0, columnspan=4, sticky="we", pady=(0, 6))
            row += 1

            for i in range(0, len(valid_fields), 2):
                f1 = valid_fields[i]
                v1 = tool.get(f1, '—')

                lbl1 = tk.Label(self.grid_frame, text=f1.upper(), font=("Segoe UI", 8, "bold"),
                                fg=self.COLOR_MUTED, bg=self.COLOR_PANEL, anchor="w")
                lbl1.grid(row=row, column=0, sticky="nw", padx=(4, 8), pady=2)

                val1_fg = self.COLOR_TEXT if v1 != '—' else "#94a3b8"
                val1 = tk.Label(self.grid_frame, text=v1, font=("Segoe UI", 9, "bold" if v1 != '—' else "normal"),
                                fg=val1_fg, bg=self.COLOR_PANEL, anchor="w", wraplength=220, justify=tk.LEFT)
                val1.grid(row=row, column=1, sticky="w", padx=(0, 16), pady=2)

                if i + 1 < len(valid_fields):
                    f2 = valid_fields[i + 1]
                    v2 = tool.get(f2, '—')

                    lbl2 = tk.Label(self.grid_frame, text=f2.upper(), font=("Segoe UI", 8, "bold"),
                                    fg=self.COLOR_MUTED, bg=self.COLOR_PANEL, anchor="w")
                    lbl2.grid(row=row, column=2, sticky="nw", padx=(4, 8), pady=2)

                    val2_fg = self.COLOR_TEXT if v2 != '—' else "#94a3b8"
                    val2 = tk.Label(self.grid_frame, text=v2, font=("Segoe UI", 9, "bold" if v2 != '—' else "normal"),
                                    fg=val2_fg, bg=self.COLOR_PANEL, anchor="w", wraplength=220, justify=tk.LEFT)
                    val2.grid(row=row, column=3, sticky="w", pady=2)

                row += 1

        self.canvas_text.yview_moveto(0)


if __name__ == "__main__":
    app = ToolApp()
    app.mainloop()