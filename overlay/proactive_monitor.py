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

    def __init__(self, get_state_fn, trigger_fn,
                 inactivity_threshold: float = 30.0,
                 frustration_threshold: float = 10.0,
                 cooldown: float = 60.0):
        """
        Args:
            get_state_fn: Callable returning vision state dict.
            trigger_fn:   Callable invoked with (reason: str) when help is warranted.
            inactivity_threshold: Seconds of inactivity before triggering.
            frustration_threshold: Seconds of sustained frustration before triggering.
            cooldown: Minimum seconds between consecutive triggers.
        """
        self._get_state = get_state_fn
        self._trigger = trigger_fn
        self._inactivity_threshold = inactivity_threshold
        self._frustration_threshold = frustration_threshold
        self._cooldown = cooldown

        self._running = False
        self._thread = None
        self._last_trigger_time = 0.0
        self._last_cycle_time = time.time()
        self._frustration_start = 0.0

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
        print(f"[ProactiveMonitor] Triggering: {reason}")
        try:
            self._trigger(reason)
        except Exception as e:
            print(f"[ProactiveMonitor] Trigger callback error: {e}")

    def _loop(self):
        while self._running:
            try:
                state = self._get_state()
                now = time.time()

                if not state.get("face_detected", False):
                    self._frustration_start = 0.0
                    time.sleep(3)
                    continue

                if not self._can_trigger():
                    time.sleep(3)
                    continue

                # Check 1: Inactivity
                inactivity = now - self._last_cycle_time
                if inactivity > self._inactivity_threshold:
                    self._do_trigger(
                        f"User inactive for {inactivity:.0f}s with face present")
                    time.sleep(3)
                    continue

                # Check 2: Sustained frustration (squinting AND leaning)
                frustrated = (state.get("squinting", False)
                              and state.get("leaning_forward", False))
                if frustrated:
                    if self._frustration_start == 0:
                        self._frustration_start = now
                    elif (now - self._frustration_start) > self._frustration_threshold:
                        self._do_trigger(
                            f"Sustained frustration for "
                            f"{now - self._frustration_start:.0f}s")
                        self._frustration_start = 0
                else:
                    self._frustration_start = 0

            except Exception as e:
                print(f"[ProactiveMonitor] Loop error: {e}")

            time.sleep(3)
