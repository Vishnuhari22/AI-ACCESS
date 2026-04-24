"""
Safety Validators — enforces allowlists, amount limits, rate limiting,
and other safety checks before kiosk commands are executed.
"""
import logging
import time
from typing import Tuple

logger = logging.getLogger(__name__)


class SafetyValidator:
    """Validates kiosk operations for safety and correctness."""

    # ATM constraints
    MIN_WITHDRAWAL = 100
    MAX_WITHDRAWAL = 25000
    VALID_DENOMINATIONS = [100, 200, 500, 1000, 2000, 5000]
    MAX_TRANSACTIONS_PER_SESSION = 5

    # Rate limiting
    MIN_COMMAND_INTERVAL_MS = 500  # Minimum time between commands

    def __init__(self):
        self.transaction_count = 0
        self.last_command_time = 0

    def validate_amount(self, amount: int) -> Tuple[bool, str]:
        """Validate a withdrawal amount."""
        if amount < self.MIN_WITHDRAWAL:
            return False, f"Minimum withdrawal amount is ₹{self.MIN_WITHDRAWAL}"
        
        if amount > self.MAX_WITHDRAWAL:
            return False, f"Maximum withdrawal amount is ₹{self.MAX_WITHDRAWAL}"
        
        if amount % 100 != 0:
            return False, "Amount must be in multiples of ₹100"
        
        return True, ""

    def validate_command(self, command: str, kiosk_mode: str) -> Tuple[bool, str]:
        """Check if a command is valid for the current kiosk mode."""
        atm_commands = {
            "START_TRANSACTION", "SELECT_WITHDRAWAL", "SELECT_BALANCE", "SELECT_STATEMENT",
            "SET_AMOUNT_500", "SET_AMOUNT_1000", "SET_AMOUNT_2000", "SET_AMOUNT_5000",
            "ENTER_CUSTOM_AMOUNT", "SUBMIT_AMOUNT", "SUBMIT_PIN",
            "CASH_COLLECTED", "PRINT_RECEIPT", "NO_RECEIPT", "PROCESS_TRANSACTION",
            "NAVIGATE", "GO_BACK", "GO_HOME", "NEW_TRANSACTION",
        }
        hospital_commands = {
            "SELECT_TOKEN", "SELECT_APPOINTMENT",
            "SELECT_DEPT_CARDIOLOGY", "SELECT_DEPT_OPHTHALMOLOGY", "SELECT_DEPT_ORTHOPEDICS",
            "SELECT_DEPT_GENERAL", "SELECT_DEPT_ENT",
            "SELECT_DOCTOR_1", "SELECT_DOCTOR_2", "SELECT_DOCTOR_3",
            "GENERATE_TOKEN", "PRINT_TOKEN", "CHECK_APPOINTMENT",
            "NAVIGATE", "GO_BACK", "GO_HOME", "NEW_TRANSACTION",
        }

        valid_set = atm_commands if kiosk_mode == "atm" else hospital_commands

        if command.upper() not in valid_set:
            return False, f"Command '{command}' is not valid for {kiosk_mode} mode"
        
        return True, ""

    def check_rate_limit(self) -> Tuple[bool, str]:
        """Ensure commands aren't fired too rapidly."""
        now = time.time() * 1000
        if now - self.last_command_time < self.MIN_COMMAND_INTERVAL_MS:
            return False, "Please wait a moment before the next action"
        self.last_command_time = now
        return True, ""

    def check_transaction_limit(self) -> Tuple[bool, str]:
        """Ensure session hasn't exceeded max transactions."""
        if self.transaction_count >= self.MAX_TRANSACTIONS_PER_SESSION:
            return False, f"Maximum of {self.MAX_TRANSACTIONS_PER_SESSION} transactions per session reached"
        return True, ""
