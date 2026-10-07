import ctypes
import sys
import os

_OVERLAY_DIR = os.path.dirname(os.path.abspath(__file__))
if _OVERLAY_DIR not in sys.path:
    sys.path.insert(0, _OVERLAY_DIR)

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
import winsound

from screen_reader import (capture_screen, analyze_screen_and_intent,
                          analyze_follow_up, verify_anchor, analyze_proactive, analyze_dropdown_options,
                          wait_for_stable_screen, get_gemini_client, analyze_agent_step)
from overlay_voice import OverlayVoice
from overlay_vision import OverlayVision
from overlay_adapter import inject_click, inject_text, inject_keys, inject_scroll
from proactive_monitor import ProactiveMonitor
from escalation import EscalationManager, EscalationState


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
        self._base_width = 460
        self._base_height = 650
        # Position at top-right corner of primary monitor
        screen_w = self.root.winfo_screenwidth()
        x_pos = max(0, screen_w - self._base_width - 16)
        self.root.geometry(f"{self._base_width}x{self._base_height}+{x_pos}+30")
        self.root.configure(bg=Palette.BG)
        self.root.minsize(400, 500)

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
        self._last_cycle_time = time.time()

        # --- Escalation Manager ---
        self._escalation = EscalationManager(
            on_state_change=lambda st, ctx: self.root.after(
                0, self._on_escalation_change, st, ctx)
        )

        # Hysteresis: require N consecutive readings before switching adaptation
        self._HYSTERESIS_THRESHOLD = 3  # 3 × 0.5s = 1.5 seconds of stable signal
        self._pending_level = AdaptationLevel.NORMAL
        self._pending_count = 0

        # Adaptation state
        self._last_visual_time = 0.0
        self._last_motor_time = 0.0
        self._last_face_time = time.time()
        self._dock_left = False
        self._is_seated = False
        self._conversation_context = []


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
            self.header_frame, text="⬟  UIAA Overlay",
            font=self._fonts["title"], fg=Palette.ACCENT, bg=Palette.BG, anchor="w"
        )
        self.title_lbl.pack(side=tk.LEFT)
        
        self.dock_btn = tk.Button(
            self.header_frame, text="⇄ Dock", font=self._fonts["indicator"],
            bg=Palette.KEYPAD_BTN, fg=Palette.TEXT_DIM, relief=tk.FLAT,
            command=self._toggle_dock, padx=4, pady=2, cursor="hand2"
        )
        self.dock_btn.pack(side=tk.RIGHT, padx=4)

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

        # Wake word toggle
        self._wake_word_enabled = tk.BooleanVar(value=False)
        self.wake_cb = tk.Checkbutton(
            root, text="Wake Word ('access')", variable=self._wake_word_enabled,
            font=self._fonts["indicator"], bg=Palette.BG, fg=Palette.TEXT_DIM,
            selectcolor=Palette.BG, activebackground=Palette.BG,
            command=self._toggle_wake_word
        )
        self.wake_cb.pack(fill=tk.X, padx=12, pady=(0, 0))
        self._wake_stop_fn = None
        
        # Guide Mode toggle
        self._guide_mode_enabled = tk.BooleanVar(value=False)
        self.guide_cb = tk.Checkbutton(
            root, text="Guide Mode (Narrate pages)", variable=self._guide_mode_enabled,
            font=self._fonts["indicator"], bg=Palette.BG, fg=Palette.TEXT_DIM,
            selectcolor=Palette.BG, activebackground=Palette.BG
        )
        self.guide_cb.pack(fill=tk.X, padx=12, pady=(0, 4))

        # ④ Voice Cycle Button
        self.btn_listen = tk.Button(
            root, text="🎤  Run Voice Cycle",
            font=self._fonts["keypad"],
            bg=Palette.ACCENT_DIM, fg="white", activebackground="#023e8a",
            relief=tk.FLAT, padx=14, pady=7, cursor="hand2",
            command=self.run_cycle_async
        )
        self.btn_listen.pack(fill=tk.X, padx=12, pady=6)

        # ④(b) Agent Loop Text Input & Button
        self.agent_frame = tk.Frame(root, bg=Palette.BG)
        self.agent_frame.pack(fill=tk.X, padx=12, pady=(0, 6))
        
        self.agent_input = tk.Entry(
            self.agent_frame, font=self._fonts["indicator"], 
            bg=Palette.BG_INPUT, fg=Palette.TEXT, insertbackground=Palette.TEXT
        )
        self.agent_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=4)
        
        # Safe focus to help with Windows topmost issues without breaking internal events
        self.agent_input.bind("<Button-1>", lambda e: self.agent_input.focus_set())
        self.agent_input.bind("<Return>", lambda e: self.run_agent_cycle_async())
        
        self.btn_agent = tk.Button(
            self.agent_frame, text="🤖 Run Agent",
            font=self._fonts["keypad"],
            bg="#5e35b1", fg="white", activebackground="#4527a0",
            relief=tk.FLAT, padx=10, pady=4, cursor="hand2",
            command=self.run_agent_cycle_async
        )
        self.btn_agent.pack(side=tk.RIGHT)


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

        # Scrollable keypad container — fixed max height so it doesn't push log off
        self.keypad_outer = tk.Frame(root, bg=Palette.BG, height=160)
        self.keypad_outer.pack(fill=tk.X, padx=12, pady=2)
        self.keypad_outer.pack_propagate(False)  # enforce fixed height

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
            root, height=8, bg=Palette.BG_INPUT, fg=Palette.TEXT_DIM,
            font=self._fonts["log"], relief=tk.FLAT, wrap=tk.WORD,
            padx=8, pady=4, state=tk.DISABLED, cursor="arrow",
            insertbackground=Palette.TEXT_DIM
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(2, 4))

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

        # ⑩ Escalation Banner (hidden by default)
        self.escalation_frame = tk.Frame(root, bg="#ff1744")
        self._escalation_var = tk.StringVar(value="")
        self.escalation_lbl = tk.Label(
            self.escalation_frame, textvariable=self._escalation_var,
            font=self._fonts["desc"], fg="white", bg="#ff1744",
            wraplength=420, justify=tk.LEFT, padx=12, pady=10
        )
        self.escalation_lbl.pack(fill=tk.X)
        self._escalation_visible = False

        # ⑪ Sensitive Data On-Screen Display (hidden by default)
        self._sensitive_frame = tk.Frame(root, bg="#1a237e")
        self._sensitive_var = tk.StringVar(value="")
        self._sensitive_lbl = tk.Label(
            self._sensitive_frame, textvariable=self._sensitive_var,
            font=self._fonts["desc"], fg="#e8eaf6", bg="#1a237e",
            wraplength=420, justify=tk.LEFT, padx=12, pady=8
        )
        self._sensitive_lbl.pack(fill=tk.X)
        self._sensitive_visible = False

        # ──────────────────────────────────────────────────────────────────
        # Start background threads
        # ──────────────────────────────────────────────────────────────────
        if self.vision:
            threading.Thread(target=self.vision_loop, daemon=True).start()
        else:
            self._vision_status.set("No camera")
            if self._vision_dot:
                self._vision_dot.config(fg=Palette.ERROR)

        # Start Proactive Monitor
        self._proactive = ProactiveMonitor(
            get_state_fn=lambda: (self.vision.get_latest_state()
                                  if self.vision else {}),
            trigger_fn=self._run_proactive_check,
            inactivity_threshold=30,
            frustration_threshold=10,
            cooldown=60,
        )
        self._proactive.start()

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

    def _toggle_dock(self):
        self._dock_left = not self._dock_left
        self._update_window_geometry()

    def _update_window_geometry(self):
        scale = self._FONT_SCALE[self._adaptation_level]
        new_w = int(self._base_width * scale)
        new_h = int(self._base_height * scale)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        # X Position: dock left vs right
        if self._dock_left:
            x_pos = 16
        else:
            x_pos = max(0, screen_w - new_w - 16)
            
        # Y Position: seated (wheelchair reachability) vs standing
        if self._is_seated:
            y_pos = max(30, screen_h - new_h - 40)
        else:
            y_pos = 30
            
        self.root.geometry(f"{new_w}x{new_h}+{x_pos}+{y_pos}")

    def _apply_adaptation(self, level: str):
        """Apply full UI adaptation based on the detected level.

        Must be called on the main thread (via root.after).
        """
        if level == self._adaptation_level:
            return  # No change needed

        old_level = self._adaptation_level
        self._adaptation_level = level
        scale = self._FONT_SCALE[level]

        print(f"[Overlay] Adaptation: {old_level} -> {level} (scale {scale}x)")

        # --- 0. Dynamic window resize (fluid container) --- 
        self._update_window_geometry()

        # --- 1. Rescale all fonts ---
        self._rescale_fonts(scale)

        if level in (AdaptationLevel.VISUAL, AdaptationLevel.FULL):
            # --- HIGH CONTRAST MODE (Yellow on Black) ---
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
        if hasattr(self, 'dock_btn'):
            self.dock_btn.config(fg=text, bg=btn_bg)
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
                self._last_face_time = time.time()
                if state.get("is_calibrating"):
                    status = "Calibrating..."
                    dot_color = Palette.WARNING
                    self.root.after(0, self._set_description, "Calibrating camera... Please look straight at the screen.")
                else:
                    if state.get("standing_above_frame"):
                        stance_text = "🧍 Standing (Head Above Frame)"
                    elif state.get("seated"):
                        stance_text = "🪑 Sitting"
                    else:
                        stance_text = "🧍 Standing"
                    
                    if state.get("looking_down"):
                        pitch_text = "👇 Down"
                    elif state.get("looking_up"):
                        pitch_text = "👆 Up"
                    else:
                        pitch_text = "Straight"

                    sq_text = "Squinting ⚠️" if state.get("squinting") else "Eyes OK"
                    ln_text = "Leaning ↗️" if state.get("leaning_forward") else "Upright"

                    status = f"{stance_text} | {pitch_text} | {sq_text} | {ln_text}"
                    dot_color = Palette.WARNING if (state.get("squinting") or state.get("leaning_forward")) else Palette.SUCCESS
                    
                    # Clear calibration text if it was showing
                    if self._desc_var.get().startswith("Calibrating"):
                        self.root.after(0, self._set_description, "")
            else:
                status = "No face detected"
                dot_color = Palette.TEXT_DIM
                
                # Session Timer / Kiosk Auto-Reset
                if time.time() - self._last_face_time > 60.0:
                    self.root.after(0, self._reset_kiosk_session)
                    self._last_face_time = time.time() # prevent repeated calls


            # Handle seated transition for wheelchair ergonomics
            was_seated = self._is_seated
            self._is_seated = state.get("seated", False)
            if was_seated != self._is_seated:
                self.root.after(0, self._update_window_geometry)

            # Thread-safe Tkinter updates via root.after
            self.root.after(0, self._vision_status.set, status)
            if self._vision_dot:
                self.root.after(0, self._vision_dot.config, {"fg": dot_color})

            # Decoupled sticky timers: visual (20s hold) and motor (10s hold)
            now = time.time()
            is_calib = state.get("is_calibrating", False)
            if is_calib:
                # Do NOT trigger or accumulate adaptations while camera is calibrating
                self._last_visual_time = 0.0
                self._last_motor_time = 0.0
                self._pending_level = AdaptationLevel.NORMAL
                self._pending_count = 0
                new_level = AdaptationLevel.NORMAL
            else:
                if state.get("squinting"):
                    self._last_visual_time = now
                if state.get("leaning_forward"):
                    self._last_motor_time = now

                visual_active = (now - self._last_visual_time < 20.0)
                motor_active  = (now - self._last_motor_time < 10.0)

                if visual_active and motor_active:
                    new_level = AdaptationLevel.FULL
                elif visual_active:
                    new_level = AdaptationLevel.VISUAL
                elif motor_active:
                    new_level = AdaptationLevel.MOTOR
                else:
                    new_level = AdaptationLevel.NORMAL

            if new_level == self._pending_level:
                self._pending_count += 1
            else:
                self._pending_level = new_level
                self._pending_count = 1

            # Require 2 consecutive frames (1.0s) to activate elevated mode (eliminates twitchy 1-frame triggers)
            # Require 3 consecutive frames (1.5s) to decay back to NORMAL
            req_count = 2 if self._pending_level != AdaptationLevel.NORMAL else self._HYSTERESIS_THRESHOLD
            if (self._pending_count >= req_count and
                    self._pending_level != self._adaptation_level):
                self.root.after(0, self._apply_adaptation, self._pending_level)

            time.sleep(0.5)

    def _play_success_sound(self):
        def _sound():
            try:
                winsound.Beep(880, 100)
                time.sleep(0.05)
                winsound.Beep(1046, 150)
            except:
                pass
        threading.Thread(target=_sound, daemon=True).start()

    def _play_error_sound(self):
        def _sound():
            try:
                winsound.Beep(440, 250)
                time.sleep(0.05)
                winsound.Beep(330, 300)
            except:
                pass
        threading.Thread(target=_sound, daemon=True).start()

    def _reset_kiosk_session(self):
        self._conversation_context.clear()
        self._set_transcript("")
        self._transcript_visible = False
        self.transcript_frame.pack_forget()
        self._set_description("Session reset due to inactivity. Welcome back.")
        self._log("🔄 Kiosk auto-reset (60s inactivity).")
        # Ensure adaptation resets
        self._last_visual_time = 0.0
        self._last_motor_time = 0.0
        self._pending_level = AdaptationLevel.NORMAL
        self._pending_count = 0
        self._escalation.reset()
        self._apply_adaptation(AdaptationLevel.NORMAL)

    def _start_ai_pulse(self):
        self._ai_pulsing = True
        self._pulse_state = False
        self._pulse_ai_dot()

    def _stop_ai_pulse(self):
        self._ai_pulsing = False
        if self._engine_dot:
            self.root.after(0, self._engine_dot.config, {"fg": Palette.SUCCESS})

    def _pulse_ai_dot(self):
        if not self._ai_pulsing or not self._engine_dot:
            return
        
        self._pulse_state = not self._pulse_state
        color = Palette.WARNING if self._pulse_state else Palette.TEXT_DIM
        self._engine_dot.config(fg=color)
        
        dots = "." * (1 + (int(time.time() * 3) % 3))
        self._engine_status.set(f"Analysing with AI{dots}")
        
        self.root.after(333, self._pulse_ai_dot)

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

    def _show_sensitive_on_screen(self, text: str):
        """Display sensitive data visually (no TTS) with auto-hide."""
        def _show():
            self._sensitive_var.set(f"🔒 {text}")
            if not self._sensitive_visible:
                self._sensitive_frame.pack(fill=tk.X, padx=12, pady=2)
                self._sensitive_visible = True
            # Auto-hide after 8 seconds
            self.root.after(8000, self._hide_sensitive)
        self.root.after(0, _show)

    def _hide_sensitive(self):
        if self._sensitive_visible:
            self._sensitive_frame.pack_forget()
            self._sensitive_visible = False
            self._sensitive_var.set("")

    def _on_escalation_change(self, new_state: EscalationState, ctx: dict):
        """Handle escalation state transitions — update UI."""
        if new_state == EscalationState.ESCALATING:
            self._escalation_var.set(
                "⚠ I'm having trouble helping. Connecting to a human assistant…")
            if not self._escalation_visible:
                self.escalation_frame.pack(fill=tk.X, padx=12, pady=4)
                self._escalation_visible = True
            self.voice.speak(
                "I'm having trouble with your request. "
                "Let me connect you with a human assistant.")
            self._log(f"🚨 ESCALATION triggered ({ctx.get('failures', 0)} failures)")
            # Simulate human connection after 5 seconds
            self.root.after(5000, self._simulate_human_connect)
        elif new_state == EscalationState.CONNECTED:
            self._escalation_var.set(
                "✅ Human assistant connected. You can describe your issue.")
            self._log("✅ Human agent connected (simulated)")
        elif new_state == EscalationState.NORMAL:
            if self._escalation_visible:
                self.escalation_frame.pack_forget()
                self._escalation_visible = False
            self._log("Escalation reset — AI recovered.")

    def _simulate_human_connect(self):
        self._escalation.simulate_human_connected()

    def _run_proactive_check(self, reason: str):
        """Called by ProactiveMonitor when the user appears stuck."""
        self._log(f"🤖 Proactive trigger: {reason}")
        self._set_engine_status("Proactive check…", Palette.WARNING)

        def _do_check():
            try:
                img, mon = capture_screen(hide_window=None)
                result = analyze_proactive(img, reason)
                if result:
                    speech = result.get("speech_response", "")
                    desc = result.get("screen_description", "")
                    if speech:
                        sensitive = result.get("is_sensitive", False)
                        spoken = self.voice.speak(speech, sensitive=sensitive)
                        if not spoken:
                            self._show_sensitive_on_screen(speech)
                    if desc:
                        self._set_description(desc)
                    self._log(f"🤖 Proactive: \"{speech[:60]}\"")
                self._set_engine_status("Idle", Palette.SUCCESS)
            except Exception as e:
                print(f"[Overlay] Proactive check error: {e}")
                self._set_engine_status("Idle", Palette.SUCCESS)

        threading.Thread(target=_do_check, daemon=True).start()

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

            circled_num = chr(0x245F + idx) if idx <= 20 else str(idx)
            display_text = f"{circled_num} {icon}\n{btn_name}"

            def make_click_handler(target_info, mon):
                def handler():
                    b = target_info.get("box_2d")
                    if b and isinstance(b, list) and len(b) == 4:
                        ymin, xmin, ymax, xmax = b
                        nx = ((xmin + xmax) / 2) / 1000.0
                        ny = ((ymin + ymax) / 2) / 1000.0
                        self._log(f"Keypad click -> '{target_info.get('name')}' ({nx:.3f}, {ny:.3f})")
                        inject_click(nx, ny, mon, self.root)
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
                anchor="center",
                justify="center",
                padx=8, pady=btn_pady,
                cursor="hand2",
                highlightbackground=btn_border,
                highlightthickness=1,
                command=make_click_handler(t, monitor_info)
            )
            
            # Grid layout: 2 columns
            row = (idx - 1) // 2
            col = (idx - 1) % 2
            btn.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)

        # Make columns equal width
        self.keypad_frame.grid_columnconfigure(0, weight=1, uniform="col")
        self.keypad_frame.grid_columnconfigure(1, weight=1, uniform="col")

        # Update keypad title with count
        self.keypad_title.config(text=f"▸ Virtual Accessibility Keypad  ({len(targets)} targets)")

        # Reset scroll position
        self.keypad_canvas.yview_moveto(0)

    def _toggle_wake_word(self):
        if self._wake_word_enabled.get():
            self._log("🎙️ Wake word enabled (Listening for 'access')")
            self._wake_stop_fn = self.voice.listen_continuous("access", self._on_wake_word)
        else:
            if self._wake_stop_fn:
                self._log("🎙️ Wake word disabled")
                self._wake_stop_fn(wait_for_stop=False)
                self._wake_stop_fn = None

    def _on_wake_word(self, clean_text):
        if self.btn_listen.cget("state") != tk.DISABLED:
            self.run_cycle_async(pre_transcribed_text=clean_text)

    def _listen_for_reply(self, timeout: int = 8) -> tuple[str, str]:
        """Reliably listens for a user reply.
        
        Pauses wake word listener, waits for TTS to fully finish,
        gives the audio hardware a moment to settle, then listens.
        Returns a tuple of (transcript_string, error_message).
        """
        # 1. Pause wake word listener so it doesn't steal the mic
        wake_was_enabled = self._wake_word_enabled.get()
        if wake_was_enabled and self._wake_stop_fn:
            self._log("⏸ Pausing wake word listener for reply...")
            self._wake_stop_fn(wait_for_stop=False)
            self._wake_stop_fn = None

        try:
            # 2. Busy-wait until TTS is truly done (belt + suspenders)
            wait_start = time.time()
            while self.voice._is_speaking and (time.time() - wait_start) < 10:
                time.sleep(0.1)

            # 3. Let audio hardware fully release (pyttsx3 SAPI5 holds output briefly)
            time.sleep(0.5)

            # 4. Listen
            self._set_engine_status("🎙 Listening…", Palette.WARNING)
            self._log("🎙 Mic ON — waiting for your reply...")
            reply, err = self.voice.listen_sync(timeout=timeout)
            if reply:
                self._log(f"🎙 Heard: '{reply}'")
            else:
                self._log(f"🎙 No reply captured ({err})")
            return reply, err

        finally:
            # 5. Restart wake word listener if it was on
            if wake_was_enabled:
                self._log("▶ Resuming wake word listener")
                self._wake_stop_fn = self.voice.listen_continuous("access", self._on_wake_word)

    # ══════════════════════════════════════════════════════════════════════
    # Main Pipeline — runs on background thread
    # ══════════════════════════════════════════════════════════════════════
    def run_cycle_async(self, pre_transcribed_text: str = None):
        """Dispatches the vision/voice cycle to a background thread."""
        self.root.after(0, self.btn_listen.config, {"state": tk.DISABLED})
        threading.Thread(target=self.run_cycle, args=(pre_transcribed_text,), daemon=True).start()

    def run_cycle(self, pre_transcribed_text: str = None):
        self._cycle_had_error = False
        self._last_cycle_time = time.time()
        if hasattr(self, '_proactive'):
            self._proactive.record_cycle()
        try:
            # --- Step 1: Voice Input ---
            self.root.after(0, self.btn_listen.config, {"state": tk.DISABLED})
            
            if pre_transcribed_text:
                self._log(f"🎤 Wake word triggered! Pre-transcribed: {pre_transcribed_text}")
                user_input = pre_transcribed_text
                if not user_input.strip():
                    user_input = "Please help me with this screen." # fallback if they just said "access"
            else:
                self._set_voice_status("Listening…", Palette.WARNING)
                self._log("🎤 Listening for voice input…")

                user_input, voice_error = self._listen_for_reply(timeout=7)

                if not user_input:
                    error_msg = voice_error or "No speech detected"
                    self._set_voice_status(f"⚠ {error_msg}", Palette.WARNING)
                    self._set_engine_status("Idle", Palette.SUCCESS)
                    self._log(f"⚠ {error_msg}")
                    self._play_error_sound()
                    return

            self._set_voice_status("Transcribed ✓", Palette.SUCCESS)
            self._set_transcript(user_input)
            self._log(f"🗣 Heard: \"{user_input}\"")

            # --- Step 2: Capture screen (overlay hides briefly for clean screenshot) ---
            self._set_engine_status("Capturing screen…", Palette.WARNING)
            
            # Wait passively for page animations to finish without blinking overlay
            wait_for_stable_screen(timeout=2.5, interval=0.25)
            
            # Take clean screenshot with single brief overlay hide
            img, mon = capture_screen(hide_window=self.root)
            self.monitor_info = mon
            self._log(f"📷 Screen captured ({img.size[0]}×{img.size[1]})")

            # --- Step 3: Read vision state ---
            with self._lock:
                state_copy = self.vision.user_state.copy() if self.vision else {}
            st = "sitting" if state_copy.get("seated") else "standing"
            pt = "down" if state_copy.get("looking_down") else ("up" if state_copy.get("looking_up") else "straight")
            sq = state_copy.get("squinting", False)
            ln = state_copy.get("leaning_forward", False)
            self._log(f"👁 User state: {st}, pitch={pt}, squinting={sq}, leaning={ln}")

            # --- Step 4: Call Gemini Vision ---
            self._set_engine_status("Analysing with AI…", Palette.WARNING)
            self._start_ai_pulse()
            self._log("🧠 Sending to Gemini Vision…")

            response = analyze_screen_and_intent(img, user_input, state_copy, self._conversation_context)
            
            self._stop_ai_pulse()

            if not response:
                self._cycle_had_error = True
                if get_gemini_client() is None:
                    err_msg = "API Key Missing"
                    detail = "Please set GEMINI_API_KEY in overlay/.env"
                else:
                    err_msg = "AI Error"
                    detail = "Gemini returned no valid response"
                self._set_engine_status(f"❌ {err_msg}", Palette.ERROR)
                self._log(f"❌ {detail}")
                return

            targets = response.get("targets") or []
            selected = response.get("selected_targets") or []
            self._log(f"🧠 Gemini responded: {len(targets)} targets, {len(selected)} selected")

            # --- Step 5: Speak response (with privacy gate) ---
            speech = response.get("speech_response", "")
            is_sensitive = response.get("is_sensitive", False)
            expects_reply = response.get("expects_response", False)
            if speech:
                spoken = self.voice.speak(speech, sensitive=is_sensitive, block=expects_reply)
                if not spoken:
                    # Sensitive data suppressed — show on screen instead
                    self._show_sensitive_on_screen(speech)
                    self._log(f"🔒 Sensitive (screen only): \"{speech[:60]}\"")
                else:
                    self._log(f"🔊 Speaking: \"{speech[:60]}{'…' if len(speech) > 60 else ''}\"")
            # --- Step 6: Update UI ---
            screen_desc = response.get("screen_description", "")
            
            pending = response.get("pending_fields") or []
            if pending:
                self._log(f"📋 Pending fields: {pending}")
                self._conversation_context.append(
                    f"System paused: missing fields {pending}. Waiting for user input."
                )

            visible_results = response.get("visible_results") or []
            has_more = response.get("has_more_results", False)

            # Determine if we should show the accessibility panel
            is_impaired = self._demo_mode.get() or sq or ln

            if is_impaired:
                self._set_description(screen_desc)
                display_targets = visible_results if visible_results else targets
                self.root.after(0, self._rebuild_keypad, display_targets, mon)
            else:
                self._set_description("")
                self.root.after(0, self._rebuild_keypad, [], mon)

            if visible_results and not selected:
                summary_parts = [f"I can see {len(visible_results)} results."]
                for i, r in enumerate(visible_results, 1):
                    summary_parts.append(f"Option {i}: {r.get('label', '')}.")
                if has_more:
                    summary_parts.append("There are more results below. Say 'scroll down' to see them.")
                self.voice.speak(" ".join(summary_parts))
                self._log(f"📊 Summarized {len(visible_results)} results (more={has_more})")

            # --- CAPTCHA CHECK ---
            if response.get("captcha_detected"):
                self._set_engine_status("⚠ CAPTCHA detected", Palette.WARNING)
                self._log("⚠ Halted for manual CAPTCHA completion.")
                return

            # --- Step 7: Execute clicks for selected targets ---
            self._set_engine_status("Executing actions…", Palette.WARNING)
            for target in selected:
                if target and isinstance(target, dict):
                    box = target.get("box_2d")
                    has_box = isinstance(box, list) and len(box) == 4
                    has_scroll = bool(target.get("scroll_direction"))
                    has_keys = bool(target.get("press_keys"))
                    
                    if not (has_box or has_scroll or has_keys):
                        continue

                    if target.get("requires_confirmation"):
                        self._log(f"🛡️ Confirmation required for '{target.get('name', '?')}'")
                        self.voice.speak(f"Please confirm: {target.get('name', '?')}. Say yes to confirm.", block=True)
                        conf_ans, _ = self._listen_for_reply(timeout=8)
                        if "yes" not in (conf_ans or "").lower():
                            self._log(f"❌ Action cancelled by user (heard: '{conf_ans}')")
                            self.voice.speak("Action cancelled.", block=True)
                            continue
                        self._log("✅ Action confirmed by user.")

                    # --- Handle Scroll Direction ---
                    scroll_dir = target.get("scroll_direction")
                    if scroll_dir in ["down", "up"]:
                        self._log(f"Scrolling {scroll_dir.upper()} for target '{target.get('name', '?')}'")
                        # Click center of screen to ensure browser has focus (not the overlay)
                        inject_click(0.5, 0.5, mon, self.root)
                        time.sleep(0.3)
                        inject_scroll(scroll_dir)
                        time.sleep(1.0)
                        # If we have a box to click, we need a new screenshot to verify anchor
                        if has_box:
                            pass # Anchor verification below will find new coords

                    if has_box:
                        try:
                            box = [float(v) for v in box]
                            ymin, xmin, ymax, xmax = box
                        except (ValueError, TypeError):
                            self._log(f"⚠ Invalid coords type for '{target.get('name', '?')}': {box}")
                            has_box = False

                    if has_box:
                        # --- Coordinate validation ---
                        if not all(0 <= v <= 1000 for v in box):
                            self._log(f"⚠ Invalid coords for '{target.get('name', '?')}': {box} (out of range)")
                            has_box = False
                        elif ymax <= ymin or xmax <= xmin:
                            self._log(f"⚠ Invalid box for '{target.get('name', '?')}': {box} (inverted/zero)")
                            has_box = False
                        else:
                            center_y = (ymin + ymax) / 2
                            if center_y > 960:
                                self._log(f"⚠ Skipping '{target.get('name', '?')}': coords ({box}) point to taskbar area")
                                has_box = False

                    if has_box:
                        # --- Visual Anchor Verification ---
                        verified_box = verify_anchor(
                            target.get('name', ''),
                            box, mon, hide_window=None
                        )
                        if verified_box is None:
                            self._log(f"⚠ Anchor lost for '{target.get('name', '?')}' — skipping click")
                            has_box = False
                        else:
                            if verified_box != box:
                                self._log(f"🔄 Anchor shifted for '{target.get('name', '?')}': {box} → {verified_box}")
                                box = verified_box
                                ymin, xmin, ymax, xmax = [float(v) for v in box]

                            nx = ((xmin + xmax) / 2) / 1000.0
                            ny = ((ymin + ymax) / 2) / 1000.0
                            self._log(f"Click -> '{target.get('name', '?')}' at ({nx:.3f}, {ny:.3f})")
                            inject_click(nx, ny, mon, self.root)
                            time.sleep(0.3)

                            type_text = target.get("type_text")
                            if type_text and isinstance(type_text, str):
                                self._log(f"Typing -> '{type_text}'")
                                inject_keys(["ctrl+a", "backspace"])
                                time.sleep(0.2)
                                inject_text(type_text)
                                time.sleep(0.3)

                    keys_to_press = target.get("press_keys")
                    if keys_to_press and isinstance(keys_to_press, list):
                        self._log(f"Keys -> {keys_to_press}")
                        inject_keys(keys_to_press)
                        time.sleep(0.3)

                    # If Gemini says a follow-up is needed (e.g. dropdown opened,
                    # need to take a new screenshot to find the right option)
                    follow_up = target.get("follow_up")
                    if follow_up and isinstance(follow_up, str):
                        self._log(f"Follow-up: {follow_up}")
                        self._set_engine_status("Re-scanning dropdown...", Palette.WARNING)

                        # Wait for dropdown animation to complete
                        time.sleep(2.5)

                        # Take a new screenshot (do not hide overlay to prevent stealing focus and closing the dropdown)
                        img2, mon2 = capture_screen(hide_window=None)
                        self._log(f"Second screenshot captured ({img2.size[0]}x{img2.size[1]})")

                        # Decide if this is a dropdown options list or just a generic follow-up
                        if any(k in follow_up.lower() for k in ["autocomplete", "suggestion", "station", "city"]):
                            fu_result = analyze_dropdown_options(img2, follow_up, user_input)
                            if fu_result and fu_result.get("options"):
                                options = fu_result["options"]
                                best_match = fu_result.get("best_match")
                                
                                if len(options) == 1:
                                    target_to_click_str = options[0]
                                elif best_match:
                                    target_to_click_str = best_match
                                    self._log(f"Matched best option: {best_match}")
                                else:
                                    # Ambiguous! Ask user.
                                    option_names = options[:3]
                                    ask_text = f"I see {', '.join(option_names)}. Which one?"
                                    self.voice.speak(ask_text, block=True)
                                    self._log(ask_text)
                                    user_choice, _ = self._listen_for_reply(timeout=8)
                                    
                                    target_to_click_str = None
                                    if user_choice:
                                        user_choice_lower = user_choice.lower()
                                        for opt in options:
                                            if opt.lower() in user_choice_lower or user_choice_lower in opt.lower():
                                                target_to_click_str = opt
                                                break
                                    if not target_to_click_str:
                                        target_to_click_str = options[0]
                                        
                                self._log(f"Resolving coordinates for: {target_to_click_str}")
                                fu_result = analyze_follow_up(img2, f"Click on the option '{target_to_click_str}'")
                                if fu_result:
                                    fu_box = fu_result.get("box_2d")
                                    fu_name = fu_result.get("name", target_to_click_str)
                                else:
                                    fu_box = None
                                    fu_name = target_to_click_str
                            else:
                                fu_box = None
                                fu_name = "?"
                        else:
                            # Standard single-target follow-up
                            fu_result = analyze_follow_up(img2, follow_up)
                            if fu_result:
                                fu_box = fu_result.get("box_2d")
                                fu_name = fu_result.get("name", "?")
                            else:
                                fu_box = None
                                fu_name = "?"

                        if fu_box and isinstance(fu_box, list) and len(fu_box) == 4:
                            try:
                                fy1, fx1, fy2, fx2 = [float(v) for v in fu_box]
                                fu_nx = ((fx1 + fx2) / 2) / 1000.0
                                fu_ny = ((fy1 + fy2) / 2) / 1000.0
                                self._log(f"Follow-up click -> '{fu_name}' at ({fu_nx:.3f}, {fu_ny:.3f})")
                                inject_click(fu_nx, fu_ny, mon2, overlay_window=self.root)
                                time.sleep(0.3)
                            except ValueError:
                                self._log("Follow-up: invalid coordinates returned")
                        else:
                            self._log("Follow-up: option not found in dropdown")

            # --- Page Guidance Narration ---
            page_guidance = response.get("page_guidance")
            if page_guidance and selected and self._guide_mode_enabled.get():
                time.sleep(1.5)
                wait_for_stable_screen(timeout=3.0, interval=0.3)
                self._log(f"📖 Page guidance: {page_guidance}")
                self.voice.speak(page_guidance)

            self._set_engine_status("Done", Palette.SUCCESS)
            self._play_success_sound()
            
            # --- Conversational Turn ---
            if response.get("expects_response"):
                self._log("🔄 Conversational turn — waiting for reply...")
                user_reply, _ = self._listen_for_reply(timeout=8)
                if user_reply:
                    self._log(f"Received reply: '{user_reply}'")
                    self.root.after(0, self.run_cycle_async, user_reply)
            # Maintain rolling conversation memory (last 5 cycles)
            action_desc = f"User said: '{user_input}'"
            if selected:
                action_desc += f" -> System acted on {len(selected)} target(s)."
            self._conversation_context.append(action_desc)
            if len(self._conversation_context) > 5:
                self._conversation_context.pop(0)

            # Record success for escalation tracking
            self._escalation.record_success()

        except Exception as exc:
            self._cycle_had_error = True
            print(f"[Overlay] run_cycle error: {exc}")
            self._set_engine_status(f"❌ {exc}", Palette.ERROR)
            self._log(f"❌ Error: {exc}")
            self._play_error_sound()
            # Record failure for escalation tracking
            self._escalation.record_failure(str(exc))
        finally:
            self._is_processing = False
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
    # Stateful Agent Loop (Phase 1 Upgrade)
    # ══════════════════════════════════════════════════════════════════════
    def run_agent_cycle_async(self):
        """Dispatches the stateful agent loop to a background thread."""
        self.root.after(0, self.btn_agent.config, {"state": tk.DISABLED})
        self.root.after(0, self.btn_listen.config, {"state": tk.DISABLED})
        threading.Thread(target=self.run_agent_cycle, daemon=True).start()

    def run_agent_cycle(self):
        self._cycle_had_error = False
        self._last_cycle_time = time.time()
        if hasattr(self, '_proactive'):
            self._proactive.record_cycle()
            
        typed_goal = self.agent_input.get().strip()
        if typed_goal:
            user_goal = typed_goal
            self.agent_input.delete(0, tk.END)
            self._log(f"📝 Text input used: {user_goal}")
            self._set_voice_status("Text Input ✓", Palette.SUCCESS)
        else:
            self._set_voice_status("Listening…", Palette.WARNING)
            user_goal, err = self._listen_for_reply(timeout=10)
            
            if not user_goal:
                error_msg = err or "No speech detected"
                self._set_voice_status(f"⚠ {error_msg}", Palette.WARNING)
                self._set_engine_status("Idle", Palette.SUCCESS)
                self._log(f"⚠ Agent Loop aborted: {error_msg}")
                self._play_error_sound()
                self.root.after(0, self.btn_agent.config, {"state": tk.NORMAL})
                self.root.after(0, self.btn_listen.config, {"state": tk.NORMAL})
                return
            
            self._set_voice_status("Transcribed ✓", Palette.SUCCESS)
            
        self._set_transcript(f"Goal: {user_goal}")
        self._log(f"🤖 Starting Agent Loop for Goal: '{user_goal}'")
        self.voice.speak(f"Okay, working on: {user_goal}")
        
        history = []
        max_steps = 30
        step = 0
        
        while step < max_steps:
            step += 1
            if hasattr(self, '_proactive'):
                self._proactive.record_cycle()
                
            self._log(f"--- Agent Step {step} ---")
            self._set_engine_status(f"Step {step}: Capturing…", Palette.WARNING)
            
            wait_for_stable_screen(timeout=2.0, interval=0.25)
            screenshot, monitor_info = capture_screen(hide_window=self.root)
            
            self._set_engine_status(f"Step {step}: Analysing…", Palette.WARNING)
            action_data = analyze_agent_step(screenshot, user_goal, history)
            
            if not action_data:
                self._log("Agent failed to respond. Aborting loop.")
                self.voice.speak("I encountered an error planning the next step.")
                break
                
            action_type = action_data.get("action_type")
            thought = action_data.get("thought_process")
            speech = action_data.get("speech_to_user")
            
            self._log(f"🤔 Thought: {thought}")
            if speech:
                self.voice.speak(speech)
                
            if action_type == "DONE":
                self._log("✅ Goal Achieved!")
                self._play_success_sound()
                break
            elif action_type == "ERROR":
                self._log(f"❌ Agent Error: {action_data.get('error_reason')}")
                self._play_error_sound()
                break
            elif action_type in ["ASK_USER", "READ_OPTIONS"]:
                if action_type == "READ_OPTIONS":
                    self._log(f"📖 Agent reading options: {speech}")
                else:
                    self._log(f"❓ Agent asked: {speech}")
                
                # Thread-safe dialog using an Event
                ans_container = []
                ev = threading.Event()
                def _ask():
                    # Custom dialog to guarantee it appears on top and doesn't freeze invisibly
                    dlg = tk.Toplevel(self.root)
                    dlg.title("Agent Needs Info")
                    dlg.attributes("-topmost", True)
                    # Auto-size height based on text length by omitting the height parameter
                    dlg.geometry(f"300x250+{self.root.winfo_x() - 50}+{self.root.winfo_y() + 100}")
                    dlg.configure(bg=Palette.BG_CARD)
                    
                    tk.Label(dlg, text=speech, font=self._fonts["status"], bg=Palette.BG_CARD, fg=Palette.TEXT, wraplength=280).pack(pady=10)
                    ans_entry = tk.Entry(dlg, font=self._fonts["indicator"], bg=Palette.BG_INPUT, fg=Palette.TEXT, insertbackground=Palette.TEXT)
                    ans_entry.pack(fill=tk.X, padx=15, pady=5)
                    ans_entry.focus_set()
                    
                    def _on_submit(*args):
                        ans_container.append(ans_entry.get().strip())
                        dlg.destroy()
                        ev.set()
                        
                    ans_entry.bind("<Return>", _on_submit)
                    tk.Button(dlg, text="Submit", command=_on_submit, bg=Palette.ACCENT_DIM, fg="white", relief=tk.FLAT).pack(pady=10)
                    
                    # If user closes window with X
                    def _on_close():
                        ans_container.append(None)
                        dlg.destroy()
                        ev.set()
                    dlg.protocol("WM_DELETE_WINDOW", _on_close)

                self.root.after(0, _ask)
                ev.wait()
                
                user_reply = ans_container[0] if ans_container else None
                if user_reply:
                    user_goal = f"{user_goal}. [User clarified: {user_reply}]"
                    self._log(f"📝 Goal updated to: {user_goal}")
                    self._set_transcript(f"Goal: {user_goal}")
                    history.append(f"Turn {step}: Asked user '{speech}', user replied '{user_reply}'")
                else:
                    self._log("❌ User cancelled the clarification dialog. Aborting loop.")
                    break
                continue # Restart loop with new goal
                
            self._set_engine_status(f"Step {step}: Executing {action_type}…", Palette.WARNING)
            
            box = action_data.get("target_box_2d")
            if box and (len(box) == 4 or len(box) == 2):
                if len(box) == 4:
                    ymin, xmin, ymax, xmax = [float(v) for v in box]
                    center_x = ((xmin + xmax) / 2) / 1000.0
                    center_y = ((ymin + ymax) / 2) / 1000.0
                elif len(box) == 2:
                    center_y = float(box[0]) / 1000.0
                    center_x = float(box[1]) / 1000.0
                else:
                    continue
                
                if action_type in ["CLICK", "TYPE"]:
                    self._log(f"🖱️ Clicking at ({center_x:.2f}, {center_y:.2f})")
                    inject_click(center_x, center_y, monitor_info, self.root)
                    
                if action_type == "TYPE":
                    type_text = action_data.get("type_text")
                    if type_text:
                        self._log(f"⌨️ Typing: '{type_text}'")
                        inject_text(type_text)
                        
            elif action_type == "SCROLL_DOWN":
                inject_scroll("down")
            elif action_type == "SCROLL_UP":
                inject_scroll("up")
                
            keys_to_press = action_data.get("press_keys")
            if keys_to_press and isinstance(keys_to_press, list):
                inject_keys(keys_to_press)
                
            # Build detailed history string
            hist_str = f"Turn {step}: {action_type}"
            if action_type == "TYPE" and action_data.get("type_text"):
                hist_str += f" '{action_data['type_text']}' into {action_data.get('target_name', 'field')}"
            elif action_type == "CLICK":
                hist_str += f" on {action_data.get('target_name', 'element')}"
            if keys_to_press:
                hist_str += f", then pressed {keys_to_press}"
            history.append(hist_str)
            time.sleep(1.0)
            
        if step >= max_steps:
            self._log("⚠ Max steps reached. Aborting to prevent infinite loop.")
            self.voice.speak("I've reached the maximum number of steps for this task.")
            
        self._set_engine_status("Idle", Palette.SUCCESS)
        self.root.after(0, self.btn_agent.config, {"state": tk.NORMAL})
        self.root.after(0, self.btn_listen.config, {"state": tk.NORMAL})
        self._log("── Agent Cycle Complete ──")

    # ══════════════════════════════════════════════════════════════════════
    # Shutdown
    # ══════════════════════════════════════════════════════════════════════
    def on_closing(self):
        self.running = False
        if self._wake_stop_fn:
            self._wake_stop_fn(wait_for_stop=False)
        if hasattr(self, '_proactive'):
            self._proactive.stop()
        if self.vision:
            self.vision.release()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = OverlayApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
