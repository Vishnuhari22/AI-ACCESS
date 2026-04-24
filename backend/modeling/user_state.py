"""
User State Vector — the core data model representing the user's current 
physical, cognitive, and behavioral state. This is what the LLM uses to 
decide how to adapt the kiosk experience.
"""
from dataclasses import dataclass, field, asdict
from typing import List
import time


@dataclass
class UserStateVector:
    """Comprehensive user state vector for accessibility modeling."""
    
    # Physical capabilities (0.0 = no capability, 1.0 = full capability)
    visual_capability: float = 1.0
    motor_capability: float = 1.0
    
    # Cognitive/emotional state (0.0 = calm/low, 1.0 = high)
    cognitive_load: float = 0.0
    frustration_level: float = 0.0
    
    # Behavioral characteristics
    hand_tremor: float = 0.0
    wheelchair_detected: bool = False
    bystander_present: bool = False
    estimated_age: str = "adult"
    
    # Behavioral flags detected from observation
    behavioral_flags: List[str] = field(default_factory=list)
    # Possible flags: "squinting", "leaning_forward", "hand_tremor", 
    #                 "repeated_errors", "long_pauses", "confused_speech"
    
    # Interaction metrics (auto-tracked)
    error_count: int = 0
    avg_response_time_ms: float = 0.0
    interaction_count: int = 0
    
    # Timestamp of last update
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Convert to a clean dictionary for the Context Bundle."""
        return asdict(self)
    
    def update_from_frontend(self, data: dict):
        """Update state from frontend slider/control panel values."""
        if "visual_capability" in data:
            self.visual_capability = float(data["visual_capability"])
        if "motor_capability" in data:
            self.motor_capability = float(data["motor_capability"])
        if "cognitive_load" in data:
            self.cognitive_load = float(data["cognitive_load"])
        if "frustration_level" in data:
            self.frustration_level = float(data["frustration_level"])
        if "interaction_speed" in data:
            self.interaction_speed = data["interaction_speed"]
        if "age_group" in data:
            self.age_group = data["age_group"]
        if "hand_tremor" in data:
            self.hand_tremor = float(data["hand_tremor"])
        if "wheelchair_detected" in data:
            self.wheelchair_detected = bool(data["wheelchair_detected"])
        if "bystander_present" in data:
            self.bystander_present = bool(data["bystander_present"])
        if "estimated_age" in data:
            self.estimated_age = data["estimated_age"]
        
        self.last_updated = time.time()
    
    def record_error(self):
        """Track a user error for frustration estimation."""
        self.error_count += 1
        # Auto-escalate frustration based on error count
        if self.error_count >= 3:
            self.frustration_level = min(1.0, self.frustration_level + 0.2)
    
    def record_interaction(self, response_time_ms: float):
        """Track interaction timing for speed estimation."""
        self.interaction_count += 1
        # Running average
        self.avg_response_time_ms = (
            (self.avg_response_time_ms * (self.interaction_count - 1) + response_time_ms)
            / self.interaction_count
        )
        # Auto-classify speed
        if self.avg_response_time_ms > 5000:
            self.interaction_speed = "slow"
        elif self.avg_response_time_ms < 1500:
            self.interaction_speed = "fast"
        else:
            self.interaction_speed = "normal"

    def needs_accessibility_boost(self) -> bool:
        """Quick check if this user likely needs enhanced accessibility."""
        return (
            self.visual_capability < 0.5
            or self.motor_capability < 0.5
            or self.cognitive_load > 0.6
            or self.frustration_level > 0.5
            or self.age_group == "elderly"
            or "hand_tremor" in self.behavioral_flags
            or "squinting" in self.behavioral_flags
        )
