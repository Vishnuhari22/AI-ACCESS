"""
Context Bundle Assembler — packages ALL available signals into a single 
JSON structure that gets sent to the LLM as the "user prompt".
This is the core data contract between perception and intelligence.
"""
import time
from typing import List, Optional
from modeling.user_state import UserStateVector
from modeling.accessibility_policy import AccessibilityPolicy


class ContextBundleAssembler:
    
    @staticmethod
    def assemble(
        user_transcript: str,
        user_state: UserStateVector,
        kiosk_state: dict,
        conversation_history: List[dict],
        session_metadata: Optional[dict] = None
    ) -> dict:

        accessibility = AccessibilityPolicy.evaluate(user_state)

        user_state_dict = user_state.to_dict()
        """
        Assemble a complete Context Bundle for the LLM.
        
        Args:
            user_transcript: What the user just said (ASR output)
            user_state: Current canonical UserStateVector
            kiosk_state: Current kiosk screen state
            conversation_history: Last N conversation turns
            session_metadata: Optional session info (duration, etc.)
        
        Returns:
            Complete Context Bundle dict ready for the LLM prompt
        """
        bundle = {
            "timestamp": time.time(),
            
            "user_input": {
                "transcript": user_transcript,
                "input_method": "voice"
            },
            
            "user_state": {
                "visual_capability": user_state.visual_capability,
                "motor_capability": user_state.motor_capability,
                "cognitive_load": user_state.cognitive_load,
                "frustration_level": user_state.frustration_level,

                "interaction_speed": user_state.interaction_speed,
                "preferred_language": user_state.preferred_language,
                "age_group": user_state.age_group,

                "hand_tremor": user_state.hand_tremor,
                "looking_down": user_state.looking_down,
                "gaze_direction": user_state.gaze_direction,

                "wheelchair_detected": user_state.wheelchair_detected,
                "bystander_present": user_state.bystander_present,
                "estimated_age": user_state.estimated_age,

                "behavioral_flags": user_state.behavioral_flags,

                "error_count": user_state.error_count,
                "interaction_count": user_state.interaction_count,
                "avg_response_time_ms": user_state.avg_response_time_ms,

                # Deterministic decision made outside the LLM.
                "accessibility_decision": accessibility,
            },
            
            "kiosk_state": kiosk_state,
            
            "conversation_history": conversation_history[-10:],  # Last 10 turns max
            
            "session": session_metadata or {
                "interaction_count": user_state.interaction_count,
                "session_active": True
            }
        }
        
        return bundle
