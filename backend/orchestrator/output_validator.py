"""
Output Validator — validates the JSON structure returned by the LLM
to ensure it matches our expected action schema before execution.
"""
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

VALID_ACTION_TYPES = {"speech_output", "ui_adaptation", "kiosk_command", "proactive_suggestion"}
VALID_CONTRAST_MODES = {"normal", "high_contrast", "dark"}
VALID_LAYOUTS = {"standard", "simplified"}
VALID_LANGUAGES = {"en", "hi", "ta"}


def validate_llm_output(output: dict) -> Tuple[bool, str]:
    """
    Validate the LLM's JSON output against the expected schema.
    
    Returns:
        (is_valid, error_message) — error_message is empty string if valid
    """
    # Check top-level structure
    if not isinstance(output, dict):
        return False, "Output must be a JSON object"
    
    if "reasoning" not in output:
        return False, "Missing 'reasoning' field"
    
    if "actions" not in output:
        return False, "Missing 'actions' field"
    
    if not isinstance(output["actions"], list):
        return False, "'actions' must be an array"
    
    if len(output["actions"]) == 0:
        return False, "'actions' array must not be empty"
    
    # Check for at least one speech_output
    has_speech = False
    
    for i, action in enumerate(output["actions"]):
        if not isinstance(action, dict):
            return False, f"Action {i} is not a JSON object"
        
        action_type = action.get("type")
        if action_type not in VALID_ACTION_TYPES:
            return False, f"Action {i} has invalid type '{action_type}'. Valid: {VALID_ACTION_TYPES}"
        
        # Validate each action type
        if action_type == "speech_output":
            has_speech = True
            if "text" not in action or not action["text"].strip():
                return False, f"Action {i} (speech_output) missing or empty 'text'"
        
        elif action_type == "ui_adaptation":
            if "adaptations" not in action:
                return False, f"Action {i} (ui_adaptation) missing 'adaptations'"
            adaptations = action["adaptations"]
            if not isinstance(adaptations, dict):
                return False, f"Action {i} (ui_adaptation) 'adaptations' must be a dict"
            # Optional field checks
            if "contrast_mode" in adaptations and adaptations["contrast_mode"] not in VALID_CONTRAST_MODES:
                return False, f"Action {i}: invalid contrast_mode '{adaptations['contrast_mode']}'"
            if "layout" in adaptations and adaptations["layout"] not in VALID_LAYOUTS:
                return False, f"Action {i}: invalid layout '{adaptations['layout']}'"
        
        elif action_type == "kiosk_command":
            if "command" not in action:
                return False, f"Action {i} (kiosk_command) missing 'command'"
        
        elif action_type == "proactive_suggestion":
            if "suggestion" not in action:
                return False, f"Action {i} (proactive_suggestion) missing 'suggestion'"
    
    if not has_speech:
        return False, "Must include at least one 'speech_output' action"
    
    return True, ""
