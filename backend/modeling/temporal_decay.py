"""
Temporal Decay — behavioral signals naturally decay over time.
A user who was frustrated 5 minutes ago may have calmed down.
"""
import time
import math


def apply_decay(current_value: float, last_updated: float, half_life_seconds: float = 60.0) -> float:
    """
    Apply exponential decay to a behavioral signal.
    
    Args:
        current_value: The current signal value (0.0 to 1.0)
        last_updated: Timestamp when the value was last actively set
        half_life_seconds: Time for the signal to decay to half its value
    
    Returns:
        Decayed value
    """
    elapsed = time.time() - last_updated
    if elapsed <= 0:
        return current_value
    
    decay_factor = math.exp(-0.693 * elapsed / half_life_seconds)  # ln(2) ≈ 0.693
    return current_value * decay_factor


def decay_user_state(user_state) -> None:
    """
    Apply temporal decay to all volatile signals in the user state.
    Modifies the user state in place.
    """
    now = time.time()
    elapsed = now - user_state.last_updated
    
    # Only decay if enough time has passed (> 5 seconds)
    if elapsed < 5:
        return
    
    # Frustration decays with 90-second half-life
    user_state.frustration_level = apply_decay(
        user_state.frustration_level, user_state.last_updated, half_life_seconds=90.0
    )
    
    # Cognitive load decays with 120-second half-life (slower)
    user_state.cognitive_load = apply_decay(
        user_state.cognitive_load, user_state.last_updated, half_life_seconds=120.0
    )
    
    # Clamp to minimum
    user_state.frustration_level = max(0.0, user_state.frustration_level)
    user_state.cognitive_load = max(0.0, user_state.cognitive_load)
