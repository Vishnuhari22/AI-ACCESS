"""
User State Vector — the core data model representing the user's current
physical, cognitive, and behavioral state.

This is the canonical state model shared by all perception sources.
Accessibility decisions are made by AccessibilityPolicy, not here.
"""

from dataclasses import dataclass, field, asdict
from typing import List
import time


@dataclass
class UserStateVector:
    """Canonical user state shared by all perception sources."""

    # ------------------------------------------------------------------
    # Physical capabilities
    # ------------------------------------------------------------------
    visual_capability: float = 1.0
    motor_capability: float = 1.0

    # ------------------------------------------------------------------
    # Cognitive / emotional state
    # ------------------------------------------------------------------
    cognitive_load: float = 0.0
    frustration_level: float = 0.0

    # ------------------------------------------------------------------
    # Perception signals
    # ------------------------------------------------------------------
    hand_tremor: float = 0.0
    squint_confidence: float = 1.0
    lean_confidence: float = 1.0
    tremor_confidence: float = 1.0
    face_confidence: float = 1.0
    hand_confidence: float = 1.0
    looking_down: bool = False
    gaze_direction: str = "center"
    wheelchair_detected: bool = False
    bystander_present: bool = False
    estimated_age: str = "adult"

    # ------------------------------------------------------------------
    # User preferences
    # ------------------------------------------------------------------
    interaction_speed: str = "normal"
    preferred_language: str = "en"
    age_group: str = "adult"

    # ------------------------------------------------------------------
    # Behavioral flags
    # ------------------------------------------------------------------
    behavioral_flags: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Interaction metrics
    # ------------------------------------------------------------------
    error_count: int = 0
    avg_response_time_ms: float = 0.0
    interaction_count: int = 0

    # ------------------------------------------------------------------
    # Timestamp
    # ------------------------------------------------------------------
    last_updated: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Return the complete canonical state as a dictionary."""
        return asdict(self)

    # ------------------------------------------------------------------
    # Frontend state update
    # ------------------------------------------------------------------
    def update_from_frontend(self, data: dict):
        """
        Update canonical state from the web simulation.

        The frontend may provide simulated values, interaction-derived
        values, or real webcam observations.

        Accessibility decisions are NOT made here.
        """

        # Physical capabilities
        if "visual_capability" in data:
            self.visual_capability = max(
                0.0,
                min(1.0, float(data["visual_capability"]))
            )

        if "motor_capability" in data:
            self.motor_capability = max(
                0.0,
                min(1.0, float(data["motor_capability"]))
            )

        # Cognitive / emotional state
        if "cognitive_load" in data:
            self.cognitive_load = max(
                0.0,
                min(1.0, float(data["cognitive_load"]))
            )

        if "frustration_level" in data:
            self.frustration_level = max(
                0.0,
                min(1.0, float(data["frustration_level"]))
            )

        # Preferences
        if "interaction_speed" in data:
            self.interaction_speed = str(
                data["interaction_speed"]
            )

        if "preferred_language" in data:
            self.preferred_language = str(
                data["preferred_language"]
            )

        if "age_group" in data:
            self.age_group = str(
                data["age_group"]
            )

        # Perception signals
        if "hand_tremor" in data:
            self.hand_tremor = max(
                0.0,
                min(1.0, float(data["hand_tremor"]))
            )

        if "squint_confidence" in data:
            self.squint_confidence = max(
                0.0,
                min(1.0, float(data["squint_confidence"]))
            )

        if "lean_confidence" in data:
            self.lean_confidence = max(
                0.0,
                min(1.0, float(data["lean_confidence"]))
            )

        if "tremor_confidence" in data:
            self.tremor_confidence = max(
                0.0,
                min(1.0, float(data["tremor_confidence"]))
            )

        if "face_confidence" in data:
            self.face_confidence = max(
                0.0,
                min(1.0, float(data["face_confidence"]))
            )

        if "hand_confidence" in data:
            self.hand_confidence = max(
                0.0,
                min(1.0, float(data["hand_confidence"]))
            )

        if "looking_down" in data:
            self.looking_down = bool(
                data["looking_down"]
            )

        if "gaze_direction" in data:
            self.gaze_direction = str(
                data["gaze_direction"]
            )

        if "wheelchair_detected" in data:
            self.wheelchair_detected = bool(
                data["wheelchair_detected"]
            )

        if "bystander_present" in data:
            self.bystander_present = bool(
                data["bystander_present"]
            )

        if "estimated_age" in data:
            self.estimated_age = str(
                data["estimated_age"]
            )

        # Behavioral flags
        if "behavioral_flags" in data:
            self.behavioral_flags = sorted(
                set(
                    str(flag)
                    for flag in data["behavioral_flags"]
                )
            )

        self.last_updated = time.time()

    # ------------------------------------------------------------------
    # Vision observation → behavioral flags
    # ------------------------------------------------------------------
    def update_behavioral_flags_from_observations(
        self,
        squinting: bool = False,
        leaning_forward: bool = False,
        hand_tremor: float | None = None,
    ):
        """
        Convert raw perception observations into behavioral flags.

        This method only updates canonical state.

        It does NOT determine accessibility level or UI adaptation.
        """

        flags = set(self.behavioral_flags)

        # Remove the previous dynamically detected values so that
        # stale observations do not persist.
        flags.discard("squinting")
        flags.discard("leaning_forward")
        flags.discard("hand_tremor")

        if squinting:
            flags.add("squinting")
            self.squint_confidence = max(
                self.squint_confidence,
                1.0
            )

        if leaning_forward:
            flags.add("leaning_forward")
            self.lean_confidence = max(
                self.lean_confidence,
                1.0
            )

        if hand_tremor is not None:
            self.hand_tremor = max(
                0.0,
                min(1.0, float(hand_tremor))
            )

            if self.hand_tremor > 0.35:
                flags.add("hand_tremor")

        self.behavioral_flags = sorted(flags)
        self.last_updated = time.time()

    # ------------------------------------------------------------------
    # Interaction error tracking
    # ------------------------------------------------------------------
    def record_error(self):
        """Record an interaction error and update frustration state."""

        self.error_count += 1

        if self.error_count >= 3:
            self.frustration_level = min(
                1.0,
                self.frustration_level + 0.2
            )

        if (
            self.error_count >= 3
            and "repeated_errors" not in self.behavioral_flags
        ):
            self.behavioral_flags.append("repeated_errors")
            self.behavioral_flags.sort()

        self.last_updated = time.time()

    # ------------------------------------------------------------------
    # Interaction tracking
    # ------------------------------------------------------------------
    def record_interaction(self, response_time_ms: float):
        """
        Record an interaction and update the running average response time.
        """

        self.interaction_count += 1

        self.avg_response_time_ms = (
            (
                self.avg_response_time_ms
                * (self.interaction_count - 1)
                + response_time_ms
            )
            / self.interaction_count
        )

        if self.avg_response_time_ms > 5000:
            self.interaction_speed = "slow"
        elif self.avg_response_time_ms < 1500:
            self.interaction_speed = "fast"
        else:
            self.interaction_speed = "normal"

        self.last_updated = time.time()

    # ------------------------------------------------------------------
    # Accessibility decision helper
    # ------------------------------------------------------------------
    def needs_accessibility_boost(self) -> bool:
        """
        Return whether the canonical accessibility policy currently
        considers the user to need accessibility support.

        The actual decision remains centralized in AccessibilityPolicy.
        """

        from modeling.accessibility_policy import AccessibilityPolicy

        decision = AccessibilityPolicy.evaluate(self)

        return decision["needs_accessibility_boost"]