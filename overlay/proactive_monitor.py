"""
Proactive Monitor — detects user frustration or inactivity and triggers
AI assistance without requiring voice input.

The system is currently "sound-gated" — nothing happens until the user speaks.
This module adds a background watcher that nudges the AI when it detects:
  1. Long inactivity (face present but no voice cycle)
  2. Sustained frustration (squinting + leaning for extended period)
"""
import threading
import time


class ProactiveMonitor:
    """Background monitor that triggers proactive AI assistance."""

    def __init__(self, get_state_fn, trigger_fn, empathetic_fn=None,
                 inactivity_threshold: float = 30.0,
                 frustration_threshold: float = 10.0,
                 cooldown: float = 60.0):
        """
        Args:
            get_state_fn: Callable returning vision state dict.
            trigger_fn:   Callable invoked with (reason: str) when help is warranted.
            empathetic_fn: Callable invoked with (speech: str) for direct empathetic prompts.
            inactivity_threshold: Seconds of inactivity before triggering.
            frustration_threshold: Seconds of sustained frustration before triggering.
            cooldown: Minimum seconds between consecutive triggers.
        """
        self._get_state = get_state_fn
        self._trigger = trigger_fn
        self._empathetic_trigger = empathetic_fn
        self._inactivity_threshold = inactivity_threshold
        self._frustration_threshold = frustration_threshold
        self._cooldown = cooldown

        self._running = False
        self._thread = None
        self._last_trigger_time = 0.0
        self._last_cycle_time = time.time()
        
        self._frustration_start = 0.0
        self._tremor_start = 0.0
        self._last_frustration_seen = 0.0
        self._last_tremor_seen = 0.0

    # ── Public API ──────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[ProactiveMonitor] Started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        print("[ProactiveMonitor] Stopped.")

    def record_cycle(self):
        """Call whenever a voice cycle completes (resets inactivity timer)."""
        self._last_cycle_time = time.time()

    # ── Internal ────────────────────────────────────────────────────────

    def _can_trigger(self) -> bool:
        return (time.time() - self._last_trigger_time) > self._cooldown

    def _do_trigger(self, reason: str):
        self._last_trigger_time = time.time()
        print(f"[ProactiveMonitor] Triggering LLM: {reason}")
        try:
            self._trigger(reason)
        except Exception as e:
            print(f"[ProactiveMonitor] Trigger callback error: {e}")

    def _do_empathetic_trigger(self, speech: str):
        self._last_trigger_time = time.time()
        print(f"[ProactiveMonitor] Empathetic Trigger: {speech}")
        try:
            if self._empathetic_trigger:
                self._empathetic_trigger(speech)
        except Exception as e:
            print(f"[ProactiveMonitor] Empathetic callback error: {e}")

    def _loop(self):
        # We poll frequently (0.5s) to catch short 2-3s events like tremor and squinting
        POLL_INTERVAL = 0.5
        while self._running:
            try:
                state = self._get_state()
                now = time.time()

                if not state.get("face_detected", False):
                    self._frustration_start = 0.0
                    self._tremor_start = 0.0
                    time.sleep(POLL_INTERVAL)
                    continue

                if not self._can_trigger():
                    time.sleep(POLL_INTERVAL)
                    continue
                    
                # Check 1: Hand Tremor (>35% for ~2.5s)
                decision = state.get(
                    "accessibility_decision",
                    {}
                )

                # Consume the policy's specific tremor decision rather than
                # interpreting the raw hand signal here.
                tremor_need = decision.get(
                    "tremor_need",
                    False
                )

                if tremor_need:
                    self._last_tremor_seen = now
                    if self._tremor_start == 0:
                        self._tremor_start = now
                    elif (now - self._tremor_start) > 2.5:
                        self._do_empathetic_trigger("I noticed some hand tremor. Would you like me to navigate by voice for you?")
                        self._tremor_start = 0
                        time.sleep(POLL_INTERVAL)
                        continue
                else:
                    if (now - self._last_tremor_seen) > 0.8:
                        self._tremor_start = 0

                # Check 2: Sustained Vision Difficulty (squinting OR leaning for 2.5s, with blink tolerance)
                vision_difficulty = decision.get(
                    "visual_need",
                    False
                )
                if vision_difficulty:
                    self._last_frustration_seen = now
                    if self._frustration_start == 0:
                        self._frustration_start = now
                    elif (now - self._frustration_start) > 2.5:
                        self._do_empathetic_trigger("I noticed you're looking closely. Would you like me to read the screen aloud?")
                        self._frustration_start = 0
                        time.sleep(POLL_INTERVAL)
                        continue
                else:
                    # Allow up to 1.0s gap for natural eye blinks without resetting counter
                    if (now - self._last_frustration_seen) > 1.0:
                        self._frustration_start = 0

                # Check 3: Inactivity
                inactivity = now - self._last_cycle_time
                if inactivity > self._inactivity_threshold:
                    self._do_trigger(f"User inactive for {inactivity:.0f}s with face present")
                    time.sleep(POLL_INTERVAL)
                    continue

            except Exception as e:
                print(f"[ProactiveMonitor] Loop error: {e}")

            time.sleep(POLL_INTERVAL)
