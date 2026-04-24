"""
Action Executor — takes validated LLM actions and executes them against 
the kiosk state machine. Returns results to send back to the frontend.
"""
import logging
import json
from typing import List, Optional
from execution.kiosk_state import KioskStateMachine
from safety.validators import SafetyValidator

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Processes validated LLM actions into concrete kiosk state changes."""

    def __init__(self, kiosk: KioskStateMachine):
        self.kiosk = kiosk
        self.safety = SafetyValidator()

    def execute_actions(self, actions: List[dict]) -> dict:
        """
        Execute all actions from the LLM response.
        Returns a result dict with screen_update and any errors.
        """
        results = {
            "screen_updated": False,
            "new_screen": None,
            "adaptations_applied": [],
            "errors": [],
        }

        for action in actions:
            action_type = action.get("type")

            if action_type == "kiosk_command":
                self._execute_kiosk_command(action, results)
            elif action_type == "ui_adaptation":
                results["adaptations_applied"].append(action.get("adaptations", {}))
            elif action_type == "proactive_suggestion":
                # If suggestion has an auto-apply action, queue it
                apply_action = action.get("apply_action")
                if apply_action and apply_action.get("type") == "ui_adaptation":
                    results["adaptations_applied"].append(apply_action.get("adaptations", {}))
            # speech_output is handled directly by the frontend

        return results

    def _execute_kiosk_command(self, action: dict, results: dict):
        """Execute a kiosk navigation/control command."""
        command = action.get("command", "").upper()
        target = action.get("target_screen", "")
        params = action.get("parameters", {})

        logger.info(f"Executing kiosk command: {command}, target={target}, params={params}")

        # ─── Navigation Commands ───
        if command == "NAVIGATE" and target:
            # Fuzzy match screen IDs (LLM sometimes adds _screen, uses dashes, etc.)
            resolved = self._resolve_screen_id(target)
            success = self.kiosk.navigate_to(resolved)
            if success:
                results["screen_updated"] = True
                results["new_screen"] = self.kiosk.to_frontend_dict()
            else:
                results["errors"].append(f"Cannot navigate to '{target}' from '{self.kiosk.current_screen_id}'")

        elif command == "GO_BACK":
            self.kiosk.go_back()
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "GO_HOME" or command == "NEW_TRANSACTION":
            self.kiosk.navigate_to("welcome")
            self.kiosk.transaction_data = {}
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        # ─── ATM-Specific Commands ───
        elif command == "START_TRANSACTION":
            self.kiosk.navigate_to("main_menu")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "SELECT_WITHDRAWAL":
            self.kiosk.navigate_to("withdrawal")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "SELECT_BALANCE":
            self.kiosk.transaction_data["pending_action"] = "balance_display"
            self.kiosk.navigate_to("enter_pin")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "SELECT_STATEMENT":
            self.kiosk.transaction_data["pending_action"] = "statement_display"
            self.kiosk.navigate_to("enter_pin")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command.startswith("SET_AMOUNT_"):
            amount_str = command.replace("SET_AMOUNT_", "")
            try:
                amount = int(amount_str)
                valid, msg = self.safety.validate_amount(amount)
                if valid:
                    self.kiosk.transaction_data["amount"] = amount
                    self.kiosk.navigate_to("enter_pin")
                    results["screen_updated"] = True
                    results["new_screen"] = self.kiosk.to_frontend_dict()
                else:
                    results["errors"].append(msg)
            except ValueError:
                results["errors"].append(f"Invalid amount: {amount_str}")

        elif command == "SUBMIT_AMOUNT":
            amount = params.get("amount")
            if amount:
                try:
                    amount = int(amount)
                    valid, msg = self.safety.validate_amount(amount)
                    if valid:
                        self.kiosk.transaction_data["amount"] = amount
                        self.kiosk.navigate_to("enter_pin")
                        results["screen_updated"] = True
                        results["new_screen"] = self.kiosk.to_frontend_dict()
                    else:
                        results["errors"].append(msg)
                except (ValueError, TypeError):
                    results["errors"].append("Please enter a valid number")

        elif command == "SUBMIT_PIN":
            # Simulate PIN acceptance (always succeeds in prototype)
            self.kiosk.transaction_data["pin_verified"] = True
            
            # Route to the right screen based on what the user was doing
            pending = self.kiosk.transaction_data.get("pending_action", "")
            if pending == "balance_display":
                self.kiosk.navigate_to("balance_display")
            elif pending == "statement_display":
                self.kiosk.navigate_to("statement_display")
            elif self.kiosk.transaction_data.get("amount"):
                self.kiosk.navigate_to("processing")
            else:
                self.kiosk.navigate_to("processing")
            
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "CASH_COLLECTED" or command == "PRINT_RECEIPT" or command == "NO_RECEIPT":
            if command == "CASH_COLLECTED":
                self.kiosk.navigate_to("receipt")
            else:
                self.kiosk.navigate_to("thank_you")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "PROCESS_TRANSACTION":
            # Move from processing → dispensing
            self.kiosk.navigate_to("dispensing")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        # ─── Hospital-Specific Commands ───
        elif command == "SELECT_TOKEN":
            self.kiosk.navigate_to("department_select")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "SELECT_APPOINTMENT":
            self.kiosk.navigate_to("appointment_check")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command.startswith("SELECT_DEPT_"):
            dept = command.replace("SELECT_DEPT_", "").title()
            self.kiosk.transaction_data["department"] = dept
            self.kiosk.navigate_to("doctor_select")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command.startswith("SELECT_DOCTOR_"):
            doctor_names = {
                "SELECT_DOCTOR_1": "Dr. Sharma",
                "SELECT_DOCTOR_2": "Dr. Patel",
                "SELECT_DOCTOR_3": "Dr. Kumar",
            }
            doctor = doctor_names.get(command, "Doctor")
            self.kiosk.transaction_data["doctor"] = doctor
            self.kiosk.transaction_data["token_number"] = f"A-{self.kiosk.transaction_data.get('token_seq', 42):03d}"
            self.kiosk.navigate_to("token_generated")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "GENERATE_TOKEN":
            self.kiosk.transaction_data["token_number"] = f"A-{self.kiosk.transaction_data.get('token_seq', 42):03d}"
            self.kiosk.navigate_to("token_generated")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "PRINT_TOKEN":
            self.kiosk.navigate_to("thank_you")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "CHECK_APPOINTMENT":
            self.kiosk.navigate_to("appointment_details")
            results["screen_updated"] = True
            results["new_screen"] = self.kiosk.to_frontend_dict()

        elif command == "WITHDRAW" or command == "WITHDRAWAL":
            # LLM might send WITHDRAW with an amount in parameters
            amount = params.get("amount")
            if amount:
                try:
                    amount = int(amount)
                    valid, msg = self.safety.validate_amount(amount)
                    if valid:
                        self.kiosk.transaction_data["amount"] = amount
                        self.kiosk.navigate_to("enter_pin")
                        results["screen_updated"] = True
                        results["new_screen"] = self.kiosk.to_frontend_dict()
                    else:
                        results["errors"].append(msg)
                except (ValueError, TypeError):
                    results["errors"].append("Invalid withdrawal amount")
            else:
                # No amount specified, go to withdrawal screen
                self.kiosk.navigate_to("withdrawal")
                results["screen_updated"] = True
                results["new_screen"] = self.kiosk.to_frontend_dict()

        else:
            logger.warning(f"Unknown kiosk command: {command}")
            results["errors"].append(f"Unknown command: {command}")

    def _resolve_screen_id(self, raw_target: str) -> str:
        """Fuzzy-match an LLM-provided screen name to a real screen ID."""
        screens = self.kiosk.get_screens()
        
        # Direct match
        if raw_target in screens:
            return raw_target
        
        # Normalize: lowercase, strip _screen suffix, replace dashes/spaces with underscores
        cleaned = raw_target.lower().strip()
        cleaned = cleaned.replace("-", "_").replace(" ", "_")
        cleaned = cleaned.replace("_screen", "").replace("_page", "")
        
        if cleaned in screens:
            return cleaned
        
        # Partial match: find the screen whose ID is contained in the target
        for screen_id in screens:
            if screen_id in cleaned or cleaned in screen_id:
                logger.info(f"Fuzzy matched '{raw_target}' → '{screen_id}'")
                return screen_id
        
        logger.warning(f"Could not resolve screen ID: {raw_target}")
        return raw_target

