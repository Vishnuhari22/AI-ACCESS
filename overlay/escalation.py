"""
Escalation Manager — tracks AI failures and escalates to human assistance
when the system cannot resolve a user's request after repeated attempts.

State machine:  NORMAL → WARNING (1 fail) → ESCALATING (2+ fails) → CONNECTED
"""
import time
import threading
from enum import Enum


class EscalationState(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    ESCALATING = "escalating"
    CONNECTED = "connected"


class EscalationManager:
    """Manages the escalation pathway from AI to human assistance."""

    FAILURE_THRESHOLD = 2

    def __init__(self, on_state_change=None):
        """
        Args:
            on_state_change: Optional callback(new_state, context_dict)
                             called on every state transition.
        """
        self._state = EscalationState.NORMAL
        self._failures = 0
        self._failure_log = []
        self._on_change = on_state_change
        self._lock = threading.Lock()

    @property
    def state(self) -> EscalationState:
        with self._lock:
            return self._state

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def should_escalate(self) -> bool:
        with self._lock:
            return self._state == EscalationState.ESCALATING

    def record_failure(self, error_msg: str = ""):
        with self._lock:
            self._failures += 1
            self._failure_log.append((time.time(), error_msg))

            if self._failures >= self.FAILURE_THRESHOLD:
                new = EscalationState.ESCALATING
            elif self._failures == 1:
                new = EscalationState.WARNING
            else:
                new = self._state

            self._transition(new)

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._transition(EscalationState.NORMAL)

    def simulate_human_connected(self):
        with self._lock:
            self._transition(EscalationState.CONNECTED)

    def reset(self):
        with self._lock:
            self._failures = 0
            self._failure_log.clear()
            self._transition(EscalationState.NORMAL)

    def _transition(self, new_state: EscalationState):
        """Internal: change state and fire callback. Must hold _lock."""
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        print(f"[Escalation] {old.value} → {new_state.value} "
              f"({self._failures} failures)")

        if self._on_change:
            ctx = {"failures": self._failures,
                   "log": list(self._failure_log[-5:])}
            # Release lock before callback to avoid deadlock
            self._lock.release()
            try:
                self._on_change(new_state, ctx)
            finally:
                self._lock.acquire()
