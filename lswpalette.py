import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import configparser
import os
import sys
from contextlib import contextmanager

from colourutils import hex_to_rgb_tuple, hsv_to_hex, is_light

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# ---------------- Constants ----------------
MIN_COLS = 2
MAX_COLS = 360
APP_VERSION = "0.1"

# ---------------- Platform helpers ----------------
@contextmanager
def _suppress_cocoa_stderr():
    """
    On macOS, silence benign Cocoa/NSLog warnings from native file panels
    (e.g., NSSavePanel overrides identifier…). No effect on other platforms.
    """
    if sys.platform != "darwin":
        yield
        return
    devnull = open(os.devnull, "w")
    try:
        orig_fd = os.dup(2)
        os.dup2(devnull.fileno(), 2)
        try:
            yield
        finally:
            os.dup2(orig_fd, 2)
            os.close(orig_fd)
            devnull.close()
    except Exception:
        # If anything goes wrong, just yield without suppression to avoid breaking dialogs
        try:
            devnull.close()
        except Exception:
            pass
        yield

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ---------------- Reusable control: HSVVar (Entry + Scale) ----------------
class HSVVar:
    """
    Compact 'integer value' control:
    - Label + numeric Entry on the first row
    - Unit label (e.g., %) next to Entry
    - Horizontal Scale below
    Keeps Entry and Scale in sync.
    Calls an optional 'command' whenever the value changes.
    """
    def __init__(self, parent, label, from_, to, initial, unit="", width=4, command=None):
        self.frame = ttk.Frame(parent)
        self.label = ttk.Label(self.frame, text=label)
        self.var = tk.IntVar(value=initial)
        self._min = from_
        self._max = to
        self._command = command

        # Create widgets (ENTRY BEFORE SCALE to avoid early callbacks)
        self.entry = ttk.Entry(self.frame, width=width, justify="right")
        self.entry.insert(0, str(initial))
        self.unit = ttk.Label(self.frame, text=unit)
        self.scale = ttk.Scale(self.frame, from_=from_, to=to, orient="horizontal")

        # Layout
        self.label.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.entry.grid(row=0, column=1, sticky="ew")
        self.unit.grid(row=0, column=2, sticky="w", padx=(4, 0))
        self.scale.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.frame.columnconfigure(1, weight=1)

        # Set initial scale AFTER layout, then bind command
        self.scale.set(initial)
        self.scale.configure(command=self._on_scale)

        # Bindings: Enter applies; FocusOut applies; Tab triggers FocusOut automatically
        self.entry.bind("<Return>", self._on_entry)
        self.entry.bind("<KP_Enter>", self._on_entry)
        self.entry.bind("<FocusOut>", self._on_entry)

    def _on_scale(self, value):
        ivalue = int(round(float(value)))
        self.var.set(ivalue)
        if hasattr(self, "entry") and self.entry:
            self.entry.delete(0, tk.END)
            self.entry.insert(0, str(ivalue))
        if self._command:
            self._command()

    def _on_entry(self, event=None):
        text = self.entry.get().strip()
        try:
            v = int(float(text))
        except ValueError:
            v = self.var.get()
        v = max(self._min, min(self._max, v))
        self.var.set(v)
        self.entry.delete(0, tk.END)
        self.entry.insert(0, str(v))
        self.scale.set(v)
        if self._command:
            self._command()

    def get(self):
        return self.var.get()

    def set(self, value):
        value = max(self._min, min(self._max, int(round(value))))
        self.var.set(value)
        self.entry.delete(0, tk.END)
        self.entry.insert(0, str(value))
        self.scale.set(value)
        if self._command:
            self._command()

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)


# ---------------- Main App ----------------
class PaletteApp(tk.Tk):
    """
    HSV Palette Designer
    - Left: input panel
      - Header (column count + hue)
      - N adjustable rows (S/V per-row) with delete and drag-to-reorder
      - '+' button at bottom-left to add a row
    - Right: output grid (columns = hues; rows = 1 + adjustable rows)
      - Top row is fixed S/V = 100/100 for base hue sequence
      - Each cell shows color and hex label; click copies hex to clipboard
    - Import/Export:
      - PNG: renders grid with hex labels
      - INI: persists cols/hue/rows_count + ordered S/V rows + hex rows
    """
    def __init__(self):
        super().__init__()
        self.title("λ∿ Palette Designer")
        self.geometry("1200x720")
        self.minsize(950, 560)

        self.cols = 7  # default number of columns (colors)
        self.rows = []  # adjustable rows [{'frame', 's', 'v', 'del', 'handle'}, ...]
        self._last_cols = 0
        self._last_total_rows = 0
        
        self._build_menu()

        # Window layout: [left_container | output_panel]
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.left_container = ttk.Frame(self, padding=0)
        self.left_container.grid(row=0, column=0, sticky="nsew")
        self.left_container.rowconfigure(0, weight=1)
        self.left_container.columnconfigure(0, weight=1)

        self.input_panel = ttk.Frame(self.left_container, padding=8)
        self.input_panel.grid(row=0, column=0, sticky="nsew")

        # Bottom bar (add-row button)
        self.bottom_bar = ttk.Frame(self.left_container, padding=(8, 0, 8, 8))
        self.bottom_bar.grid(row=1, column=0, sticky="ew")
        self._build_bottom_bar()

        self.output_panel = ttk.Frame(self, padding=(6, 8, 8, 8))
        self.output_panel.grid(row=0, column=1, sticky="nsew")

        # Inputs & grid
        self._build_inputs_header()

        # Start with 5 adjustable rows so total rows = 1 (header) + 5 = 6
        for _ in range(5):
            self._add_row(initial_s=85 - len(self.rows) * 15, initial_v=85 - len(self.rows) * 15, build_only=True)
        self._regrid_inputs()
        self._build_grid()

        # Bind hue scale handler after grid exists
        self.h_scale.configure(command=self._on_h_scale)
        self._update_grid()

        # Drag state for row reordering
        self._drag_info = {"start_index": None, "indicator": None}
        
        # Context menu for cells
        self._ctx_menu = tk.Menu(self, tearoff=0)
        self._ctx_menu.add_command(label="Add to Palette", command=self._ctx_add_to_palette)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="Copy HEX value", command=lambda: self._copy_ctx_hex())
        self._ctx_menu.add_command(label="Copy RGB value", command=lambda: self._copy_ctx_rgb())
        self._ctx_cell = None   # tuple (r, c)
        self._ctx_hex = None    # HEX string for last-clicked main cell
        
        # Palette window state
        self.palette_win = None
        self.palette_frame = None
        self._palette_menu = None
        self.palette_hexes = []
        self.palette_hex_set = set()
        self.palette_canvases = {}
        self.palette_max_cols = 8           # Hard cap for columns
        self.palette_min_tile = 92          # Target min tile size (px) including padding
        self._palette_resize_after = None   # debounce handle for resize
        self._palette_geometry = None       # remember last palette window "WxH+X+Y"

    # ---------- Menu ----------
    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Import configuration...", command=self._import_ini)
        file_menu.add_separator()
        file_menu.add_command(label="Export PNG...", command=self._export_png)
        file_menu.add_command(label="Export configuration...", command=self._export_ini)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

    # ---------- Bottom bar ----------
    def _build_bottom_bar(self):
        """Bottom-left '+' button to add a new adjustable row."""
        add_btn = ttk.Button(self.bottom_bar, text="+", width=3, command=self._on_add_row_click)
        add_btn.pack(side="left")
        """Palette button"""
        open_pal_btn = ttk.Button(self.bottom_bar, text="Palette", command=self._open_palette_window)
        open_pal_btn.pack(side="left", padx=(8, 0))

    def _on_add_row_click(self):
        """Create a new row (defaults to average of previous row's S/V, else 70)."""
        default = 70
        if self.rows:
            last_s = self.rows[-1]["s"].get()
            last_v = self.rows[-1]["v"].get()
            default = max(0, min(100, int((last_s + last_v) / 2)))
        self._add_row(initial_s=default, initial_v=default)
        self._regrid_inputs()
        self._build_grid()
        self._update_grid()

    # ---------- Inputs header (row 0: column count + hue) ----------
    def _build_inputs_header(self):
        self.header_frame = ttk.Frame(self.input_panel, padding=(0, 2))
        self.header_frame.grid(row=0, column=0, sticky="nsew")
        self.input_panel.grid_rowconfigure(0, weight=1, uniform="inrows")
        self.input_panel.grid_columnconfigure(0, weight=1)

        top = self.header_frame
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        # Left: number of columns (# hues)
        left = ttk.Frame(top)
        left.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Label(left, text="#").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.cols_var = tk.IntVar(value=self.cols)
        self.cols_spin = ttk.Spinbox(
            left, from_=MIN_COLS, to=MAX_COLS, width=4,
            textvariable=self.cols_var, wrap=False, justify="right"
        )
        self.cols_spin.grid(row=0, column=1, sticky="w")
        # Spinbox callbacks: Apply on spin/Enter/FocusOut
        self.cols_spin.configure(command=self._on_cols_change)
        self.cols_spin.bind("<Return>", self._on_cols_entry, add=True)
        self.cols_spin.bind("<KP_Enter>", self._on_cols_entry, add=True)
        self.cols_spin.bind("<FocusOut>", self._on_cols_entry, add=True)

        # Right: base Hue controls
        right = ttk.Frame(top)
        right.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        right.columnconfigure(1, weight=1)
        ttk.Label(right, text="H (°)").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.h_var = tk.IntVar(value=25)
        self.h_entry = ttk.Entry(right, width=5, justify="right", textvariable=self.h_var)
        self.h_entry.grid(row=0, column=1, sticky="ew")
        self.h_entry.bind("<Return>", lambda e: self._clamp_h())
        self.h_entry.bind("<KP_Enter>", lambda e: self._clamp_h())
        self.h_entry.bind("<FocusOut>", lambda e: self._clamp_h())

        self.h_scale = ttk.Scale(top, from_=0, to=359, orient="horizontal")
        self.h_scale.set(25)
        self.h_scale.grid(row=1, column=0, columnspan=2, sticky="ew")

    # ---------- Row add/remove/drag ----------
    def _add_row(self, initial_s=70, initial_v=70, build_only=False):
        """
        Add an adjustable row:
        - Drag handle (≡)
        - S/V HSVVar controls
        - Delete '−' button
        """
        row_frame = ttk.Frame(self.input_panel, padding=(0, 2))
        row_frame.grid_columnconfigure(0, weight=0)  # handle
        row_frame.grid_columnconfigure(1, weight=1)  # S
        row_frame.grid_columnconfigure(2, weight=1)  # V
        row_frame.grid_columnconfigure(3, weight=0)  # delete

        # Drag handle
        try:
            handle = ttk.Label(row_frame, text="≡", cursor="sb_v_double_arrow", width=2)
        except Exception:
            handle = ttk.Label(row_frame, text="=", cursor="fleur", width=2)
        handle.grid(row=0, column=0, sticky="ns", padx=(0, 4))

        # S/V controls (call _update_grid on change)
        s = HSVVar(row_frame, label=f"Row ? S", from_=0, to=100, initial=initial_s, unit="%", command=self._update_grid)
        v = HSVVar(row_frame, label=f"Row ? V", from_=0, to=100, initial=initial_v, unit="%", command=self._update_grid)
        s.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        v.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        # Delete button
        del_btn = ttk.Button(row_frame, text="−", width=3, command=lambda rf=row_frame: self._remove_row_by_frame(rf))
        del_btn.grid(row=0, column=3, sticky="e", padx=(6, 0))

        # Drag bindings
        handle.bind("<ButtonPress-1>", lambda e, rf=row_frame: self._drag_start(e, rf))
        handle.bind("<B1-Motion>", self._drag_motion)
        handle.bind("<ButtonRelease-1>", self._drag_end)

        row_data = {"frame": row_frame, "s": s, "v": v, "del": del_btn, "handle": handle}
        self.rows.append(row_data)
        if not build_only:
            self._regrid_inputs()

    def _remove_row_by_frame(self, row_frame):
        """Remove adjustable row given its frame widget."""
        idx = None
        for i, r in enumerate(self.rows):
            if r["frame"] == row_frame:
                idx = i
                break
        if idx is None:
            return
        self._remove_row(idx)

    def _remove_row(self, idx):
        """Remove adjustable row at index."""
        r = self.rows.pop(idx)
        r["frame"].destroy()
        self._regrid_inputs()
        self._build_grid()
        self._update_grid()

    def _regrid_inputs(self):
        """
        Re-grid header and data rows; maintain vertical alignment
        with output rows. Also refresh row labels to human-friendly
        numbers: header is row 1 visually, so adjustable rows display 2..N+1.
        """
        self.header_frame.grid(row=0, column=0, sticky="nsew")
        self.input_panel.grid_rowconfigure(0, weight=1, uniform="inrows")
        for i, r in enumerate(self.rows, start=1):
            rf = r["frame"]
            rf.grid(row=i, column=0, sticky="nsew")
            self.input_panel.grid_rowconfigure(i, weight=1, uniform="inrows")
            r["s"].label.configure(text=f"Row {i+1} S")
            r["v"].label.configure(text=f"Row {i+1} V")

    # ----- Drag helpers -----
    def _row_index_from_y(self, y_root):
        """
        Convert a root Y coordinate into an insert index among adjustable rows.
        Returns an index in [0..len(rows)] where the dragged row will be inserted.
        """
        y_local = self.input_panel.winfo_pointery() - self.input_panel.winfo_rooty()
        slots = []
        for i, r in enumerate(self.rows, start=1):
            rf = r["frame"]
            y = rf.winfo_y()
            h = rf.winfo_height()
            slots.append((i, y, y + h))
        for i, y0, y1 in slots:
            if y_local < (y0 + y1) / 2:
                return i - 1  # insert before row i
        return len(self.rows)  # insert at end

    def _show_indicator(self, insert_index):
        """Show a thin blue line where the dragged row will be inserted."""
        if self._drag_info["indicator"] is not None:
            self._drag_info["indicator"].destroy()
            self._drag_info["indicator"] = None

        if insert_index <= 0:
            y = self.header_frame.winfo_height()  # just below header
        elif insert_index >= len(self.rows):
            last = self.rows[-1]["frame"]
            y = last.winfo_y() + last.winfo_height()
        else:
            prev = self.rows[insert_index - 1]["frame"]
            y = prev.winfo_y() + prev.winfo_height()

        ind = tk.Frame(self.input_panel, height=2, bg="#0078D4")
        ind.place(x=0, y=y, relwidth=1.0)
        self._drag_info["indicator"] = ind

    def _drag_start(self, event, row_frame):
        """Begin drag: record which row index is moving."""
        for i, r in enumerate(self.rows):
            if r["frame"] == row_frame:
                self._drag_info["start_index"] = i
                break

    def _drag_motion(self, event):
        """While dragging: update insert indicator position."""
        if self._drag_info["start_index"] is None:
            return
        insert_index = self._row_index_from_y(event.y_root)
        self._show_indicator(insert_index)

    def _drag_end(self, event):
        """On release: reorder rows if position changed."""
        if self._drag_info["start_index"] is None:
            return
        insert_index = self._row_index_from_y(event.y_root)
        start = self._drag_info["start_index"]
        if self._drag_info["indicator"] is not None:
            self._drag_info["indicator"].destroy()
            self._drag_info["indicator"] = None
        self._drag_info["start_index"] = None

        # No move
        if insert_index == start or insert_index == start + 1:
            return

        # Reorder list
        row = self.rows.pop(start)
        if insert_index > start:
            insert_index -= 1
        self.rows.insert(insert_index, row)

        # Re-grid + rebuild output to keep alignment
        self._regrid_inputs()
        self._build_grid()
        self._update_grid()

    # ---------- Column count + Hue handlers ----------
    def _on_cols_entry(self, event=None):
        """Apply column count on Enter/FocusOut."""
        self._on_cols_change()
        return "break"

    def _on_cols_change(self):
        """Spinbox command: clamp and rebuild grid if column count changes."""
        try:
            value = int(self.cols_var.get())
        except Exception:
            value = self.cols
        value = max(MIN_COLS, min(MAX_COLS, value))
        self.cols_var.set(value)
        if value != self.cols:
            self.cols = value
            self._build_grid()
        else:
            self._reset_output_grid_config()
        self._update_grid()

    def _on_h_scale(self, value):
        """Scale callback for Hue changes (dragging/keys)."""
        try:
            iv = int(round(float(value)))
        except Exception:
            iv = int(self.h_var.get()) if self.h_var else 0
        iv = max(0, min(359, iv))
        self.h_var.set(iv)
        self._update_grid()

    def _clamp_h(self):
        """Entry/FocusOut handler for Hue text field."""
        try:
            v = int(float(self.h_var.get()))
        except Exception:
            v = 0
        v = max(0, min(359, v))
        self.h_var.set(v)
        self.h_scale.set(v)
        self._update_grid()

    # ---------- Output grid build / layout sync ----------
    def _reset_output_grid_config(self):
        """Re-assign grid weights for the current number of rows/columns with minimal churn."""
        total_rows = 1 + len(self.rows)

        # Reset only the columns/rows we previously used
        for c in range(self._last_cols):
            self.output_panel.grid_columnconfigure(c, weight=0, uniform="", minsize=0)
        for r in range(self._last_total_rows):
            self.output_panel.grid_rowconfigure(r, weight=0, uniform="", minsize=0)

        # Apply current
        for c in range(self.cols):
            self.output_panel.grid_columnconfigure(c, weight=1, uniform="cols")
        for r in range(total_rows):
            self.output_panel.grid_rowconfigure(r, weight=1, uniform="rows")

        self._last_cols = self.cols
        self._last_total_rows = total_rows

    def _build_grid(self):
        """Create the right-hand color cell canvases for all rows/columns."""
        for child in self.output_panel.winfo_children():
            child.destroy()
        self._reset_output_grid_config()

        total_rows = 1 + len(self.rows)
        self.cell_canvases = []
        self.cell_hex = [[None for _ in range(self.cols)] for _ in range(total_rows)]

        for r in range(total_rows):
            row_cells = []
            for c in range(self.cols):
                canvas = tk.Canvas(self.output_panel, highlightthickness=1, highlightbackground="#aaa")
                canvas.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
                # Repaint and keep input row height aligned when the cell resizes
                canvas.bind("<Configure>", lambda e, rr=r, cc=c: (self._repaint_cell(rr, cc), self._sync_input_row_height(rr)))
                canvas.bind("<Button-1>", lambda e, rr=r, cc=c: self._copy_cell(rr, cc))
                canvas.bind("<Button-2>", lambda e, rr=r, cc=c: self._show_ctx_menu(e, rr, cc))
                canvas.bind("<Button-3>", lambda e, rr=r, cc=c: self._show_ctx_menu(e, rr, cc))
                canvas.bind("<Control-Button-1>", lambda e, rr=r, cc=c: self._show_ctx_menu(e, rr, cc))  # macOS right-click
                row_cells.append(canvas)
            self.cell_canvases.append(row_cells)

        self.after(0, self._sync_all_input_row_heights)

    def _sync_input_row_height(self, r):
        """Match the input panel row height with the corresponding output row height."""
        total_rows = 1 + len(self.rows)
        if r < 0 or r >= total_rows:
            return
        heights = []
        for c in range(len(self.cell_canvases[r])):
            h = self.cell_canvases[r][c].winfo_height()
            if h > 1:
                heights.append(h)
        if not heights:
            return
        canvas_h = max(heights)
        target = canvas_h + 8
        try:
            # header is row 0; adjustable rows map to input_panel rows 1..N
            self.input_panel.grid_rowconfigure(r, minsize=target)
        except Exception:
            pass

    def _sync_all_input_row_heights(self):
        for r in range(1 + len(self.rows)):
            self._sync_input_row_height(r)

    # ---------- Context menu ----------
    def _show_ctx_menu(self, event, r, c):
        """Show context menu for a specific cell."""
        # Remember which cell was clicked
        self._ctx_cell = (r, c)
        # Remember the hex value that was clicked
        self._ctx_hex = self.cell_hex[r][c] if (hasattr(self, "cell_hex") and self.cell_hex and self.cell_hex[r][c]) else None
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    def _copy_ctx_hex(self):
        if not self._ctx_hex:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._ctx_hex.upper())
        except Exception:
            pass

    def _copy_ctx_rgb(self):
        if not self._ctx_hex:
            return
        r, g, b = hex_to_rgb_tuple(self._ctx_hex)
        try:
            self.clipboard_clear()
            self.clipboard_append(f"rgb({r}, {g}, {b})")
        except Exception:
            pass

    # ---------- Painting ----------
    def _update_grid(self):
        """Recompute all hex colors from current inputs and repaint cells."""
        if not hasattr(self, "cell_hex") or not hasattr(self, "cell_canvases"):
            return

        base_h = int(self.h_var.get())
        step = 360.0 / self.cols
        hue_steps = [(base_h + step * i) % 360 for i in range(self.cols)]

        total_rows = 1 + len(self.rows)

        # Top row: fixed S/V = 100%
        for c in range(self.cols):
            self.cell_hex[0][c] = hsv_to_hex(hue_steps[c], 100, 100)
            self._repaint_cell(0, c)

        # Adjustable rows
        for r in range(1, total_rows):
            s_val = self.rows[r - 1]["s"].get()
            v_val = self.rows[r - 1]["v"].get()
            for c in range(self.cols):
                self.cell_hex[r][c] = hsv_to_hex(hue_steps[c], s_val, v_val)
                self._repaint_cell(r, c)

        self._sync_all_input_row_heights()

    def _repaint_cell(self, r, c):
        """Paint a single cell (background + hex label with readable contrast)."""
        canvas = self.cell_canvases[r][c]
        hex_color = self.cell_hex[r][c]
        if not hex_color:
            return
        canvas.delete("all")
        w = max(10, canvas.winfo_width())
        h = max(10, canvas.winfo_height())
        canvas.create_rectangle(0, 0, w, h, fill=hex_color, outline="")
        fill = "#000" if is_light(hex_color) else "#fff"
        canvas.create_text(
            6, h - 6,
            text=hex_color.upper(),
            anchor="sw",
            fill=fill,
            font=("TkDefaultFont", 9),
        )

    # ---------- Clipboard ----------
    def _copy_cell(self, r, c):
        """Copy the cell's hex value to the clipboard."""
        hex_color = self.cell_hex[r][c]
        if not hex_color:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(hex_color.upper())
        except Exception:
            pass

    # ---------- Pillow text-size helper ----------
    @staticmethod
    def _text_size(draw, text, font):
        """Compatible text measurement across Pillow versions."""
        if hasattr(draw, "textbbox"):
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        if hasattr(draw, "textsize"):
            return draw.textsize(text, font=font)
        if hasattr(font, "getsize"):
            return font.getsize(text)
        return (len(text) * 7, 12)  # fallback guess

    # ---------- Export / Import ----------
    def _export_png(self):
        """Export the current grid to a PNG (with hex labels)."""
        if not PIL_AVAILABLE:
            messagebox.showerror(
                "Missing Dependency",
                "Pillow (PIL) is required for PNG export.\nInstall with:\n\npip install pillow",
            )
            return

        with _suppress_cocoa_stderr():
            path = filedialog.asksaveasfilename(
                defaultextension=".png",
                filetypes=[("PNG Image", "*.png")],
                title="Export PNG",
            )
        if not path:
            return

        total_rows = 1 + len(self.rows)
        cell_w = max(40, max(self.cell_canvases[0][c].winfo_width() for c in range(self.cols)))
        cell_h = max(40, max(self.cell_canvases[r][0].winfo_height() for r in range(total_rows)))
        gap = 8
        img_w = self.cols * (cell_w + gap) + gap
        img_h = total_rows * (cell_h + gap) + gap

        img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font = ImageFont.load_default()

        for r in range(total_rows):
            for c in range(self.cols):
                x0 = gap + c * (cell_w + gap)
                y0 = gap + r * (cell_h + gap)
                x1 = x0 + cell_w
                y1 = y0 + cell_h
                hex_color = self.cell_hex[r][c]
                rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
                draw.rectangle([x0, y0, x1, y1], fill=rgb, outline=(170, 170, 170))
                text = hex_color.upper()
                light = is_light(hex_color)
                text_rgb = (0, 0, 0) if light else (255, 255, 255)
                tw, th = self._text_size(draw, text, font)
                draw.text((x0 + 6, y0 + cell_h - 6 - th), text, fill=text_rgb, font=font)

        try:
            img.save(path, format="PNG")
        except Exception as e:
            messagebox.showerror("Export PNG", f"Failed to save PNG:\n{e}")

    def _export_ini(self):
        """
        Export an INI with:
        [meta] app/version
        [inputs] cols, h, rows_count, row2_s/row2_v..row{N+1}_s/_v
        [hex] row1..row{N+1} (space-separated #RRGGBB) in current on-screen order
        """
        with _suppress_cocoa_stderr():
            path = filedialog.asksaveasfilename(
                defaultextension=".ini",
                filetypes=[("INI File", "*.ini")],
                title="Export INI",
            )
        if not path:
            return

        cfg = configparser.ConfigParser()
        cfg["meta"] = {"app": "hsv_palette_designer", "version": APP_VERSION}
        cfg["inputs"] = {
            "cols": str(self.cols),
            "h": str(int(self.h_var.get())),
            "rows_count": str(len(self.rows)),
        }
        # Adjustable rows are row2..row{N+1}
        for i, r in enumerate(self.rows, start=2):
            s = r["s"].get()
            v = r["v"].get()
            cfg["inputs"][f"row{i}_s"] = str(int(s))
            cfg["inputs"][f"row{i}_v"] = str(int(v))

        # Hex grid rows: row1..row{N+1}
        total_rows = 1 + len(self.rows)
        hex_section = {}
        for r in range(total_rows):
            row_hex = [self.cell_hex[r][c].upper() for c in range(self.cols)]
            hex_section[f"row{r + 1}"] = " ".join(row_hex)
        cfg["hex"] = hex_section
        
        # Palette section: space-separated hex codes in current order (can be empty)
        cfg["palette"] = {"colors": " ".join(h.upper() for h in self.palette_hexes)}

        try:
            with open(path, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception as e:
            messagebox.showerror("Export INI", f"Failed to save INI:\n{e}")

    def _import_ini(self):
        """
        Import an INI in the same schema we export:
        - Validates presence and ranges
        - Rebuilds adjustable rows in the INI's order
        - Applies cols and hue, then repaints
        """
        with _suppress_cocoa_stderr():
            path = filedialog.askopenfilename(filetypes=[("INI File", "*.ini")], title="Import INI")
        if not path:
            return

        cfg = configparser.ConfigParser()
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg.read_file(f)
        except Exception as e:
            messagebox.showerror("Import INI", f"Could not read INI:\n{e}")
            return

        if "inputs" not in cfg or "hex" not in cfg:
            messagebox.showerror("Import INI", "Invalid INI: missing [inputs] or [hex] sections.")
            return

        inputs = cfg["inputs"]
        try:
            cols = int(inputs.get("cols"))
            h = int(inputs.get("h"))
            rows_count = int(inputs.get("rows_count"))
        except Exception:
            messagebox.showerror("Import INI", "Invalid INI: 'cols', 'h', 'rows_count' must be integers.")
            return

        if not (MIN_COLS <= cols <= MAX_COLS) or not (0 <= h <= 359) or rows_count < 0 or rows_count > 50:
            messagebox.showerror("Import INI", "Invalid INI: out-of-range values.")
            return

        # Read S/V for each adjustable row row2..row{rows_count+1}
        sv_vals = []
        for i in range(2, rows_count + 2):
            try:
                s = int(inputs.get(f"row{i}_s"))
                v = int(inputs.get(f"row{i}_v"))
            except Exception:
                messagebox.showerror("Import INI", f"Invalid INI: missing S/V for row{i}.")
                return
            if not (0 <= s <= 100 and 0 <= v <= 100):
                messagebox.showerror("Import INI", f"Invalid INI: S/V must be 0-100 for row{i}.")
                return
            sv_vals.append((s, v))

        # Validate hex rows shape (counts + basic format)
        hex_sec = cfg["hex"]
        total_rows = 1 + rows_count
        for r in range(1, total_rows + 1):
            key = f"row{r}"
            if key not in hex_sec:
                messagebox.showerror("Import INI", f"Invalid INI: missing hex list for {key}.")
                return
            arr = [x.strip().upper() for x in hex_sec[key].split() if x.strip()]
            if len(arr) != cols or any(len(x) != 7 or not x.startswith("#") for x in arr):
                messagebox.showerror("Import INI", f"Invalid INI: hex list for {key} must have {cols} space-separated items like #RRGGBB.")
                return

        # Apply: clear current rows and rebuild from INI values
        for r in self.rows:
            r["frame"].destroy()
        self.rows = []

        self.cols = cols
        self.cols_var.set(cols)
        self.h_var.set(h)
        self.h_scale.set(h)

        for s, v in sv_vals:
            self._add_row(initial_s=s, initial_v=v, build_only=True)

        self._regrid_inputs()
        self._build_grid()
        self._update_grid()
        
        # --- Palette import ---
        if "palette" in cfg:
            raw = (cfg["palette"].get("colors") or "").strip()
            if raw:
                items = [x.strip().upper() for x in raw.split() if x.strip()]
                # Validate all are #RRGGBB
                if any(len(x) != 7 or not x.startswith("#") for x in items):
                    messagebox.showerror(
                        "Import INI",
                        "Invalid INI: [palette] colors must be space-separated items like #RRGGBB."
                    )
                    return
                self._apply_imported_palette(items)
            else:
                # empty palette is allowed
                self._apply_imported_palette([])

        
    # ---------- Palette window: creation / menu / add / remove / rebuild ----------
    def _ctx_add_to_palette(self):
        """Context action from main grid: add the clicked color to the Palette window."""
        if not self._ctx_hex:
            return
        self._palette_add_color(self._ctx_hex)
        self._palette_refresh_layout()

    def _ensure_palette_window(self):
        """Create Palette Toplevel and its context menu the first time it's needed."""
        if self.palette_win and self.palette_win.winfo_exists():
            return

        self.palette_win = tk.Toplevel(self)
        self.palette_win.title("Palette")
        self.palette_win.minsize(320, 240)

        if self._palette_geometry:
            try:
                self.palette_win.geometry(self._palette_geometry)
            except Exception:
                pass
        self.after(0, self._palette_refresh_layout)

        # Destroy hooks: when closed, drop references
        def _on_close():
            try:
                # Save current geometry
                try:
                    self._palette_geometry = self.palette_win.geometry()
                except Exception:
                    pass
            finally:
                self.palette_win.destroy()
                self.palette_win = None
                self.palette_frame = None
                self._palette_menu = None
        self.palette_win.protocol("WM_DELETE_WINDOW", _on_close)

        # Container for palette squares
        self.palette_frame = ttk.Frame(self.palette_win, padding=8)
        self.palette_frame.pack(fill="both", expand=True)
        
        # Reflow on palette frame resize (debounced)
        def _on_palette_resize(event):
            if self._palette_resize_after is not None:
                try:
                    self.after_cancel(self._palette_resize_after)
                except Exception:
                    pass
            self._palette_resize_after = self.after(50, self._rebuild_palette_grid)

        self.palette_frame.bind("<Configure>", _on_palette_resize)

        # Palette context menu (right-click on palette squares)
        self._palette_menu = tk.Menu(self.palette_win, tearoff=0)
        self._palette_menu.add_command(label="Remove from Palette", command=self._palette_remove_ctx)
        self._palette_menu.add_separator()
        self._palette_menu.add_command(label="Copy HEX value", command=self._palette_copy_hex_ctx)
        self._palette_menu.add_command(label="Copy RGB value", command=self._palette_copy_rgb_ctx)

        # Track which color in palette was last right-clicked
        self._palette_ctx_hex = None

    def _palette_add_color(self, hex_color):
        """Add a hex color to the palette unless it's already present."""
        if not hex_color:
            return
        if hex_color.upper() in (h.upper() for h in self.palette_hexes):
            return  # no duplicates

        self._ensure_palette_window()

        hex_color = hex_color.upper()
        if hex_color in self.palette_hex_set:
            return
        self._ensure_palette_window()
        self.palette_hexes.append(hex_color)
        self.palette_hex_set.add(hex_color)
        self._rebuild_palette_grid()


    def _rebuild_palette_grid(self):
        """Rebuild the palette grid from self.palette_hexes, auto-fitting columns to width."""
        if not (self.palette_win and self.palette_win.winfo_exists() and self.palette_frame):
            return

        # Clear previous widgets
        for child in self.palette_frame.winfo_children():
            child.destroy()
        self.palette_canvases.clear()

        count = len(self.palette_hexes)
        if count == 0:
            # Still make columns stretch so the frame expands cleanly
            self.palette_frame.grid_columnconfigure(0, weight=1, uniform="pcols")
            return

        # Compute how many columns we can fit based on current width
        cols = self._palette_compute_cols(count)

        # Place canvases in a wrapped grid using 'cols' columns
        for idx, hex_color in enumerate(self.palette_hexes):
            r = idx // cols
            c = idx % cols

            canvas = tk.Canvas(
                self.palette_frame,
                highlightthickness=1,
                highlightbackground="#aaa"
            )
            canvas.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")

            # Repaint tile on resize to keep it filled
            canvas.bind("<Configure>", lambda e, h=hex_color, cv=canvas: self._paint_palette_square(cv, h))

            # Left click = copy HEX; right-click variants show context menu
            canvas.bind("<Button-1>",            lambda e, h=hex_color: self._palette_copy_hex(h))
            canvas.bind("<Button-3>",            lambda e, h=hex_color: self._show_palette_menu(e, h))
            canvas.bind("<Button-2>",            lambda e, h=hex_color: self._show_palette_menu(e, h))         # macOS
            canvas.bind("<Control-Button-1>",    lambda e, h=hex_color: self._show_palette_menu(e, h))          # macOS Ctrl+click

            self.palette_canvases[hex_color] = canvas

        # Stretch columns/rows that are actually used
        # First reset a reasonable range
        for col in range(self.palette_max_cols + 1):
            self.palette_frame.grid_columnconfigure(col, weight=0, uniform="")

        rows = (count + cols - 1) // cols
        for row in range(max(1, rows) + 2):
            self.palette_frame.grid_rowconfigure(row, weight=0, uniform="")

        # Now set weights for the used ones
        for col in range(cols):
            self.palette_frame.grid_columnconfigure(col, weight=1, uniform="pcols")
        for row in range(rows):
            self.palette_frame.grid_rowconfigure(row, weight=1, uniform="prows")

    def _paint_palette_square(self, canvas, hex_color):
        """Paint a palette-square canvas background + hex label with readable contrast."""
        canvas.delete("all")
        w = max(2, canvas.winfo_width())
        h = max(2, canvas.winfo_height())

        # Fill the entire canvas
        canvas.create_rectangle(0, 0, w, h, fill=hex_color, outline="")

        # Label with good contrast
        fill = "#000" if is_light(hex_color) else "#fff"
        canvas.create_text(6, h - 6, text=hex_color.upper(), anchor="sw", fill=fill, font=("TkDefaultFont", 9))

    def _show_palette_menu(self, event, hex_color):
        """Show context menu for a palette square and remember which hex it represents."""
        self._palette_ctx_hex = hex_color
        try:
            self._palette_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._palette_menu.grab_release()

    def _palette_remove_ctx(self):
        """Remove the last right-clicked color from the palette."""
        if not self._palette_ctx_hex:
            return
        hex_target = self._palette_ctx_hex.upper()
        if hex_target in self.palette_hex_set:
            self.palette_hex_set.remove(hex_target)
        self.palette_hexes = [h for h in self.palette_hexes if h.upper() != hex_target]
        self._palette_ctx_hex = None
        self._rebuild_palette_grid()

    # --- Palette copy helpers (context + direct) ---
    def _palette_copy_hex_ctx(self):
        if not self._palette_ctx_hex:
            return
        self._palette_copy_hex(self._palette_ctx_hex)

    def _palette_copy_rgb_ctx(self):
        if not self._palette_ctx_hex:
            return
        self._palette_copy_rgb(self._palette_ctx_hex)

    def _palette_copy_hex(self, hex_color):
        try:
            self.clipboard_clear()
            self.clipboard_append(hex_color.upper())
        except Exception:
            pass

    def _palette_copy_rgb(self, hex_color):
        r_, g_, b_ = hex_to_rgb_tuple(hex_color)
        text = f"rgb({r_}, {g_}, {b_})"   # or f"{r_}, {g_}, {b_}"
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass
    def _open_palette_window(self):
        """Ensure the palette window exists and bring it to front (even if empty)."""
        self._ensure_palette_window()
        self._palette_refresh_layout()
        try:
            self.palette_win.deiconify()
            self.palette_win.lift()
            self.palette_win.focus_force()
        except Exception:
            pass

    def _palette_compute_cols(self, count):
        tile_budget = max(60, self.palette_min_tile)
        w = max(1, self.palette_frame.winfo_width() or 1)
        est_cols = max(1, int(w // tile_budget))
        cols = min(self.palette_max_cols, count, est_cols)
        return max(1, min(cols, count))

    
    def _palette_refresh_layout(self):
        """Recompute palette tile sizing after (re)opening or geometry changes."""
        if not (self.palette_win and self.palette_win.winfo_exists()):
            return
        # Ensure geometry is applied, then rebuild now and once more after layout settles
        try:
            self.palette_win.update_idletasks()
        except Exception:
            pass
        self._rebuild_palette_grid()
        # A second pass a tick later helps after geometry restore / window mapping
        self.after(40, self._rebuild_palette_grid)

    def _apply_imported_palette(self, items):
        """
        Apply an imported palette list (iterable of '#RRGGBB'), preserving order
        and removing duplicates. Updates the palette window if it's open.
        """
        # de-dup while preserving order
        seen = set()
        ordered = []
        for h in (x.upper() for x in items):
            if h not in seen:
                seen.add(h)
                ordered.append(h)

        self.palette_hexes = ordered
        self.palette_canvases.clear()

        # If the palette window is open, rebuild it; otherwise keep it lazy
        if self.palette_win and self.palette_win.winfo_exists():
            self._rebuild_palette_grid()

# ---------------- Entry point ----------------
if __name__ == "__main__":
    app = PaletteApp()
    # After layout settles, re-sync row heights to match grid cells
    app.after(120, app._sync_all_input_row_heights)
    app.mainloop()
