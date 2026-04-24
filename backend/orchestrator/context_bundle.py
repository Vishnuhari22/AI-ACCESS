"""
Context Bundle Assembler — packages ALL available signals into a single 
JSON structure that gets sent to the LLM as the "user prompt".
This is the core data contract between perception and intelligence.
"""
import time
from typing import List, Optional


class ContextBundleAssembler:
    
    @staticmethod
    def assemble(
        user_transcript: str,
        user_state_dict: dict,
        kiosk_state: dict,
        conversation_history: List[dict],
        session_metadata: Optional[dict] = None
    ) -> dict:
        """
        Assemble a complete Context Bundle for the LLM.
        
        Args:
            user_transcript: What the user just said (ASR output)
            user_state_dict: Current UserStateVector as dict
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
                "visual_capability": user_state_dict.get("visual_capability", 1.0),
                "motor_capability": user_state_dict.get("motor_capability", 1.0),
                "cognitive_load": user_state_dict.get("cognitive_load", 0.0),
                "frustration_level": user_state_dict.get("frustration_level", 0.0),
                "interaction_speed": user_state_dict.get("interaction_speed", "normal"),
                "age_group": user_state_dict.get("age_group", "adult"),
                "hand_tremor": user_state_dict.get("hand_tremor", 0.0),
                "wheelchair_detected": user_state_dict.get("wheelchair_detected", False),
                "bystander_present": user_state_dict.get("bystander_present", False),
                "estimated_age": user_state_dict.get("estimated_age", "adult"),
                "behavioral_flags": user_state_dict.get("behavioral_flags", []),
                "error_count": user_state_dict.get("error_count", 0),
                "needs_accessibility_boost": (
                    user_state_dict.get("visual_capability", 1.0) < 0.5
                    or user_state_dict.get("motor_capability", 1.0) < 0.5
                    or user_state_dict.get("cognitive_load", 0.0) > 0.6
                    or user_state_dict.get("frustration_level", 0.0) > 0.5
                    or user_state_dict.get("age_group", "adult") == "elderly"
                )
            },
            
            "kiosk_state": kiosk_state,
            
            "conversation_history": conversation_history[-10:],  # Last 10 turns max
            
            "session": session_metadata or {
                "interaction_count": user_state_dict.get("interaction_count", 0),
                "session_active": True
            }
        }
        
        return bundle
