"""
Kiosk State Machine — defines all screens, transitions, and available actions
for ATM and Hospital kiosk modes. This is the "simulated kiosk hardware."
"""
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class KioskScreen:
    """Represents a single screen on the kiosk."""
    id: str
    title: str
    description: str
    buttons: List[dict]           # [{id, label, action}]
    input_field: Optional[dict] = None  # {type: "numpad"|"pin", placeholder}
    display_data: dict = field(default_factory=dict)  # Dynamic data shown on screen


# ──────────────────────────────────────────────
#  ATM SCREEN DEFINITIONS
# ──────────────────────────────────────────────
ATM_SCREENS: Dict[str, KioskScreen] = {
    "welcome": KioskScreen(
        id="welcome",
        title="Welcome",
        description="Welcome to Smart ATM. Please insert your card or tap to begin.",
        buttons=[
            {"id": "start", "label": "Tap to Begin", "action": "START_TRANSACTION"}
        ]
    ),
    "main_menu": KioskScreen(
        id="main_menu",
        title="Main Menu",
        description="Please select a transaction:",
        buttons=[
            {"id": "withdraw", "label": "💵 Cash Withdrawal", "action": "SELECT_WITHDRAWAL"},
            {"id": "balance", "label": "💰 Balance Enquiry", "action": "SELECT_BALANCE"},
            {"id": "statement", "label": "📄 Mini Statement", "action": "SELECT_STATEMENT"},
        ]
    ),
    "withdrawal": KioskScreen(
        id="withdrawal",
        title="Cash Withdrawal",
        description="Select an amount or enter a custom amount:",
        buttons=[
            {"id": "amt500", "label": "₹500", "action": "SET_AMOUNT_500"},
            {"id": "amt1000", "label": "₹1,000", "action": "SET_AMOUNT_1000"},
            {"id": "amt2000", "label": "₹2,000", "action": "SET_AMOUNT_2000"},
            {"id": "amt5000", "label": "₹5,000", "action": "SET_AMOUNT_5000"},
            {"id": "other", "label": "Other Amount", "action": "ENTER_CUSTOM_AMOUNT"},
            {"id": "back", "label": "← Back", "action": "GO_BACK"},
        ]
    ),
    "enter_amount": KioskScreen(
        id="enter_amount",
        title="Enter Amount",
        description="Enter the amount you wish to withdraw:",
        buttons=[
            {"id": "submit", "label": "✓ Confirm", "action": "SUBMIT_AMOUNT"},
            {"id": "back", "label": "← Back", "action": "GO_BACK"},
        ],
        input_field={"type": "numpad", "placeholder": "₹ 0"}
    ),
    "enter_pin": KioskScreen(
        id="enter_pin",
        title="Enter PIN",
        description="Please enter your 4-digit PIN:",
        buttons=[
            {"id": "submit", "label": "✓ Submit", "action": "SUBMIT_PIN"},
            {"id": "back", "label": "← Cancel", "action": "GO_BACK"},
        ],
        input_field={"type": "pin", "placeholder": "● ● ● ●"}
    ),
    "processing": KioskScreen(
        id="processing",
        title="Processing",
        description="Please wait while we process your transaction...",
        buttons=[]
    ),
    "dispensing": KioskScreen(
        id="dispensing",
        title="Dispensing Cash",
        description="Please collect your cash from the dispenser.",
        buttons=[
            {"id": "done", "label": "Cash Collected ✓", "action": "CASH_COLLECTED"}
        ]
    ),
    "receipt": KioskScreen(
        id="receipt",
        title="Receipt",
        description="Would you like a receipt?",
        buttons=[
            {"id": "yes", "label": "🖨️ Print Receipt", "action": "PRINT_RECEIPT"},
            {"id": "no", "label": "No Thanks", "action": "NO_RECEIPT"},
        ]
    ),
    "balance_display": KioskScreen(
        id="balance_display",
        title="Balance Enquiry",
        description="Your account balance:",
        buttons=[
            {"id": "done", "label": "Done", "action": "GO_HOME"},
        ],
        display_data={"balance": "₹24,580.00", "account": "XXXX-XXXX-4521"}
    ),
    "statement_display": KioskScreen(
        id="statement_display",
        title="Mini Statement",
        description="Recent transactions:",
        buttons=[
            {"id": "done", "label": "Done", "action": "GO_HOME"},
        ],
        display_data={
            "transactions": [
                {"date": "09 Apr", "desc": "UPI Transfer", "amount": "-₹1,200"},
                {"date": "08 Apr", "desc": "Salary Credit", "amount": "+₹35,000"},
                {"date": "07 Apr", "desc": "ATM Withdrawal", "amount": "-₹2,000"},
                {"date": "05 Apr", "desc": "Online Purchase", "amount": "-₹899"},
                {"date": "03 Apr", "desc": "UPI Transfer", "amount": "-₹500"},
            ]
        }
    ),
    "thank_you": KioskScreen(
        id="thank_you",
        title="Thank You",
        description="Thank you for using Smart ATM. Have a great day!",
        buttons=[
            {"id": "new", "label": "New Transaction", "action": "NEW_TRANSACTION"},
        ]
    ),
}

# ──────────────────────────────────────────────
#  HOSPITAL KIOSK SCREEN DEFINITIONS
# ──────────────────────────────────────────────
HOSPITAL_SCREENS: Dict[str, KioskScreen] = {
    "welcome": KioskScreen(
        id="welcome",
        title="Welcome",
        description="Welcome to City Hospital. How can we help you today?",
        buttons=[
            {"id": "token", "label": "🎫 Generate Token", "action": "SELECT_TOKEN"},
            {"id": "appt", "label": "📅 Check Appointment", "action": "SELECT_APPOINTMENT"},
        ]
    ),
    "department_select": KioskScreen(
        id="department_select",
        title="Select Department",
        description="Please choose a department:",
        buttons=[
            {"id": "cardio", "label": "❤️ Cardiology", "action": "SELECT_DEPT_CARDIOLOGY"},
            {"id": "opthal", "label": "👁️ Ophthalmology", "action": "SELECT_DEPT_OPHTHALMOLOGY"},
            {"id": "ortho", "label": "🦴 Orthopedics", "action": "SELECT_DEPT_ORTHOPEDICS"},
            {"id": "general", "label": "🩺 General Medicine", "action": "SELECT_DEPT_GENERAL"},
            {"id": "ent", "label": "👂 ENT", "action": "SELECT_DEPT_ENT"},
            {"id": "back", "label": "← Back", "action": "GO_BACK"},
        ]
    ),
    "doctor_select": KioskScreen(
        id="doctor_select",
        title="Select Doctor",
        description="Available doctors:",
        buttons=[
            {"id": "back", "label": "← Back", "action": "GO_BACK"},
        ],
        display_data={
            "doctors": [
                {"name": "Dr. Sharma", "slots": "10:00 AM, 11:30 AM", "action": "SELECT_DOCTOR_1"},
                {"name": "Dr. Patel", "slots": "2:00 PM, 3:30 PM", "action": "SELECT_DOCTOR_2"},
                {"name": "Dr. Kumar", "slots": "4:00 PM", "action": "SELECT_DOCTOR_3"},
            ]
        }
    ),
    "token_generated": KioskScreen(
        id="token_generated",
        title="Token Generated",
        description="Your token has been generated successfully!",
        buttons=[
            {"id": "print", "label": "🖨️ Print Token", "action": "PRINT_TOKEN"},
            {"id": "new", "label": "New Token", "action": "NEW_TRANSACTION"},
        ],
        display_data={"token_number": "A-042", "department": "", "doctor": "", "time": ""}
    ),
    "appointment_check": KioskScreen(
        id="appointment_check",
        title="Appointment Details",
        description="Enter your appointment ID or phone number:",
        buttons=[
            {"id": "submit", "label": "✓ Check", "action": "CHECK_APPOINTMENT"},
            {"id": "back", "label": "← Back", "action": "GO_BACK"},
        ],
        input_field={"type": "numpad", "placeholder": "Appointment ID"}
    ),
    "appointment_details": KioskScreen(
        id="appointment_details",
        title="Appointment Found",
        description="Your appointment details:",
        buttons=[
            {"id": "done", "label": "Done", "action": "GO_HOME"},
        ],
        display_data={
            "appointment": {"doctor": "Dr. Sharma", "dept": "Cardiology", "date": "10 Apr 2026", "time": "10:00 AM", "status": "Confirmed"}
        }
    ),
    "thank_you": KioskScreen(
        id="thank_you",
        title="Thank You",
        description="Thank you for visiting City Hospital. Get well soon!",
        buttons=[
            {"id": "new", "label": "Start Over", "action": "NEW_TRANSACTION"},
        ]
    ),
}


# ──────────────────────────────────────────────
#  VALID TRANSITIONS
# ──────────────────────────────────────────────
ATM_TRANSITIONS = {
    "welcome":            ["main_menu"],
    "main_menu":          ["withdrawal", "balance_display", "statement_display"],
    "withdrawal":         ["enter_amount", "enter_pin", "main_menu"],
    "enter_amount":       ["enter_pin", "withdrawal"],
    "enter_pin":          ["processing", "withdrawal", "main_menu"],
    "processing":         ["dispensing", "balance_display", "statement_display"],
    "dispensing":         ["receipt"],
    "receipt":            ["thank_you"],
    "balance_display":    ["welcome", "main_menu"],
    "statement_display":  ["welcome", "main_menu"],
    "thank_you":          ["welcome"],
}

HOSPITAL_TRANSITIONS = {
    "welcome":             ["department_select", "appointment_check"],
    "department_select":   ["doctor_select", "welcome"],
    "doctor_select":       ["token_generated", "department_select"],
    "token_generated":     ["welcome", "thank_you"],
    "appointment_check":   ["appointment_details", "welcome"],
    "appointment_details": ["welcome"],
    "thank_you":           ["welcome"],
}


class KioskStateMachine:
    """Manages kiosk state, screen transitions, and transaction data."""

    def __init__(self, mode: str = "atm"):
        self.mode = mode
        self.current_screen_id = "welcome"
        self.transaction_data = {}  # amount, pin, department, doctor, etc.
        self._history = ["welcome"]  # For GO_BACK navigation

    def get_screens(self) -> Dict[str, KioskScreen]:
        return ATM_SCREENS if self.mode == "atm" else HOSPITAL_SCREENS

    def get_transitions(self) -> dict:
        return ATM_TRANSITIONS if self.mode == "atm" else HOSPITAL_TRANSITIONS

    def get_current_screen(self) -> KioskScreen:
        screens = self.get_screens()
        return screens.get(self.current_screen_id, screens["welcome"])

    def navigate_to(self, target_screen: str) -> bool:
        """
        Navigate to a target screen.
        For the prototype, we allow the LLM to jump to any valid screen
        (the LLM is smart enough to know what's appropriate).
        """
        screens = self.get_screens()

        # Allow navigating to welcome from anywhere (full reset)
        if target_screen == "welcome":
            self.current_screen_id = "welcome"
            self._history = ["welcome"]
            self.transaction_data = {}
            logger.info("Kiosk reset to welcome")
            return True

        # Allow navigation to any valid screen in the current mode
        if target_screen in screens:
            self._history.append(self.current_screen_id)
            self.current_screen_id = target_screen
            logger.info(f"Kiosk navigated: → {target_screen}")
            return True

        logger.warning(f"Unknown screen: {target_screen}")
        return False

    def go_back(self) -> str:
        """Go to the previous screen."""
        if len(self._history) > 1:
            self._history.pop()
            self.current_screen_id = self._history[-1]
        else:
            self.current_screen_id = "welcome"
        logger.info(f"Kiosk back: → {self.current_screen_id}")
        return self.current_screen_id

    def set_mode(self, mode: str):
        """Switch kiosk mode (atm/hospital)."""
        self.mode = mode
        self.current_screen_id = "welcome"
        self.transaction_data = {}
        self._history = ["welcome"]

    def to_context_dict(self) -> dict:
        """Generate the kiosk state for the Context Bundle."""
        screen = self.get_current_screen()
        return {
            "mode": self.mode,
            "current_screen": screen.id,
            "screen_title": screen.title,
            "screen_description": screen.description,
            "available_buttons": [{"label": b["label"], "action": b["action"]} for b in screen.buttons],
            "has_input_field": screen.input_field is not None,
            "input_field_type": screen.input_field["type"] if screen.input_field else None,
            "display_data": screen.display_data,
            "transaction_data": self.transaction_data,
        }

    def to_frontend_dict(self) -> dict:
        """Generate full screen data for the frontend to render."""
        screen = self.get_current_screen()
        return {
            "screen_id": screen.id,
            "title": screen.title,
            "description": screen.description,
            "buttons": screen.buttons,
            "input_field": screen.input_field,
            "display_data": {**screen.display_data, **self.transaction_data},
            "mode": self.mode,
        }
