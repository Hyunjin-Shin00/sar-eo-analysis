#!/usr/bin/env python3
"""
BlueBON Geometric Correction Pipeline — GUI Interface (tkinter)

PipelineConfig 및 유틸리티 함수는 pipeline_config.py 참조.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional, Tuple

from pipeline_config import (
    PipelineConfig,
    parse_filename,
    get_rgb_band_indices,
    get_output_folder_name,
    get_output_filename,
    get_segment_names,
)


class PipelineGUI:

    C = {
        'bg':           '#1A1D23',
        'panel':        '#21252D',
        'surface':      '#282C35',
        'border':       '#333844',
        'text':         '#E2E8F0',
        'text_dim':     '#7A8499',
        'accent':       '#4A9EFF',
        'accent_hover': '#3D8EEE',
        'accent_dim':   '#1A2D45',
        'green':        '#3ECF72',
        'green_dim':    '#122B1E',
        'green_border': '#235C38',
        'amber':        '#F5A623',
        'amber_dim':    '#2E1F00',
        'amber_border': '#6B4800',
        'entry_bg':     '#1E222A',
        'entry_border': '#3A3F4E',
        'header_bg':    '#141720',
    }

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("BlueBON — Geometric Correction Pipeline")
        self.root.resizable(True, True)
        self.root.configure(bg=self.C['bg'])
        self.config: Optional[PipelineConfig] = None
        self.file_info: Optional[dict] = None

        self._setup_styles()
        self._build()
        self._center(680, 750)

    def _center(self, w, h):
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.root.minsize(600, 640)

    def _setup_styles(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')
        c = self.C

        s.configure('TEntry',
                    fieldbackground=c['entry_bg'],
                    foreground=c['text'],
                    insertcolor=c['accent'],
                    bordercolor=c['entry_border'],
                    lightcolor=c['entry_border'],
                    darkcolor=c['entry_border'],
                    selectbackground=c['accent_dim'],
                    selectforeground=c['text'],
                    relief='flat', padding=7)
        s.map('TEntry',
              bordercolor=[('focus', c['accent'])],
              fieldbackground=[('focus', '#222831')])

        s.configure('Vertical.TScrollbar',
                    background=c['surface'],
                    troughcolor=c['bg'],
                    bordercolor=c['bg'],
                    arrowcolor=c['text_dim'],
                    relief='flat')
        s.map('Vertical.TScrollbar',
              background=[('active', c['border'])])

    # ── helpers ──────────────────────────────────────────────────────────────

    def _label(self, parent, text, size=10, bold=False, dim=False, **kw):
        weight = 'bold' if bold else 'normal'
        color = self.C['text_dim'] if dim else self.C['text']
        return tk.Label(parent, text=text,
                        bg=kw.pop('bg', self.C['panel']),
                        fg=kw.pop('fg', color),
                        font=('Helvetica', size, weight), **kw)

    def _sep(self, parent):
        tk.Frame(parent, bg=self.C['border'], height=1).pack(fill=tk.X, pady=12)

    def _section(self, parent, title) -> tk.Frame:
        card = tk.Frame(parent, bg=self.C['panel'],
                        highlightbackground=self.C['border'],
                        highlightthickness=1)
        card.pack(fill=tk.X, pady=(0, 12))

        title_row = tk.Frame(card, bg=self.C['surface'])
        title_row.pack(fill=tk.X)
        tk.Label(title_row, text=title,
                 bg=self.C['surface'], fg=self.C['text'],
                 font=('Helvetica', 10, 'bold'),
                 anchor='w').pack(side=tk.LEFT, padx=16, pady=9)

        body = tk.Frame(card, bg=self.C['panel'], padx=16, pady=14)
        body.pack(fill=tk.X)
        return body

    def _btn(self, parent, text, cmd, bg, fg, hover, width=12, pady=9):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bg, fg=fg, font=('Helvetica', 10, 'bold'),
                      relief='flat', cursor='hand2',
                      width=width, pady=pady,
                      activebackground=hover, activeforeground=fg,
                      borderwidth=0)
        b.bind('<Enter>', lambda _: b.config(bg=hover))
        b.bind('<Leave>', lambda _: b.config(bg=bg))
        return b

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self):
        c = self.C

        hdr = tk.Frame(self.root, bg=c['header_bg'], height=64)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        tk.Label(hdr, text="BlueBON  Geometric Correction Pipeline",
                 bg=c['header_bg'], fg=c['text'],
                 font=('Helvetica', 14, 'bold')).pack(side=tk.LEFT, padx=20, pady=14)

        tk.Label(hdr, text="v2",
                 bg=c['header_bg'], fg=c['text_dim'],
                 font=('Helvetica', 10)).pack(side=tk.LEFT, pady=20)

        sbar = tk.Frame(self.root, bg=c['header_bg'], height=24)
        sbar.pack(fill=tk.X, side=tk.BOTTOM)
        sbar.pack_propagate(False)
        self._status_var = tk.StringVar(value="Ready")
        self._status_lbl = tk.Label(sbar, textvariable=self._status_var,
                                    bg=c['header_bg'], fg=c['text_dim'],
                                    font=('Helvetica', 8), anchor='w')
        self._status_lbl.pack(fill=tk.BOTH, padx=14)

        canvas = tk.Canvas(self.root, bg=c['bg'], highlightthickness=0)
        vsb = ttk.Scrollbar(self.root, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(fill=tk.BOTH, expand=True)

        sf = tk.Frame(canvas, bg=c['bg'])
        wid = canvas.create_window((0, 0), window=sf, anchor='nw')
        sf.bind('<Configure>',
                lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfig(wid, width=e.width))
        canvas.bind_all('<MouseWheel>',
                        lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), 'units'))

        body = tk.Frame(sf, bg=c['bg'], padx=20, pady=18)
        body.pack(fill=tk.BOTH, expand=True)

        # ── 1. Input Image ────────────────────────────────────────────────────
        s1 = self._section(body, "Input Image")

        path_box = tk.Frame(s1, bg=c['entry_bg'],
                            highlightbackground=c['entry_border'],
                            highlightthickness=1)
        path_box.pack(fill=tk.X, pady=(0, 10))

        self._file_var = tk.StringVar()
        self._path_lbl = tk.Label(path_box, textvariable=self._file_var,
                                  bg=c['entry_bg'], fg=c['accent'],
                                  font=('Helvetica', 9),
                                  anchor='w', justify='left', wraplength=590)
        self._ph_lbl = tk.Label(path_box,
                                text="No file selected",
                                bg=c['entry_bg'], fg=c['text_dim'],
                                font=('Helvetica', 9), anchor='w')
        self._ph_lbl.pack(padx=10, pady=8, anchor='w')

        self._btn(s1, "Browse...", self._browse,
                  bg=c['surface'], fg=c['text_dim'],
                  hover=c['border'], width=14, pady=6).pack(anchor='w')

        self._info_frame = tk.Frame(s1, bg=c['green_dim'],
                                    highlightbackground=c['green_border'],
                                    highlightthickness=1)
        self._info_var = tk.StringVar()
        tk.Label(self._info_frame, textvariable=self._info_var,
                 bg=c['green_dim'], fg=c['green'],
                 font=('Helvetica', 9), anchor='w', justify='left'
                 ).pack(fill=tk.X, padx=10, pady=7)

        # ── 2. Coordinates ────────────────────────────────────────────────────
        s2 = self._section(body, "Center Coordinates")

        grid = tk.Frame(s2, bg=c['panel'])
        grid.pack(anchor='w')

        for i, (lbl, attr, hint) in enumerate([
            ("Latitude",  "lat_var", "e.g.  37.5665"),
            ("Longitude", "lon_var", "e.g.  126.9780"),
        ]):
            tk.Label(grid, text=lbl,
                     bg=c['panel'], fg=c['text'],
                     font=('Helvetica', 10), width=12, anchor='e'
                     ).grid(row=i, column=0, padx=(0, 12), pady=6, sticky='e')

            var = tk.StringVar()
            setattr(self, attr, var)
            ttk.Entry(grid, textvariable=var, width=22,
                      font=('Helvetica', 10)
                      ).grid(row=i, column=1, pady=6, sticky='w')

            tk.Label(grid, text=f"°    ({hint})",
                     bg=c['panel'], fg=c['text_dim'],
                     font=('Helvetica', 9)
                     ).grid(row=i, column=2, padx=10, pady=6, sticky='w')

        # ── 3. Options ────────────────────────────────────────────────────────
        s3 = self._section(body, "Processing Options")

        tk.Label(s3, text="Image Strip Count",
                 bg=c['panel'], fg=c['text'],
                 font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(0, 8))

        self._seg_var = tk.IntVar(value=3)
        seg_row = tk.Frame(s3, bg=c['panel'])
        seg_row.pack(anchor='w', pady=(0, 6))

        for val, label, sub in [
            (1, "1 Strip",  "Full"),
            (2, "2 Strips", "Upper / Lower"),
            (3, "3 Strips", "Top / Center / Bottom"),
        ]:
            cell = tk.Frame(seg_row, bg=c['panel'])
            cell.pack(side=tk.LEFT, padx=(0, 24))

            tk.Radiobutton(cell, text=label,
                           variable=self._seg_var, value=val,
                           bg=c['panel'], fg=c['text'],
                           selectcolor=c['accent_dim'],
                           activebackground=c['panel'],
                           activeforeground=c['accent'],
                           font=('Helvetica', 10),
                           command=self._refresh_badge).pack(anchor='w')

            tk.Label(cell, text=sub,
                     bg=c['panel'], fg=c['text_dim'],
                     font=('Helvetica', 8)).pack(anchor='w', padx=20)

        self._badge_var = tk.StringVar(value="  Top  |  Center  |  Bottom  ")
        tk.Label(s3, textvariable=self._badge_var,
                 bg=c['accent_dim'], fg=c['accent'],
                 font=('Helvetica', 9, 'bold'),
                 padx=10, pady=4).pack(anchor='w', pady=(4, 14))

        self._sep(s3)

        res_row = tk.Frame(s3, bg=c['panel'])
        res_row.pack(fill=tk.X, pady=(0, 10))

        tk.Label(res_row, text="Target Resolution",
                 bg=c['panel'], fg=c['text'],
                 font=('Helvetica', 10), anchor='w', width=18
                 ).pack(side=tk.LEFT)

        self._res_var = tk.StringVar(value="4.8")
        ttk.Entry(res_row, textvariable=self._res_var,
                  width=10, font=('Helvetica', 10)).pack(side=tk.LEFT, padx=10)

        tk.Label(res_row, text="m/px  (default: 4.8)",
                 bg=c['panel'], fg=c['text_dim'],
                 font=('Helvetica', 9)).pack(side=tk.LEFT)

        self._sep(s3)

        self._save_var = tk.BooleanVar(value=False)
        tk.Checkbutton(s3, text="Save intermediate results",
                       variable=self._save_var,
                       bg=c['panel'], fg=c['text'],
                       selectcolor=c['accent_dim'],
                       activebackground=c['panel'],
                       activeforeground=c['accent'],
                       font=('Helvetica', 10)).pack(anchor='w')

        # ── 4. GCP Chip Mode ─────────────────────────────────────────────────
        s4 = self._section(body, "GCP Chip Mode  (optional)")

        self._gcp_chip_var = tk.BooleanVar(value=False)
        tk.Checkbutton(s4, text="Use GCP chips for matching",
                       variable=self._gcp_chip_var,
                       bg=c['panel'], fg=c['text'],
                       selectcolor=c['accent_dim'],
                       activebackground=c['panel'],
                       activeforeground=c['accent'],
                       font=('Helvetica', 10),
                       command=self._toggle_gcp_chip).pack(anchor='w', pady=(0, 10))

        self._gcp_inputs = tk.Frame(s4, bg=c['panel'])
        self._gcp_inputs.pack(fill=tk.X)

        gcp_box = tk.Frame(self._gcp_inputs, bg=c['entry_bg'],
                           highlightbackground=c['entry_border'],
                           highlightthickness=1)
        gcp_box.pack(fill=tk.X, pady=(0, 6))

        self._gcp_dir_var = tk.StringVar()
        self._gcp_ph_lbl = tk.Label(gcp_box, text="No folder selected",
                                    bg=c['entry_bg'], fg=c['text_dim'],
                                    font=('Helvetica', 9), anchor='w')
        self._gcp_path_lbl = tk.Label(gcp_box, textvariable=self._gcp_dir_var,
                                      bg=c['entry_bg'], fg=c['accent'],
                                      font=('Helvetica', 9),
                                      anchor='w', justify='left', wraplength=560)
        self._gcp_ph_lbl.pack(padx=10, pady=6, anchor='w')

        self._gcp_browse_btn = self._btn(
            self._gcp_inputs, "Browse...", self._browse_gcp_chips,
            bg=c['surface'], fg=c['text_dim'],
            hover=c['border'], width=14, pady=6)
        self._gcp_browse_btn.pack(anchor='w', pady=(0, 8))

        gcp_res_row = tk.Frame(self._gcp_inputs, bg=c['panel'])
        gcp_res_row.pack(fill=tk.X)

        tk.Label(gcp_res_row, text="Chip Resolution",
                 bg=c['panel'], fg=c['text'],
                 font=('Helvetica', 10), width=18, anchor='w').pack(side=tk.LEFT)

        self._gcp_res_var = tk.StringVar(value="1.2")
        self._gcp_res_entry = ttk.Entry(gcp_res_row, textvariable=self._gcp_res_var,
                                        width=10, font=('Helvetica', 10))
        self._gcp_res_entry.pack(side=tk.LEFT, padx=10)

        tk.Label(gcp_res_row, text="m/px  (default: 1.2)",
                 bg=c['panel'], fg=c['text_dim'],
                 font=('Helvetica', 9)).pack(side=tk.LEFT)

        self._toggle_gcp_chip()

        # ── buttons ───────────────────────────────────────────────────────────
        btn_row = tk.Frame(body, bg=c['bg'])
        btn_row.pack(fill=tk.X, pady=(4, 2))

        self._btn(btn_row, "Cancel", self._cancel,
                  bg=c['surface'], fg=c['text_dim'],
                  hover=c['border'], width=10).pack(side=tk.LEFT)

        self._btn(btn_row, "Run", self._run,
                  bg=c['accent'], fg='#FFFFFF',
                  hover=c['accent_hover'], width=14).pack(side=tk.RIGHT)

    # ── handlers ─────────────────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select satellite imagery (TIFF)",
            filetypes=[("TIFF files", "*.tiff *.tif *.TIFF *.TIF"),
                       ("All files", "*.*")])
        if not path:
            return

        self._file_var.set(path)
        self._ph_lbl.pack_forget()
        self._path_lbl.pack(padx=10, pady=8, fill=tk.X)

        self.file_info = parse_filename(path)

        if self.file_info and self.file_info['band_count'] > 0:
            fi = self.file_info
            info = (f"Level: {fi['level']}    Date: {fi['date']}    "
                    f"Time: {fi['time']}    Bands: {fi['band_count']}")
        elif self.file_info:
            info = "File accepted  (band count will be detected at runtime)"
        else:
            info = "Filename format unrecognized — treated as generic TIFF"

        self._info_var.set(f"  {info}")
        self._info_frame.pack(fill=tk.X, pady=(10, 0))
        self._set_status(f"Loaded: {path.split('/')[-1]}", ok=True)

    def _browse_gcp_chips(self):
        path = filedialog.askdirectory(title="Select GCP Chips folder")
        if not path:
            return
        self._gcp_dir_var.set(path)
        self._gcp_ph_lbl.pack_forget()
        self._gcp_path_lbl.pack(padx=10, pady=6, fill=tk.X)
        self._set_status(f"GCP chips: {path.split('/')[-1]}", ok=True)

    def _toggle_gcp_chip(self):
        enabled = self._gcp_chip_var.get()
        self._gcp_browse_btn.config(
            state=tk.NORMAL if enabled else tk.DISABLED,
            fg=self.C['text_dim'] if enabled else self.C['border'])
        if enabled:
            self._gcp_res_entry.state(['!disabled'])
        else:
            self._gcp_res_entry.state(['disabled'])

    def _refresh_badge(self):
        previews = {
            1: "  Full  ",
            2: "  Upper  |  Lower  ",
            3: "  Top  |  Center  |  Bottom  ",
        }
        self._badge_var.set(previews.get(self._seg_var.get(), ""))

    def _set_status(self, msg, ok=False):
        self._status_var.set(msg)
        self._status_lbl.config(
            fg=self.C['green'] if ok else self.C['text_dim'])

    def _validate(self) -> Tuple[bool, str]:
        path = self._file_var.get()
        if not path or not __import__('os').path.exists(path):
            return False, "Please select a TIFF file."
        try:
            lat = float(self.lat_var.get())
            if not -90 <= lat <= 90:
                return False, "Latitude must be between -90 and 90."
        except ValueError:
            return False, "Invalid latitude.  (e.g. 37.5665)"
        try:
            lon = float(self.lon_var.get())
            if not -180 <= lon <= 180:
                return False, "Longitude must be between -180 and 180."
        except ValueError:
            return False, "Invalid longitude.  (e.g. 126.9780)"
        try:
            res = float(self._res_var.get())
            if res <= 0:
                return False, "Resolution must be greater than 0."
        except ValueError:
            return False, "Invalid resolution.  (e.g. 4.8)"
        if self._gcp_chip_var.get():
            gcp_dir = self._gcp_dir_var.get()
            if not gcp_dir or not __import__('os').path.isdir(gcp_dir):
                return False, "Please select a valid GCP Chips folder."
            try:
                gcp_res = float(self._gcp_res_var.get())
                if gcp_res <= 0:
                    return False, "GCP chip resolution must be greater than 0."
            except ValueError:
                return False, "Invalid GCP chip resolution.  (e.g. 1.2)"
        return True, ""

    def _run(self):
        ok, msg = self._validate()
        if not ok:
            messagebox.showerror("Input Error", msg)
            return

        path = self._file_var.get()
        fi = self.file_info or parse_filename(path)
        band_count = fi.get('band_count', 0)

        if band_count == 0:
            try:
                import rasterio
                with rasterio.open(path) as src:
                    band_count = src.count
            except Exception:
                band_count = 3

        use_gcp = self._gcp_chip_var.get()
        self.config = PipelineConfig(
            input_path=path,
            level=fi.get('level', 'unknown'),
            date=fi.get('date', 'unknown'),
            time=fi.get('time', 'unknown'),
            band_count=band_count,
            center_lat=float(self.lat_var.get()),
            center_lon=float(self.lon_var.get()),
            num_segments=self._seg_var.get(),
            save_intermediate=self._save_var.get(),
            target_resolution=float(self._res_var.get()),
            gcp_chips_dir=self._gcp_dir_var.get() if use_gcp else None,
            gcp_chip_resolution=float(self._gcp_res_var.get()) if use_gcp else 1.2,
        )
        self.root.quit()
        self.root.destroy()

    def _cancel(self):
        self.config = None
        self.root.quit()
        self.root.destroy()

    def run(self) -> Optional[PipelineConfig]:
        self.root.mainloop()
        return self.config


def get_pipeline_config() -> Optional[PipelineConfig]:
    """Launch GUI and return pipeline configuration."""
    return PipelineGUI().run()


if __name__ == "__main__":
    config = get_pipeline_config()
    if config:
        import os
        print(f"[OK] {config.input_path}")
        print(f"     Coordinate : ({config.center_lat}, {config.center_lon})")
        print(f"     Strips     : {config.num_segments}  {get_segment_names(config.num_segments)}")
        print(f"     Resolution : {config.target_resolution} m/px")
        print(f"     Bands      : {config.band_count}  -> RGB {get_rgb_band_indices(config.band_count)}")
    else:
        print("[CANCELLED]")
