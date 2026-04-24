"""
Session Manager — tracks per-session state including conversation history,
user state, kiosk state machine, and action executor.
"""
import time
import logging
from modeling.user_state import UserStateVector
from execution.kiosk_state import KioskStateMachine
from execution.action_executor import ActionExecutor

logger = logging.getLogger(__name__)


class Session:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.user_state = UserStateVector()
        self.conversation_history = []
        self.kiosk = KioskStateMachine(mode="atm")
        self.executor = ActionExecutor(self.kiosk)
        self.created_at = time.time()
        self.suggestions_given = set()
    
    def add_turn(self, user_text: str, agent_response: dict):
        """Add a conversation turn to history."""
        self.conversation_history.append({
            "role": "user",
            "content": user_text,
            "timestamp": time.time()
        })
        self.conversation_history.append({
            "role": "assistant",
            "reasoning": agent_response.get("reasoning", ""),
            "actions": agent_response.get("actions", []),
            "timestamp": time.time()
        })
        # Keep last 20 entries (10 turns)
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
    
    def get_kiosk_state(self) -> dict:
        """Get current kiosk state for the Context Bundle."""
        return self.kiosk.to_context_dict()

    def get_kiosk_frontend(self) -> dict:
        """Get current kiosk screen data for the frontend."""
        return self.kiosk.to_frontend_dict()

    def execute_actions(self, actions: list) -> dict:
        """Execute LLM actions through the action executor."""
        return self.executor.execute_actions(actions)

    def set_kiosk_mode(self, mode: str):
        """Switch kiosk mode."""
        self.kiosk.set_mode(mode)


class SessionManager:
    """Manages all active sessions. In-memory for prototype."""
    
    def __init__(self):
        self.sessions = {}
    
    def get_or_create(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            logger.info(f"Creating new session: {session_id}")
            self.sessions[session_id] = Session(session_id)
        return self.sessions[session_id]
    
    def remove(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
