"""
Accessibility Policy — single source of truth for deterministic
accessibility decisions.

Detection modules should NOT decide UI adaptation.

They only produce observations:
    squinting
    leaning_forward
    hand_tremor
    etc.

This policy consumes the canonical UserStateVector and produces
the accessibility decision used by both the web simulation and
the desktop overlay.
"""


class AccessibilityPolicy:
    """
    Deterministic accessibility decision engine.

    The same policy must be used by:
      1. Web simulation backend
      2. Desktop overlay
    """

    VISUAL_STRONG_THRESHOLD = 0.5
    VISUAL_MILD_THRESHOLD = 0.7
    MOTOR_THRESHOLD = 0.5
    COGNITIVE_THRESHOLD = 0.6
    FRUSTRATION_THRESHOLD = 0.5
    TREMOR_THRESHOLD = 0.35

    @classmethod
    def evaluate(cls, state) -> dict:
        """
        Convert canonical UserStateVector into deterministic
        accessibility decisions.

        Returns a serializable dictionary.
        """

        flags = set(state.behavioral_flags or [])

        visual_strong = (
            state.visual_capability < cls.VISUAL_STRONG_THRESHOLD
            or (
                "squinting" in flags
                and state.squint_confidence >= 0.65
            )
        )

        visual_mild = (
            state.visual_capability < cls.VISUAL_MILD_THRESHOLD
        )

        motor_needed = (
            state.motor_capability < cls.MOTOR_THRESHOLD
            or (
                "leaning_forward" in flags
                and state.lean_confidence >= 0.65
            )
            or (
                state.hand_tremor > cls.TREMOR_THRESHOLD
                and state.tremor_confidence >= 0.65
            )
            or (
                "hand_tremor" in flags
                and state.tremor_confidence >= 0.65
            )
        )

        cognitive_needed = (
            state.cognitive_load > cls.COGNITIVE_THRESHOLD
        )

        frustration_needed = (
            state.frustration_level > cls.FRUSTRATION_THRESHOLD
        )

        # Specific observation-derived decisions for downstream proactive
        # assistance. These are still deterministic policy outputs.
        tremor_needed = (
            state.hand_tremor > cls.TREMOR_THRESHOLD
            and state.tremor_confidence >= 0.65
        ) or (
            "hand_tremor" in flags
            and state.tremor_confidence >= 0.55
        )

        # Highest adaptation level wins.
        if visual_strong and motor_needed:
            level = "full"
        elif visual_strong:
            level = "visual"
        elif motor_needed:
            level = "motor"
        elif visual_mild:
            level = "visual"
        elif cognitive_needed or frustration_needed:
            level = "support"
        else:
            level = "normal"

        # These values match the intended behavior of the existing
        # web simulation and desktop overlay.
        adaptation = {
            "level": level,
            "font_size_multiplier": 1.0,
            "contrast_mode": "normal",
            "layout": "standard",
            "voice_guidance": False,
        }

        if level == "visual":
            adaptation.update({
                "font_size_multiplier": 1.4,
                "contrast_mode": "high_contrast",
            })

        elif level == "motor":
            adaptation.update({
                "font_size_multiplier": 1.2,
                "layout": "simplified",
            })

        elif level == "full":
            adaptation.update({
                "font_size_multiplier": 1.5,
                "contrast_mode": "high_contrast",
                "layout": "simplified",
                "voice_guidance": True,
            })

        elif level == "support":
            adaptation.update({
                "font_size_multiplier": 1.2,
                "layout": "simplified",
                "voice_guidance": True,
            })

        return {
            "accessibility_level": level,
            "needs_accessibility_boost": (
                visual_strong
                or visual_mild
                or motor_needed
                or cognitive_needed
                or frustration_needed
                or state.estimated_age == "elderly"
            ),
            "visual_need": visual_strong or visual_mild,
            "motor_need": motor_needed,
            "tremor_need": tremor_needed,
            "cognitive_need": cognitive_needed,
            "frustration_need": frustration_needed,
            "adaptation": adaptation,
        }