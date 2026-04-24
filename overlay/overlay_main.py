import ctypes
# Crucial fix for Windows 10/11 Scaling: Prevents pyautogui from missing targets on zoomed screens
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import font as tkfont
import threading
import time
from datetime import datetime

from screen_reader import capture_screen, analyze_screen_and_intent
from overlay_voice import OverlayVoice
from overlay_vision import OverlayVision
from overlay_adapter import inject_click


# ══════════════════════════════════════════════════════════════════════════════
# Colour Palette
# ══════════════════════════════════════════════════════════════════════════════
class Palette:
    """Centralised colour definitions for normal and high-contrast modes."""
    # --- Normal mode ---
    BG           = "#0d1117"
    BG_CARD      = "#161b22"
    BG_INPUT     = "#1c2333"
    ACCENT       = "#00e5ff"
    ACCENT_DIM   = "#0077b6"
    TEXT         = "#e6edf3"
    TEXT_DIM     = "#8b949e"
    SUCCESS      = "#3fb950"
    WARNING      = "#d29922"
    ERROR        = "#f85149"
    BORDER       = "#30363d"
    KEYPAD_BTN   = "#21262d"
    KEYPAD_HOVER = "#30363d"
    SELECTED     = "#00e5ff"

    # --- High-contrast mode (accessibility) ---
    HC_BG        = "#000000"
    HC_TEXT       = "#ffeb3b"
    HC_ACCENT    = "#ff9800"
    HC_BTN       = "#1a1a1a"
    HC_BORDER    = "#ffeb3b"


# ══════════════════════════════════════════════════════════════════════════════
# Adaptive UI State
# ══════════════════════════════════════════════════════════════════════════════
class AdaptationLevel:
    NORMAL  = "normal"
    VISUAL  = "visual"      # squinting detected → high-contrast + large fonts
    MOTOR   = "motor"       # leaning forward → larger buttons + more spacing
    FULL    = "full"        # both detected → max adaptation


# ══════════════════════════════════════════════════════════════════════════════
# Main Overlay Application
# ══════════════════════════════════════════════════════════════════════════════
class OverlayApp:
    # Font size multipliers for each adaptation level
    _FONT_SCALE = {
        AdaptationLevel.NORMAL: 1.0,
        AdaptationLevel.VISUAL: 1.4,
        AdaptationLevel.MOTOR:  1.2,
        AdaptationLevel.FULL:   1.5,
    }

    def __init__(self, root):
        self.root = root
        self.root.title("UIAA Universal Overlay")
        self.root.attributes("-topmost", True)
        self.root.geometry("460x780+50+50")
        self.root.configure(bg=Palette.BG)
        self.root.minsize(400, 600)

        # --- Core modules ---
        self.voice = OverlayVoice()
        try:
            self.vision = OverlayVision()
        except Exception as e:
            print(f"[Overlay] WARNING: Failed to start vision module: {e}")
            self.vision = None

        # --- State ---
        self.running = True
        self.monitor_info = None
        self._lock = threading.Lock()
        self._adaptation_level = AdaptationLevel.NORMAL
        self._cycle_had_error = False
        self._demo_mode = tk.BooleanVar(value=True)
        self._current_targets = []      # keep reference for re-rendering on adaptation change

        # Hysteresis: require N consecutive readings before switching adaptation
        self._HYSTERESIS_THRESHOLD = 6  # 6 × 0.5s = 3 seconds of stable signal
        self._pending_level = AdaptationLevel.NORMAL
        self._pending_count = 0

        # --- Fonts (will be reconfigured on adaptation) ---
        self._base_fonts = {
            "title":     {"family": "Segoe UI", "size": 14, "weight": "bold"},
            "status":    {"family": "Segoe UI", "size": 10},
            "indicator": {"family": "Segoe UI", "size": 9},
            "transcript":{"family": "Segoe UI", "size": 11, "slant": "italic"},
            "desc":      {"family": "Segoe UI", "size": 13, "weight": "bold"},
            "keypad":    {"family": "Segoe UI", "size": 13, "weight": "bold"},
            "keypad_num":{"family": "Segoe UI", "size": 10},
            "log":       {"family": "Consolas",  "size": 8},
            "section":   {"family": "Segoe UI", "size": 9, "weight": "bold"},
            "toggle":    {"family": "Segoe UI", "size": 9},
        }
        self._fonts = {}
        self._create_fonts(1.0)

        # ──────────────────────────────────────────────────────────────────
        # UI LAYOUT — built top to bottom
        # ──────────────────────────────────────────────────────────────────

        # ① Header
        self.header_frame = tk.Frame(root, bg=Palette.BG)
        self.header_frame.pack(fill=tk.X, padx=12, pady=(10, 2))
        self.title_lbl = tk.Label(
            self.header_frame, text="⬟  UIAA Overlay Active",
            font=self._fonts["title"], fg=Palette.ACCENT, bg=Palette.BG, anchor="w"
        )
        self.title_lbl.pack(side=tk.LEFT)
        self.version_lbl = tk.Label(
            self.header_frame, text="v2.0",
            font=self._fonts["indicator"], fg=Palette.TEXT_DIM, bg=Palette.BG, anchor="e"
        )
        self.version_lbl.pack(side=tk.RIGHT)

        # Thin accent line under header
        tk.Frame(root, bg=Palette.ACCENT, height=2).pack(fill=tk.X, padx=12, pady=(2, 6))

        # ② Status Dashboard — 3 indicators
        self.dash_frame = tk.Frame(root, bg=Palette.BG_CARD, highlightbackground=Palette.BORDER, highlightthickness=1)
        self.dash_frame.pack(fill=tk.X, padx=12, pady=3)

        self._voice_status  = tk.StringVar(value="Ready")
        self._vision_status = tk.StringVar(value="Initializing…")
        self._engine_status = tk.StringVar(value="Idle")

        self._voice_dot  = None
        self._vision_dot = None
        self._engine_dot = None

        for i, (icon, label, var) in enumerate([
            ("🎤", "Voice",  self._voice_status),
            ("📷", "Vision", self._vision_status),
            ("🧠", "Engine", self._engine_status),
        ]):
            row = tk.Frame(self.dash_frame, bg=Palette.BG_CARD)
            row.pack(fill=tk.X, padx=8, pady=2)

            dot = tk.Label(row, text="●", font=self._fonts["indicator"],
                           fg=Palette.SUCCESS, bg=Palette.BG_CARD)
            dot.pack(side=tk.LEFT, padx=(0, 4))

            tk.Label(row, text=f"{icon} {label}:",
                     font=self._fonts["indicator"], fg=Palette.TEXT_DIM, bg=Palette.BG_CARD,
                     width=10, anchor="w").pack(side=tk.LEFT)

            tk.Label(row, textvariable=var,
                     font=self._fonts["status"], fg=Palette.TEXT, bg=Palette.BG_CARD,
                     anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)

            # Store dot references for colour updates
            if i == 0: self._voice_dot = dot
            elif i == 1: self._vision_dot = dot
            else: self._engine_dot = dot

        # ③ Adaptation indicator
        self.adapt_frame = tk.Frame(root, bg=Palette.BG)
        self.adapt_frame.pack(fill=tk.X, padx=12, pady=(4, 2))
        self._adapt_var = tk.StringVar(value="Adaptation: Normal")
        self.adapt_lbl = tk.Label(
            self.adapt_frame, textvariable=self._adapt_var,
            font=self._fonts["indicator"], fg=Palette.TEXT_DIM, bg=Palette.BG, anchor="w"
        )
        self.adapt_lbl.pack(side=tk.LEFT)

        # ④ Voice Cycle Button
        self.btn_listen = tk.Button(
            root, text="🎤  Run Voice Cycle",
            font=self._fonts["keypad"],
            bg=Palette.ACCENT_DIM, fg="white", activebackground="#023e8a",
            relief=tk.FLAT, padx=14, pady=7, cursor="hand2",
            command=self.run_cycle_async
        )
        self.btn_listen.pack(fill=tk.X, padx=12, pady=6)

        # ⑤ Voice Transcript
        self.transcript_frame = tk.Frame(root, bg=Palette.BG)
        self.transcript_frame.pack(fill=tk.X, padx=12, pady=2)
        self._transcript_var = tk.StringVar(value="")
        self.transcript_lbl = tk.Label(
            self.transcript_frame, textvariable=self._transcript_var,
            font=self._fonts["transcript"], fg=Palette.ACCENT, bg=Palette.BG_INPUT,
            anchor="w", wraplength=420, justify=tk.LEFT, padx=10, pady=6
        )
        # Hidden initially — shown only after first voice cycle
        self._transcript_visible = False

        # ⑥ Screen Description (AI-generated) — adapts with accessibility
        self.desc_frame = tk.Frame(root, bg=Palette.BG)
        self.desc_frame.pack(fill=tk.X, padx=12, pady=2)
        self._desc_var = tk.StringVar(value="")
        self.desc_lbl = tk.Label(
            self.desc_frame, textvariable=self._desc_var,
            font=self._fonts["desc"], fg="#ffeb3b", bg="#111111",
            wraplength=420, justify=tk.LEFT, padx=10, pady=8, anchor="nw"
        )
        # Hidden initially
        self._desc_visible = False

        # ⑦ Virtual Keypad Section
        tk.Frame(root, bg=Palette.BORDER, height=1).pack(fill=tk.X, padx=12, pady=(6, 2))
        self.keypad_header = tk.Frame(root, bg=Palette.BG)
        self.keypad_header.pack(fill=tk.X, padx=12)
        self.keypad_title = tk.Label(
            self.keypad_header, text="▸ Virtual Accessibility Keypad",
            font=self._fonts["section"], fg=Palette.TEXT_DIM, bg=Palette.BG, anchor="w"
        )
        self.keypad_title.pack(side=tk.LEFT)

        # Scrollable keypad container
        self.keypad_outer = tk.Frame(root, bg=Palette.BG)
        self.keypad_outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=2)

        self.keypad_canvas = tk.Canvas(self.keypad_outer, bg=Palette.BG,
                                        highlightthickness=0, bd=0)
        self.keypad_scrollbar = tk.Scrollbar(self.keypad_outer, orient=tk.VERTICAL,
                                              command=self.keypad_canvas.yview)
        self.keypad_frame = tk.Frame(self.keypad_canvas, bg=Palette.BG)

        self.keypad_frame.bind("<Configure>",
            lambda e: self.keypad_canvas.configure(scrollregion=self.keypad_canvas.bbox("all")))
        self.keypad_canvas.create_window((0, 0), window=self.keypad_frame, anchor="nw")
        self.keypad_canvas.configure(yscrollcommand=self.keypad_scrollbar.set)

        self.keypad_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.keypad_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse wheel scrolling (scoped to keypad canvas only)
        self.keypad_canvas.bind("<MouseWheel>",
            lambda e: self.keypad_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # ⑧ Activity Log
        tk.Frame(root, bg=Palette.BORDER, height=1).pack(fill=tk.X, padx=12, pady=(4, 2))
        log_header = tk.Frame(root, bg=Palette.BG)
        log_header.pack(fill=tk.X, padx=12)
        tk.Label(log_header, text="▸ Pipeline Log",
                 font=self._fonts["section"], fg=Palette.TEXT_DIM, bg=Palette.BG,
                 anchor="w").pack(side=tk.LEFT)

        self.log_text = tk.Text(
            root, height=5, bg=Palette.BG_INPUT, fg=Palette.TEXT_DIM,
            font=self._fonts["log"], relief=tk.FLAT, wrap=tk.WORD,
            padx=8, pady=4, state=tk.DISABLED, cursor="arrow",
            insertbackground=Palette.TEXT_DIM
        )
        self.log_text.pack(fill=tk.X, padx=12, pady=(2, 4))

        # ⑨ Demo/Live Toggle
        self.controls_frame = tk.Frame(root, bg=Palette.BG)
        self.controls_frame.pack(fill=tk.X, padx=12, pady=(2, 8))

        self.demo_cb = tk.Checkbutton(
            self.controls_frame, text="Demo Mode (always show keypad)",
            variable=self._demo_mode,
            font=self._fonts["toggle"], fg=Palette.TEXT_DIM, bg=Palette.BG,
            selectcolor=Palette.BG_CARD, activebackground=Palette.BG,
            activeforeground=Palette.TEXT
        )
        self.demo_cb.pack(side=tk.LEFT)

        # ──────────────────────────────────────────────────────────────────
        # Start background threads
        # ──────────────────────────────────────────────────────────────────
        if self.vision:
            threading.Thread(target=self.vision_loop, daemon=True).start()
        else:
            self._vision_status.set("No camera")
            if self._vision_dot:
                self._vision_dot.config(fg=Palette.ERROR)

        self._log("System initialized. Ready.")

    # ══════════════════════════════════════════════════════════════════════
    # Font Management
    # ══════════════════════════════════════════════════════════════════════
    def _create_fonts(self, scale: float):
        """Create/recreate all fonts at the given scale factor."""
        for name, spec in self._base_fonts.items():
            scaled_size = max(7, int(spec["size"] * scale))
            kwargs = {"family": spec["family"], "size": scaled_size}
            if "weight" in spec:
                kwargs["weight"] = spec["weight"]
            if "slant" in spec:
                kwargs["slant"] = spec["slant"]
            self._fonts[name] = tkfont.Font(**kwargs)

    def _rescale_fonts(self, scale: float):
        """Rescale all existing font objects in-place (avoids widget reconfiguration)."""
        for name, spec in self._base_fonts.items():
            scaled_size = max(7, int(spec["size"] * scale))
            self._fonts[name].configure(size=scaled_size)

    # ══════════════════════════════════════════════════════════════════════
    # Adaptive UI System
    # ══════════════════════════════════════════════════════════════════════
    def _compute_adaptation_level(self, state: dict) -> str:
        """Determine adaptation level from vision state."""
        squinting = state.get("squinting", False)
        leaning   = state.get("leaning_forward", False)

        if squinting and leaning:
            return AdaptationLevel.FULL
        elif squinting:
            return AdaptationLevel.VISUAL
        elif leaning:
            return AdaptationLevel.MOTOR
        else:
            return AdaptationLevel.NORMAL

    def _apply_adaptation(self, level: str):
        """Apply full UI adaptation based on the detected level.

        Must be called on the main thread (via root.after).
        """
        if level == self._adaptation_level:
            return  # No change needed

        old_level = self._adaptation_level
        self._adaptation_level = level
        scale = self._FONT_SCALE[level]

        print(f"[Overlay] Adaptation: {old_level} → {level} (scale {scale}x)")

        # --- 1. Rescale all fonts ---
        self._rescale_fonts(scale)

        if level in (AdaptationLevel.VISUAL, AdaptationLevel.FULL):
            # --- HIGH CONTRAST MODE ---
            bg      = Palette.HC_BG
            bg_card = Palette.HC_BTN
            text    = Palette.HC_TEXT
            accent  = Palette.HC_ACCENT
            dim     = Palette.HC_TEXT
            border  = Palette.HC_BORDER
            btn_bg  = Palette.HC_BTN

            self._adapt_var.set("⚡ Adaptation: HIGH CONTRAST + ENLARGED")
            self.adapt_lbl.config(fg=Palette.HC_ACCENT)
        elif level == AdaptationLevel.MOTOR:
            # --- MOTOR ADAPTATION (larger buttons, more spacing, normal colours) ---
            bg      = Palette.BG
            bg_card = Palette.BG_CARD
            text    = Palette.TEXT
            accent  = Palette.ACCENT
            dim     = Palette.TEXT_DIM
            border  = Palette.BORDER
            btn_bg  = Palette.KEYPAD_BTN

            self._adapt_var.set("⚡ Adaptation: ENLARGED + SPACED")
            self.adapt_lbl.config(fg=Palette.WARNING)
        else:
            # --- NORMAL ---
            bg      = Palette.BG
            bg_card = Palette.BG_CARD
            text    = Palette.TEXT
            accent  = Palette.ACCENT
            dim     = Palette.TEXT_DIM
            border  = Palette.BORDER
            btn_bg  = Palette.KEYPAD_BTN

            self._adapt_var.set("Adaptation: Normal")
            self.adapt_lbl.config(fg=Palette.TEXT_DIM)

        # --- 2. Recolour all major containers ---
        for widget in [self.root, self.header_frame, self.adapt_frame,
                       self.transcript_frame, self.desc_frame,
                       self.keypad_header, self.keypad_outer,
                       self.keypad_canvas, self.keypad_frame,
                       self.controls_frame]:
            widget.config(bg=bg)

        self.dash_frame.config(bg=bg_card, highlightbackground=border)

        # --- 3. Recolour labels ---
        self.title_lbl.config(fg=accent, bg=bg)
        self.version_lbl.config(fg=dim, bg=bg)
        self.keypad_title.config(fg=dim, bg=bg)
        self.adapt_lbl.config(bg=bg)

        # Dashboard indicator rows
        for row in self.dash_frame.winfo_children():
            row.config(bg=bg_card)
            for child in row.winfo_children():
                child.config(bg=bg_card)
                if isinstance(child, tk.Label) and child not in [self._voice_dot, self._vision_dot, self._engine_dot]:
                    child.config(fg=text if child.cget("textvariable") else dim)

        # Transcript
        if self._transcript_visible:
            self.transcript_lbl.config(
                fg=accent if level == AdaptationLevel.NORMAL else Palette.HC_TEXT,
                bg=Palette.BG_INPUT if level == AdaptationLevel.NORMAL else Palette.HC_BTN
            )

        # Screen description
        if self._desc_visible:
            desc_fg = Palette.HC_TEXT if level in (AdaptationLevel.VISUAL, AdaptationLevel.FULL) else "#ffeb3b"
            desc_bg = Palette.HC_BG if level in (AdaptationLevel.VISUAL, AdaptationLevel.FULL) else "#111111"
            self.desc_lbl.config(fg=desc_fg, bg=desc_bg)

        # Log
        self.log_text.config(
            bg=Palette.BG_INPUT if level == AdaptationLevel.NORMAL else Palette.HC_BTN,
            fg=dim
        )

        # Checkbutton
        self.demo_cb.config(fg=dim, bg=bg, selectcolor=bg_card, activebackground=bg)

        # Button
        self.btn_listen.config(
            bg=Palette.HC_ACCENT if level in (AdaptationLevel.VISUAL, AdaptationLevel.FULL) else Palette.ACCENT_DIM
        )

        # --- 4. Scale wraplength for labels ---
        wrap_w = int(420 * scale)
        if self._transcript_visible:
            self.transcript_lbl.config(wraplength=wrap_w)
        if self._desc_visible:
            self.desc_lbl.config(wraplength=wrap_w)

        # --- 5. Rebuild keypad with new styles ---
        if self._current_targets:
            self._rebuild_keypad(self._current_targets, self.monitor_info)

    # ══════════════════════════════════════════════════════════════════════
    # Vision Polling Loop — runs on background thread
    # ══════════════════════════════════════════════════════════════════════
    def vision_loop(self):
        while self.running:
            # get_latest_state() has its own internal lock — no outer lock needed
            state = self.vision.get_latest_state()

            if state["face_detected"]:
                sq_text = "Squinting ⚠️" if state["squinting"] else "Normal"
                ln_text = "Leaning ↗️" if state["leaning_forward"] else "Normal"
                status = f"👁 {sq_text} | Posture: {ln_text}"
                dot_color = Palette.WARNING if (state["squinting"] or state["leaning_forward"]) else Palette.SUCCESS
            else:
                status = "No face detected"
                dot_color = Palette.TEXT_DIM

            # Thread-safe Tkinter updates via root.after
            self.root.after(0, self._vision_status.set, status)
            if self._vision_dot:
                self.root.after(0, self._vision_dot.config, {"fg": dot_color})

            # Compute adaptation level with hysteresis to prevent flickering
            new_level = self._compute_adaptation_level(state)
            if new_level == self._pending_level:
                self._pending_count += 1
            else:
                self._pending_level = new_level
                self._pending_count = 1

            # Only apply if stable for enough consecutive readings AND different from current
            if (self._pending_count >= self._HYSTERESIS_THRESHOLD and
                    self._pending_level != self._adaptation_level):
                self.root.after(0, self._apply_adaptation, self._pending_level)

            time.sleep(0.5)

    # ══════════════════════════════════════════════════════════════════════
    # Activity Log
    # ══════════════════════════════════════════════════════════════════════
    def _log(self, message: str):
        """Add a timestamped entry to the pipeline log. Thread-safe."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}\n"

        def _append():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        self.root.after(0, _append)

    # ══════════════════════════════════════════════════════════════════════
    # Status Helpers — thread-safe via root.after
    # ══════════════════════════════════════════════════════════════════════
    def _set_voice_status(self, text: str, color: str = Palette.SUCCESS):
        self.root.after(0, self._voice_status.set, text)
        if self._voice_dot:
            self.root.after(0, self._voice_dot.config, {"fg": color})

    def _set_engine_status(self, text: str, color: str = Palette.SUCCESS):
        self.root.after(0, self._engine_status.set, text)
        if self._engine_dot:
            self.root.after(0, self._engine_dot.config, {"fg": color})

    def _set_transcript(self, text: str):
        def _show():
            self._transcript_var.set(f'🗣  "{text}"')
            if not self._transcript_visible:
                self.transcript_lbl.pack(fill=tk.X, pady=(0, 2))
                self._transcript_visible = True
        self.root.after(0, _show)

    def _set_description(self, text: str):
        def _show():
            self._desc_var.set(text)
            if text and not self._desc_visible:
                self.desc_lbl.pack(fill=tk.X, pady=(0, 2))
                self._desc_visible = True
            elif not text and self._desc_visible:
                self.desc_lbl.pack_forget()
                self._desc_visible = False
        self.root.after(0, _show)

    # ══════════════════════════════════════════════════════════════════════
    # Virtual Keypad — Upgraded with numbers, icons, colours, scrolling
    # ══════════════════════════════════════════════════════════════════════
    def _rebuild_keypad(self, targets: list, monitor_info: dict):
        """Clears and rebuilds the virtual keypad. Must be called via root.after."""
        self._current_targets = targets     # Store for re-rendering on adaptation

        for widget in self.keypad_frame.winfo_children():
            widget.destroy()

        if not targets:
            if not self._demo_mode.get():
                return
            placeholder = tk.Label(
                self.keypad_frame, text="No targets detected yet",
                font=self._fonts["indicator"], fg=Palette.TEXT_DIM, bg=Palette.BG,
                pady=8
            )
            placeholder.pack()
            return

        # Determine styling based on adaptation level
        is_hc = self._adaptation_level in (AdaptationLevel.VISUAL, AdaptationLevel.FULL)
        is_motor = self._adaptation_level in (AdaptationLevel.MOTOR, AdaptationLevel.FULL)

        btn_bg     = Palette.HC_BTN if is_hc else Palette.KEYPAD_BTN
        btn_fg     = Palette.HC_TEXT if is_hc else "white"
        btn_border = Palette.HC_BORDER if is_hc else Palette.BORDER
        btn_height = 3 if is_motor else 2
        btn_pady   = 6 if is_motor else 3

        # Type → icon mapping
        type_icons = {
            "button": "🔘",
            "link":   "🔗",
            "input":  "📝",
            "text":   "📄",
        }

        for idx, t in enumerate(targets, 1):
            btn_name = t.get("name", "Unknown")
            btn_type = t.get("type", "button")
            icon = type_icons.get(btn_type, "🔘")

            # Build display text: ① 🔘 Withdraw Cash
            circled_num = chr(0x245F + idx) if idx <= 20 else str(idx)
            display_text = f" {circled_num}  {icon}  {btn_name}"

            def make_click_handler(target_info, mon):
                def handler():
                    b = target_info.get("box_2d")
                    if b and isinstance(b, list) and len(b) == 4:
                        ymin, xmin, ymax, xmax = b
                        nx = ((xmin + xmax) / 2) / 1000.0
                        ny = ((ymin + ymax) / 2) / 1000.0
                        self._log(f"⚡ Keypad click → '{target_info.get('name')}' ({nx:.3f}, {ny:.3f})")
                        inject_click(nx, ny, mon)
                    else:
                        self._log(f"❌ No coordinates for '{target_info.get('name')}'")
                return handler

            btn = tk.Button(
                self.keypad_frame,
                text=display_text,
                font=self._fonts["keypad"],
                bg=btn_bg, fg=btn_fg,
                activebackground=Palette.ACCENT_DIM if not is_hc else Palette.HC_ACCENT,
                activeforeground="white",
                relief=tk.FLAT,
                height=btn_height,
                anchor="w",
                padx=12,
                cursor="hand2",
                highlightbackground=btn_border,
                highlightthickness=1,
                command=make_click_handler(t, monitor_info)
            )
            btn.pack(fill=tk.X, pady=btn_pady, padx=4)

        # Update keypad title with count
        self.keypad_title.config(text=f"▸ Virtual Accessibility Keypad  ({len(targets)} targets)")

        # Reset scroll position
        self.keypad_canvas.yview_moveto(0)

    # ══════════════════════════════════════════════════════════════════════
    # Main Pipeline — runs on background thread
    # ══════════════════════════════════════════════════════════════════════
    def run_cycle_async(self):
        self.btn_listen.config(state=tk.DISABLED)
        threading.Thread(target=self.run_cycle, daemon=True).start()

    def run_cycle(self):
        self._cycle_had_error = False
        try:
            # --- Step 1: Listen ---
            self._set_voice_status("Listening…", Palette.WARNING)
            self._set_engine_status("Waiting for voice…", Palette.WARNING)
            self._log("🎤 Listening for voice input…")

            user_input, voice_error = self.voice.listen_sync(timeout=7)

            if not user_input:
                error_msg = voice_error or "No speech detected"
                self._set_voice_status(f"⚠ {error_msg}", Palette.WARNING)
                self._set_engine_status("Idle", Palette.SUCCESS)
                self._log(f"⚠ {error_msg}")
                return

            self._set_voice_status("Transcribed ✓", Palette.SUCCESS)
            self._set_transcript(user_input)
            self._log(f"🗣 Heard: \"{user_input}\"")

            # --- Step 2: Capture screen (overlay hides briefly for clean screenshot) ---
            self._set_engine_status("Capturing screen…", Palette.WARNING)
            img, mon = capture_screen(hide_window=self.root)
            self.monitor_info = mon
            self._log(f"📷 Screen captured ({img.size[0]}×{img.size[1]})")

            # --- Step 3: Read vision state ---
            with self._lock:
                state_copy = self.vision.user_state.copy() if self.vision else {}
            sq = state_copy.get("squinting", False)
            ln = state_copy.get("leaning_forward", False)
            self._log(f"👁 User state: squinting={sq}, leaning={ln}")

            # --- Step 4: Call Gemini Vision ---
            self._set_engine_status("Analysing with AI…", Palette.WARNING)
            self._log("🧠 Sending to Gemini Vision…")

            response = analyze_screen_and_intent(img, user_input, state_copy)

            if not response:
                self._cycle_had_error = True
                self._set_engine_status("❌ AI Error", Palette.ERROR)
                self._log("❌ Gemini returned no valid response")
                return

            targets = response.get("targets") or []
            selected = response.get("selected_targets") or []
            self._log(f"🧠 Gemini responded: {len(targets)} targets, {len(selected)} selected")

            # --- Step 5: Speak response ---
            speech = response.get("speech_response", "")
            if speech:
                self.voice.speak(speech)
                self._log(f"🔊 Speaking: \"{speech[:60]}{'…' if len(speech) > 60 else ''}\"")

            # --- Step 6: Update UI ---
            screen_desc = response.get("screen_description", "")

            # Determine if we should show the accessibility panel
            is_impaired = self._demo_mode.get() or sq or ln

            if is_impaired:
                self._set_description(screen_desc)
                self.root.after(0, self._rebuild_keypad, targets, mon)
            else:
                self._set_description("")
                self.root.after(0, self._rebuild_keypad, [], mon)

            # --- Step 7: Execute clicks for selected targets ---
            self._set_engine_status("Executing actions…", Palette.WARNING)
            for target in selected:
                if target and isinstance(target, dict) and target.get("box_2d"):
                    box = target["box_2d"]
                    if isinstance(box, list) and len(box) == 4:
                        ymin, xmin, ymax, xmax = box

                        # --- Coordinate validation ---
                        # Check values are in valid range
                        if not all(0 <= v <= 1000 for v in box):
                            self._log(f"⚠ Invalid coords for '{target.get('name', '?')}': {box} (out of range)")
                            continue

                        # Check box is not inverted or zero-size
                        if ymax <= ymin or xmax <= xmin:
                            self._log(f"⚠ Invalid box for '{target.get('name', '?')}': {box} (inverted/zero)")
                            continue

                        # Check box isn't in taskbar area (bottom 5% of screen)
                        center_y = (ymin + ymax) / 2
                        if center_y > 960:
                            self._log(f"⚠ Skipping '{target.get('name', '?')}': coords ({box}) point to taskbar area")
                            continue

                        nx = ((xmin + xmax) / 2) / 1000.0
                        ny = ((ymin + ymax) / 2) / 1000.0
                        self._log(f"⚡ Click → '{target.get('name', '?')}' at ({nx:.3f}, {ny:.3f})")
                        inject_click(nx, ny, mon)
                        time.sleep(0.4)

            self._set_engine_status("✅ Done", Palette.SUCCESS)

        except Exception as exc:
            self._cycle_had_error = True
            print(f"[Overlay] run_cycle error: {exc}")
            self._set_engine_status(f"❌ {exc}", Palette.ERROR)
            self._log(f"❌ Error: {exc}")
        finally:
            if not self._cycle_had_error:
                self._set_voice_status("Ready", Palette.SUCCESS)
                self._set_engine_status("Idle", Palette.SUCCESS)
            else:
                # Keep error visible for 3 seconds before resetting
                def _delayed_reset():
                    time.sleep(3)
                    self._set_voice_status("Ready", Palette.SUCCESS)
                    self._set_engine_status("Idle", Palette.SUCCESS)
                threading.Thread(target=_delayed_reset, daemon=True).start()

            self.root.after(0, self.btn_listen.config, {"state": tk.NORMAL})
            self._log("── Cycle complete ──")

    # ══════════════════════════════════════════════════════════════════════
    # Shutdown
    # ══════════════════════════════════════════════════════════════════════
    def on_closing(self):
        self.running = False
        if self.vision:
            self.vision.release()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = OverlayApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
