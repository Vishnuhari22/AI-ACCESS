import os
import io
import re
import json
import time
import base64
import mss
from PIL import Image
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Multi-path .env loader: checks overlay/.env, backend/.env, and project root
_ENV_PATHS = [
    os.path.join(os.path.dirname(__file__), ".env"),
    os.path.join(os.path.dirname(__file__), "..", "backend", ".env"),
    os.path.join(os.path.dirname(__file__), "..", ".env"),
]
for p in _ENV_PATHS:
    if os.path.exists(p):
        load_dotenv(p, override=False)

# --- Gemini client ---
_client = None
def get_gemini_client():
    global _client
    if _client is not None:
        return _client
    for p in _ENV_PATHS:
        if os.path.exists(p):
            load_dotenv(p, override=False)
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key and api_key != "your_gemini_api_key_here":
        try:
            _client = genai.Client(api_key=api_key)
            print("[ScreenReader] Gemini client initialized successfully.")
            return _client
        except Exception as e:
            print(f"[ScreenReader] Error initializing Gemini client: {e}")
            return None
    return None

_client = get_gemini_client()


# --- OpenAI client (fallback) ---
_openai_client = None
try:
    import openai
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        _openai_client = openai.OpenAI(api_key=openai_key)
        print("[ScreenReader] OpenAI fallback enabled.")
    else:
        print("[ScreenReader] OPENAI_API_KEY not found — OpenAI fallback disabled.")
except ImportError:
    print("[ScreenReader] openai package not installed — OpenAI fallback disabled.")

# ─────────────────────────────────────────────────────────────────────────────
# System prompt — tells Gemini exactly what JSON shape to return.
# KEY FIX: every item in 'targets' now includes its own box_2d so that
#           the virtual keypad buttons can inject clicks without a second scan.
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the UIAA Accessibility Overlay Agent.
You are observing the user's screen via a screenshot of their desktop.
The user's voice input and accessibility state will also be provided.

IMPORTANT INSTRUCTIONS FOR COORDINATE ACCURACY:
- You are looking at a screenshot of the ENTIRE monitor.
- The main application or kiosk is the large window in the center of the screen.
- IGNORE any small floating dark-themed panel (the UIAA Overlay panel) — it is part of the accessibility system, not the target application.
- IGNORE the Windows taskbar at the bottom/top of the screen.
- Focus ONLY on the main application window when identifying targets and calculating coordinates.
- Place box_2d coordinates precisely on the CENTER of each button/link text, not on its edges.
- Double-check your coordinates before returning them. Accuracy is critical — these will be used for mouse click injection.

Return ONLY a single valid JSON object — no markdown, no code fences, no extra text.

JSON Schema:
{
    "screen_description": "Short plain-English summary of what is on screen",
    "speech_response": "What the TTS engine should read aloud to the user",
    "is_sensitive": false,
    "captcha_detected": false,
    "pending_fields": ["Description of unfilled required fields, or empty array"],
    "visible_results": [
        {
            "label": "Short human-readable label (e.g., 'Kerala Express - Dep 15:30 - 3A Available')",
            "name": "Target name for clicking (e.g., 'Book Now for Kerala Express')",
            "box_2d": [ymin, xmin, ymax, xmax]
        }
    ],
    "has_more_results": false,
    "page_guidance": "Brief orientation for the user after a page change, or null",
    "expects_response": false,
    "targets": [
        {
            "name": "Label or purpose of the button, link, input field, or dropdown",
            "type": "button | input | dropdown | link | text",
            "box_2d": [ymin, xmin, ymax, xmax],
            "current_value": "Current text or selected option if any, else empty string",
            "placeholder": "Placeholder or hint if any, else empty string",
            "options": ["List of visible or known options if dropdown/radio, else []"]
        }
    ],
    "selected_targets": [
        {
            "name": "The target(s) matched to the user's request",
            "box_2d": "[ymin, xmin, ymax, xmax] or null if purely scrolling/keyboard",
            "type_text": "Text to type into the field after clicking, or null",
            "press_keys": ["key1", "key2"],
            "follow_up": "Description of what to click next after this action opens a menu/dropdown, or null",
            "scroll_direction": "Set to 'down' or 'up' ONLY if you need to scroll the page BEFORE finding the target, otherwise null",
            "requires_confirmation": false
        }
    ]
}

Rules:
- box_2d values are integers 0-1000 representing [ymin, xmin, ymax, xmax] on a 1000x1000 grid.
- The grid maps to the FULL screenshot: (0,0) is top-left of the monitor, (1000,1000) is bottom-right.
- If you need to scroll to find something not visible, return a dummy box_2d like [500,500,500,500] and set scroll_direction to 'down' or 'up'.
- is_sensitive: set to true when the speech_response contains private data such as PINs, passwords, account numbers, balances, or OTPs. Otherwise false.
- captcha_detected: set to true if there is a CAPTCHA challenge visible. Set speech_response to instruct the user to complete it manually and say 'done'.
- requires_confirmation: set to true for high-risk actions (e.g., Pay, Submit, Confirm, Transfer, Delete, Book Ticket). The overlay will ask the user for confirmation before clicking.

CONVERSATIONAL RULES:
- If you ask the user a question in your speech_response (e.g. "Which time do you prefer?", "Would you like to book this?"), you MUST set "expects_response" to true.
- If you set "expects_response" to true, DO NOT execute any actions that depend on their answer. Set selected_targets to [] until they reply.

SCROLLING & KEYBOARD ONLY:
- If the user asks to "scroll down", "go back", or "press enter", and NO click is needed, you can return a target with "box_2d": null, and set "scroll_direction" (e.g. "down") or "press_keys" (e.g. ["escape"]). The system will execute the scroll/keys without clicking.
- EVERY item in 'targets' MUST have its own box_2d. Do not omit any.
- COMPREHENSIVE FIELD EXTRACTION: You MUST extract ALL interactive elements visible on the main page without missing any: all text input fields, search boxes, dropdowns, date pickers, check boxes, and major action buttons. For each input or dropdown, provide its descriptive 'name', 'type' ("input", "dropdown", "button", "link"), 'placeholder', 'current_value', and known 'options' if available.
- Make bounding boxes TIGHT around the clickable element — do not use overly large boxes.
- Leave 'selected_targets' as an empty array [] when the user is only asking what is available (not requesting an action).
- Never return null for selected_targets — always use an empty array [].
- When the user just wants to click a button or link with no text entry, set "type_text" to null.

TEXT INPUT RULES:
- When the user's voice input implies typing into a field (e.g. "from Chengannur", "enter 5000", "search for trains"), set "type_text" to ONLY the value to type (e.g. "Chengannur", "5000", "trains").
- The system will automatically clear any existing text in the field before typing.
- MULTIPLE ACTIONS: If the user request involves filling multiple fields (e.g. 'from X to Y'), you MUST return multiple objects in selected_targets (e.g. one for From, one for To). The system will execute them in order.
- IMPORTANT: Identify the CORRECT target field from context. "from Chengannur" means the FROM/SOURCE field. "to Trivandrum" means the TO/DESTINATION field. Do NOT just type into whatever field is currently active — click the RIGHT field first.

KEYBOARD ACTIONS (press_keys):
- press_keys is an array of keyboard keys to press AFTER the click and optional typing are done.
- Supported keys: "enter", "tab", "down", "up", "left", "right", "escape", "backspace", "delete", "space", "home", "end", "pageup", "pagedown"
- Special: "wait:N" pauses for N milliseconds (e.g. "wait:1000" waits 1 second).
- Set press_keys to null or omit it when no keyboard action is needed.

CRITICAL RULES FOR DROPDOWNS AND AUTOCOMPLETE:
- For AUTOCOMPLETE/SEARCH input fields (station name, city, etc.): after setting type_text, set follow_up to describe which suggestion to select (e.g. "Select CHENGANNUR - CGNR from the autocomplete suggestions" or "Click the first matching station suggestion"). The system will type the text, wait for the suggestion dropdown to appear, take a NEW screenshot, and click the correct suggestion. Do NOT use press_keys for autocomplete — many websites require an actual click on the suggestion.
- For DROPDOWN/SELECT menus (class selection, quota, etc.): You CANNOT see the dropdown options before they open. Set follow_up to describe what option to click (e.g. "Click on Third AC (3A)" or "Select Second AC (2A)"). The system will click the dropdown, wait for it to open, take a NEW screenshot, and use your follow_up instruction to find and click the correct option.
- Set follow_up to null when no second action is needed (most cases — buttons, links, etc.).
- For DATE PICKERS: click the date input field. Use press_keys to navigate if needed.
- NEVER guess how many arrow-down presses are needed for a dropdown — you cannot see the options.

FORM COMPLETION CHECK:
- Before including a Submit/Search/Find/Book button in selected_targets, CHECK if there are required form fields that appear empty or set to default values.
- If you detect unfilled required fields (e.g., date field showing today's date on a travel booking form), DO NOT include the submit button in selected_targets. Instead:
  1. Set selected_targets to []
  2. Set pending_fields to describe what's missing
  3. Set speech_response to ask the user for the missing information
- Only include Submit/Search when ALL visible required fields appear filled with user-intended values.

RESULT LISTS:
- When the screen shows a list of results (trains, flights, products), populate "visible_results" with each distinct result visible. Include a human-readable label (train name + time + availability).
- Set "has_more_results" to true if there appears to be a scroll area indicating more results below.
- If availability is not loaded (shows "Refresh"), mention this in the label.
- Set visible_results to [] when not showing a results list.

PAGE GUIDANCE:
- When the user's action will cause a page navigation or major UI change (clicking Search, Submit, Next), set page_guidance to a brief 1-2 sentence orientation describing:
  1. What the new page/section shows
  2. Any non-obvious required actions (e.g., "Seat availability needs to be refreshed")
  3. A suggested next step
- Set page_guidance to null for simple in-page actions.
"""

# Gemini models to try in order (flash/lite only — Pro is no longer free tier)
_MODEL_PRIORITY = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

# OpenAI models to try as fallback (when ALL Gemini models fail)
_OPENAI_MODEL_PRIORITY = ["gpt-4o-mini", "gpt-4o"]

# Request timeout in seconds
_REQUEST_TIMEOUT = 30

# Max retries on rate-limit (429) errors
_MAX_RATE_LIMIT_RETRIES = 2


def capture_screen(hide_window=None):
    """Captures the primary monitor and returns a PIL Image and monitor info dict.
    
    Args:
        hide_window: Optional Tkinter root window to temporarily hide before
                     capturing, so the overlay panel doesn't appear in the 
                     screenshot and confuse the AI's coordinate detection.
    """
    import threading as _threading

    # Temporarily hide the overlay window so it doesn't appear in the screenshot.
    # IMPORTANT: Tkinter is NOT thread-safe — both withdraw and deiconify MUST be
    # dispatched to the main thread via after().  Calling withdraw() directly from
    # a background thread caused the "invisible then reappear" UI flash.
    was_visible = False
    if hide_window:
        try:
            was_visible = hide_window.winfo_viewable()
            if was_visible:
                _hide_event = _threading.Event()
                def _do_hide():
                    hide_window.withdraw()
                    _hide_event.set()
                hide_window.after(0, _do_hide)
                _hide_event.wait(timeout=0.5)   # block until main thread hides it
                time.sleep(0.05)                # small buffer for window manager
        except Exception:
            pass

    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]       # primary monitor
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            return img, monitor
    finally:
        # Restore the overlay window (also via main thread)
        if hide_window and was_visible:
            try:
                _show_event = _threading.Event()
                def _do_show():
                    hide_window.deiconify()
                    _show_event.set()
                hide_window.after(0, _do_show)
                _show_event.wait(timeout=0.5)   # wait for restore before continuing
            except Exception:
                pass


def wait_for_stable_screen(timeout: float = 4.0, interval: float = 0.3, threshold: float = 0.04) -> bool:
    """
    Waits until the target screen stops changing (e.g., page load finishes).
    Runs passively without hiding or blinking the overlay window.
    
    Args:
        timeout: Maximum time to wait in seconds (default 4s).
        interval: Time between comparison snapshots (default 0.3s).
        threshold: Fraction of pixels that must change to be considered 'unstable'.
        
    Returns:
        True if screen stabilized, False if timed out.
    """
    from PIL import ImageChops

    start_time = time.time()
    # Grab baseline without hiding overlay (avoids UI blinking)
    img1, _ = capture_screen(hide_window=None)
    
    while time.time() - start_time < timeout:
        time.sleep(interval)
        img2, _ = capture_screen(hide_window=None)
        
        diff = ImageChops.difference(img1, img2)
        bbox = diff.getbbox()
        if not bbox:
            return True
        
        # Downsample to 100x100 for fast difference metric
        diff_small = diff.resize((100, 100))
        diff_pixels = list(diff_small.getdata())
        changed_pixels = sum(1 for p in diff_pixels if any(c > 15 for c in p))
        diff_ratio = changed_pixels / 10000.0
        
        if diff_ratio < threshold:
            return True
            
        img1 = img2
        
    return False



def _strip_markdown_fences(text: str) -> str:
    """Remove any markdown code fences Gemini may wrap its JSON in."""
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*',     '', text)
    text = re.sub(r'\s*```$',     '', text)
    return text.strip()


def _normalise_response(parsed: dict) -> dict:
    """Normalise selected_targets to always be a list of dicts with box_2d.

    Handles all known edge cases from Gemini:
    - selected_targets missing entirely
    - selected_targets is the string "null"
    - selected_targets is None
    - selected_targets is a single dict instead of a list
    - Old schema: selected_target (singular) instead of selected_targets
    """
    # --- Normalise selected_targets ---
    st = parsed.get("selected_targets")

    # Handle string "null" or "none"
    if isinstance(st, str):
        st = None

    # Handle None / missing
    if st is None:
        st = []

    # Handle single dict instead of list
    if isinstance(st, dict):
        st = [st]

    # Ensure it's a list
    if not isinstance(st, list):
        st = []

    # --- Fallback: old singular schema ---
    old_target = parsed.get("selected_target")
    if old_target and isinstance(old_target, dict) and not st:
        st = [old_target]

    # Filter out entries without valid box_2d
    cleaned = []
    for item in st:
        if isinstance(item, dict) and item.get("box_2d"):
            box = item["box_2d"]
            if isinstance(box, list) and len(box) == 4:
                cleaned.append(item)

    parsed["selected_targets"] = cleaned

    # --- Normalise targets too ---
    targets = parsed.get("targets")
    if not isinstance(targets, list):
        parsed["targets"] = []

    # Ensure screen_description, speech_response, and is_sensitive exist
    parsed.setdefault("screen_description", "")
    parsed.setdefault("speech_response", "")
    parsed.setdefault("is_sensitive", False)

    return parsed


def analyze_screen_and_intent(screenshot: Image.Image,
                               user_voice_text: str,
                               user_state: dict,
                               conversation_context: list = None) -> dict | None:
    """Sends screenshot + voice text to Gemini Vision and returns parsed JSON."""
    client = get_gemini_client()
    if client is None:
        print("[ScreenReader] No Gemini client — API key missing.")
        return None

    # Convert PIL image → raw PNG bytes for the new SDK
    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    context_str = ""
    if conversation_context:
        context_str = "Recent Interaction History:\n" + "\n".join(f"- {c}" for c in conversation_context)

    contents = [
        SYSTEM_PROMPT,
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        f"User State Context: {json.dumps(user_state)}",
        context_str,
        f"User Voice Request: '{user_voice_text}'",
    ]

    last_error = None
    for model_name in _MODEL_PRIORITY:
        # Rate-limit retry loop for this model
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            try:
                start_t = time.time()
                print(f"[ScreenReader] Calling {model_name}" +
                      (f" (attempt {attempt+1})..." if attempt > 0 else "..."))

                response = _client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.2,      # Low temperature for reliable JSON
                        max_output_tokens=2048,
                    ),
                )

                elapsed = time.time() - start_t
                text = response.text.strip()
                text = _strip_markdown_fences(text)

                print(f"[ScreenReader] {model_name} responded in {elapsed:.1f}s ({len(text)} chars)")

                parsed = json.loads(text)
                return _normalise_response(parsed)

            except json.JSONDecodeError as e:
                print(f"[ScreenReader] JSON parse error ({model_name}): {e}")
                last_error = e

                # --- RETRY ONCE with correction prompt ---
                try:
                    print(f"[ScreenReader] Retrying {model_name} with correction...")
                    retry_contents = contents + [
                        f"Your previous response was not valid JSON. The error was: {e}\n"
                        f"Please return ONLY a valid JSON object matching the schema above. "
                        f"No markdown, no code fences, no explanation."
                    ]
                    retry_response = _client.models.generate_content(
                        model=model_name,
                        contents=retry_contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.1,
                            max_output_tokens=2048,
                        ),
                    )
                    retry_text = retry_response.text.strip()
                    retry_text = _strip_markdown_fences(retry_text)
                    parsed = json.loads(retry_text)
                    print(f"[ScreenReader] Retry succeeded!")
                    return _normalise_response(parsed)
                except Exception as retry_err:
                    print(f"[ScreenReader] Retry also failed: {retry_err}")
                    last_error = retry_err
                    # If the error during JSON retry was actually a server error (503/429), 
                    # bubble it up so the main exception handler can retry it properly
                    if "503" in str(retry_err) or "429" in str(retry_err) or "UNAVAILABLE" in str(retry_err):
                        raise retry_err

                break   # Don't retry rate-limit if it was purely a JSON problem

            except Exception as e:
                error_str = str(e)
                last_error = e

                # Handle 429 rate-limit: wait and retry the same model
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    # Extract retry delay from error message if available
                    wait_time = 10  # default wait
                    delay_match = re.search(r'retry(?:Delay)?.*?(\d+)', error_str)
                    if delay_match:
                        wait_time = min(int(delay_match.group(1)), 60)

                    if attempt < _MAX_RATE_LIMIT_RETRIES:
                        print(f"[ScreenReader] Rate limited on {model_name}. "
                              f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                        continue  # Retry same model
                    else:
                        print(f"[ScreenReader] Rate limit exhausted for {model_name}.")
                        break  # Try next model

                # Handle 503 server overload: wait briefly and retry (transient)
                elif "503" in error_str or "UNAVAILABLE" in error_str:
                    if attempt < _MAX_RATE_LIMIT_RETRIES:
                        print(f"[ScreenReader] {model_name} temporarily unavailable. "
                              f"Retrying in 5s...")
                        time.sleep(5)
                        continue  # Retry same model
                    else:
                        print(f"[ScreenReader] {model_name} still unavailable after retries.")
                        break  # Try next model

                # Handle 404: model doesn't exist — skip to next model immediately
                elif "404" in error_str or "NOT_FOUND" in error_str:
                    print(f"[ScreenReader] Model {model_name} not found — skipping.")
                    break  # Try next model

                else:
                    print(f"[ScreenReader] Error with model {model_name}: {e}")
                    break  # Try next model

    print(f"[ScreenReader] All Gemini models failed. Last error: {last_error}")

    # ──────────────────────────────────────────────────────────────────
    # FALLBACK: Try OpenAI Vision API
    # ──────────────────────────────────────────────────────────────────
    if _openai_client is not None:
        openai_result = _call_openai_fallback(image_bytes, user_voice_text, user_state)
        if openai_result:
            return openai_result
        print("[ScreenReader] OpenAI fallback also failed.")
    else:
        print("[ScreenReader] No OpenAI fallback available.")

    return None


def analyze_follow_up(screenshot: Image.Image,
                      follow_up_instruction: str) -> dict | None:
    """Takes a second screenshot and asks Gemini to find a specific element.

    Used after opening a dropdown/menu — the follow_up_instruction describes
    what option to click (e.g. "Click on Third AC (3A)").

    Returns a dict with 'box_2d' for the target, or None on failure.
    """
    if _client is None:
        return None

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    follow_up_prompt = f"""You are looking at a screenshot of a desktop. A dropdown menu or popup is now open on screen.

Your task: {follow_up_instruction}

Find the EXACT option in the visible dropdown/menu and return its coordinates.
If the option is not visible (needs scrolling), look for a scroll area and return the coordinates of
the option that is closest to what was requested. If you need to scroll down to find it,
return the coordinates of the scrollbar's down area or the last visible item.

Return ONLY a JSON object:
{{
    "found": true,
    "name": "exact text of the option found",
    "box_2d": [ymin, xmin, ymax, xmax]
}}

Or if the option is not visible at all:
{{
    "found": false,
    "name": null,
    "box_2d": null
}}

box_2d values are integers 0-1000 on a 1000x1000 grid mapped to the full screenshot.
Place coordinates precisely on the CENTER of the target option text.
"""

    contents = [
        follow_up_prompt,
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
    ]

    # Try only the fastest model for follow-up (speed matters)
    for model_name in _MODEL_PRIORITY[:1]:
        try:
            start_t = time.time()
            print(f"[ScreenReader] Follow-up call to {model_name}...")

            response = _client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=512,
                ),
            )

            elapsed = time.time() - start_t
            text = response.text.strip()
            text = _strip_markdown_fences(text)

            print(f"[ScreenReader] Follow-up responded in {elapsed:.1f}s")

            parsed = json.loads(text)
            if parsed.get("found") and parsed.get("box_2d"):
                return parsed
            else:
                print(f"[ScreenReader] Follow-up: option not found")
                return None

        except Exception as e:
            print(f"[ScreenReader] Follow-up error: {e}")
            return None

    return None


def analyze_dropdown_options(screenshot: Image.Image,
                             follow_up_instruction: str,
                             user_original_text: str) -> dict | None:
    """Calls Gemini to extract ALL visible dropdown options.
    
    Used for ambiguous dropdowns (like autocomplete station names).
    Returns a dict with 'options' (list) and 'best_match' (dict or null),
    or None on failure.
    """
    if _client is None:
        return None

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    prompt = f"""You are looking at a screenshot of a desktop. An autocomplete dropdown menu or popup is now open on screen.

User's original intent: '{user_original_text}'
Follow-up instruction: '{follow_up_instruction}'

Find ALL visible options in the dropdown/menu.
If one of the options clearly matches the user's original intent better than the others (e.g. they said 'Ernakulam Junction' and an option says 'ERNAKULAM JN - ERS'), set it as best_match. If it's ambiguous (they said 'Ernakulam' and both 'Town' and 'Junction' exist), set best_match to null.

Return ONLY a JSON object:
{{
    "options": [
        "exact text of option 1",
        "exact text of option 2"
    ],
    "best_match": "exact text of the matched option" // or null if ambiguous or no clear match
}}
"""

    contents = [
        prompt,
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
    ]

    for model_name in _MODEL_PRIORITY[:1]:
        try:
            start_t = time.time()
            print(f"[ScreenReader] Dropdown analyze call to {model_name}...")

            response = _client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=1024,
                ),
            )

            elapsed = time.time() - start_t
            text = response.text.strip()
            text = _strip_markdown_fences(text)
            print(f"[ScreenReader] Dropdown analyze responded in {elapsed:.1f}s")

            parsed = json.loads(text)
            if parsed.get("options"):
                return parsed
            return None
        except Exception as e:
            print(f"[ScreenReader] Dropdown analyze error: {e}")
            return None

    return None


def _call_openai_fallback(image_bytes: bytes,
                          user_voice_text: str,
                          user_state: dict) -> dict | None:
    """Calls OpenAI Vision API as a fallback when Gemini is unavailable."""
    # Encode image as base64 for OpenAI API
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{b64_image}",
                        "detail": "high"
                    }
                },
                {
                    "type": "text",
                    "text": (
                        f"User State Context: {json.dumps(user_state)}\n"
                        f"User Voice Request: '{user_voice_text}'"
                    )
                }
            ]
        }
    ]

    last_error = None
    for model_name in _OPENAI_MODEL_PRIORITY:
        try:
            start_t = time.time()
            print(f"[ScreenReader] Calling OpenAI {model_name}...")

            response = _openai_client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.2,
                max_tokens=2048,
                timeout=_REQUEST_TIMEOUT,
            )

            elapsed = time.time() - start_t
            text = response.choices[0].message.content.strip()
            text = _strip_markdown_fences(text)

            print(f"[ScreenReader] OpenAI {model_name} responded in {elapsed:.1f}s ({len(text)} chars)")

            parsed = json.loads(text)
            return _normalise_response(parsed)

        except json.JSONDecodeError as e:
            print(f"[ScreenReader] OpenAI JSON parse error ({model_name}): {e}")
            last_error = e
            # Try next OpenAI model
        except Exception as e:
            error_str = str(e)
            last_error = e
            print(f"[ScreenReader] OpenAI error ({model_name}): {e}")

            # On rate limit, wait and retry
            if "429" in error_str or "rate_limit" in error_str.lower():
                print(f"[ScreenReader] OpenAI rate limited. Waiting 10s...")
                time.sleep(10)
                continue

    print(f"[ScreenReader] All OpenAI models failed. Last error: {last_error}")
    return None


def verify_anchor(target_name: str, expected_box: list,
                  monitor_info: dict, hide_window=None) -> list | None:
    """Re-verify a target's position immediately before clicking.

    Takes a fresh screenshot and asks Gemini to locate the specific element,
    returning updated box_2d coordinates.  This prevents coordinate drift
    caused by scrolling between the original screenshot and click injection.

    Returns:
        Updated [ymin, xmin, ymax, xmax] list, or None if not found.
    """
    if _client is None:
        return expected_box  # Can't verify — use original

    img, _ = capture_screen(hide_window=hide_window)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    prompt = f"""Find the UI element labelled \"{target_name}\" on this screenshot.
Return ONLY a JSON object:
{{
    "found": true,
    "box_2d": [ymin, xmin, ymax, xmax]
}}
Or if not visible: {{"found": false, "box_2d": null}}
box_2d integers 0-1000 on 1000x1000 grid. Place on element CENTER."""

    contents = [
        prompt,
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
    ]

    model = _MODEL_PRIORITY[0]
    try:
        response = _client.models.generate_content(
            model=model, contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1, max_output_tokens=256,
            ),
        )
        text = _strip_markdown_fences(response.text.strip())
        parsed = json.loads(text)
        if parsed.get("found") and parsed.get("box_2d"):
            print(f"[ScreenReader] Anchor verified: '{target_name}' at {parsed['box_2d']}")
            return parsed["box_2d"]
        else:
            print(f"[ScreenReader] Anchor lost: '{target_name}' not found")
            return None
    except Exception as e:
        print(f"[ScreenReader] Anchor verify error: {e}")
        return expected_box  # Fallback to original coords


def analyze_proactive(screenshot: Image.Image,
                      reason: str) -> dict | None:
    """Proactive analysis — triggered when the user appears stuck.

    Args:
        screenshot: Current screen capture.
        reason: Why the monitor triggered (e.g. 'inactive 30s').

    Returns:
        Dict with 'speech_response' and 'screen_description', or None.
    """
    if _client is None:
        return None

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    prompt = f"""You are the UIAA Accessibility Overlay Agent.
The user has NOT spoken, but the system detected: {reason}.
Look at the screenshot and provide helpful, proactive guidance.

Return ONLY a JSON object:
{{
    "screen_description": "What is currently on screen",
    "speech_response": "A brief, friendly offer of help (1-2 sentences)",
    "is_sensitive": false
}}

Be concise and empathetic. Example: 'It looks like you\'re on the payment page.
Would you like me to help you complete this transaction?'"""

    contents = [
        prompt,
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
    ]

    model = _MODEL_PRIORITY[0]
    try:
        response = _client.models.generate_content(
            model=model, contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4, max_output_tokens=512,
            ),
        )
        text = _strip_markdown_fences(response.text.strip())
        return json.loads(text)
    except Exception as e:
        print(f"[ScreenReader] Proactive analysis error: {e}")
        return None


AGENT_PROMPT = """You are the UIAA Accessibility Agent.
You operate in a continuous loop to complete the user's ultimate goal on ANY application or website following the browser-use principle: Observe -> Think -> Act (Atomic) -> Evaluate.
Given the current screenshot, the user's goal, and the history of actions you just took, 
decide the SINGLE next best action to take.

JSON Schema:
{
    "evaluation_previous_action": "Evaluate the result of the previous action based on visual evidence: SUCCESS | FAILED | UNKNOWN. Explain what changed or if the field/popup remained unchanged.",
    "task_memory": {
        "completed": ["List of steps/fields confirmed completed"],
        "in_progress": "Current field or action being completed",
        "pending": ["Remaining fields/steps to complete"]
    },
    "form_analysis": {
        "identified_fields": ["List of all interactive fields and UI choices (e.g. date tabs, time slots, seat maps) relevant to the task"],
        "user_provided_values": ["Fields and preferences the user explicitly provided in their goal"],
        "missing_or_default_values": ["Fields that are empty, or have system default values that the user didn't explicitly authorize"],
        "unresolved_preferences": ["Any real-world choices presented on screen (dates, times, locations, seats, sizes) that the user hasn't specified"]
    },
    "thought_process": "Explain your reasoning based on evaluation_previous_action, task_memory, form_analysis, and history.",
    "action_type": "CLICK | TYPE | SCROLL_DOWN | SCROLL_UP | DONE | ERROR | ASK_USER | READ_OPTIONS",
    "target_name": "Short descriptive name of the element you are targeting (if clicking/typing).",
    "target_box_2d": [ymin, xmin, ymax, xmax], 
    "type_text": "Text to type if action_type is TYPE, otherwise null",
    "press_keys": ["enter", "tab", "escape"] or null,
    "speech_to_user": "What to narrate or ask the user (e.g., questions, reading options).",
    "options": ["Option 1", "Option 2"] or null,
    "error_reason": "If action_type is ERROR, explain why."
}

Rules:
- You must output exactly ONE action per turn.
- **ATOMIC ACTIONS & AUTOCOMPLETE (CRITICAL)**:
  - When typing into an input field (`TYPE`), the system will clear and type your text, but will **NOT automatically press Enter**.
  - This leaves autocomplete suggestions, airport/station lists, or datepickers open so you can inspect them on the NEXT turn.
  - On the turn following a `TYPE`, inspect the open suggestion list: if unambiguous, emit a `CLICK` on the matching suggestion item. Do NOT assume typing the text is enough; modern sites require clicking the dropdown suggestion!
  - Only specify `"press_keys": ["enter"]` if you explicitly want to submit without clicking suggestions.
- **EVALUATE BEFORE ADVANCING**:
  - In `evaluation_previous_action`, verify whether the previous turn actually took effect on the screen.
  - If text did not register or a dropdown didn't open, mark it `FAILED` and adjust coordinates or re-click.
  - If the same action fails 2 times consecutively, switch strategy (e.g. click directly on the option or ask the user).
- **MULTI-MATCH AMBIGUITY & DISAMBIGUATION PROTOCOL (CRITICAL)**:
  - Whenever an autocomplete menu, suggestion list, dropdown, or search results list appears on screen, examine all visible matches against the user's intent.
  - If there are multiple distinct interpretations or entities (e.g. "Kochi, Kerala (India)" vs "Kochi, Japan"; "Springfield, IL" vs "Springfield, MA"; "Dr. John (Cardiology)" vs "Dr. John (Pediatrics)"):
    **YOU MUST NOT GUESS OR DEFAULT TO THE FIRST HIT**.
  - Immediately return "READ_OPTIONS" or "ASK_USER".
  - In `speech_to_user`, explicitly enumerate the top distinct alternatives and ask the user to clarify (e.g., "I found two options for Kochi: 1. Cochin International Airport in India, and 2. Kochi Ryoma Airport in Japan. Which one would you prefer?").
  - Only proceed with a `CLICK` on a suggestion if the user's input unambiguously matched exactly one item or after they clarify.
- **LOGICAL CONSISTENCY CHECK**: If the user's instructions contain contradictions (e.g., they asked for a "One-Way" trip but provided a "Return Date"), DO NOT silently override their choices or get confused. Use "ASK_USER" to gently point out the contradiction and ask how they want to resolve it.
- **NO ASSUMPTIONS (UNIVERSAL PREFERENCE RULE)**: NEVER make assumptions about user preferences. If the screen forces a real-world choice (e.g., clicking a specific date tab, choosing a time slot, selecting a theatre, picking a seat from a map, choosing a product variant) and the user's goal does not explicitly dictate which one to choose, YOU MUST NOT GUESS OR PICK THE DEFAULT. Log it in `unresolved_preferences` and use "ASK_USER" to ask the user what they prefer (e.g., "I see showtimes for today and tomorrow. Which do you prefer?", or "I am at the seat map. Where would you like to sit?").
- **JUST-IN-TIME INQUIRY**: Do NOT ask the user for information about steps or choices that are not yet visible on the screen. For example, if the user asks to "buy a shirt" or "book a flight", and the current screen only has a "Proceed" or "Next" button, just click it. ONLY use "ASK_USER" to ask for a preference (like Color, Size, Date, or Shipping Method) when the actual UI for making that specific choice is visible in the current screenshot. Let the website's natural flow dictate when you ask questions.
- **READ_OPTIONS**: If a dropdown or list of choices is currently open on screen and the exact choice is ambiguous or multiple viable candidates exist, return "READ_OPTIONS". Use "speech_to_user" to read out the visible options clearly so the user can speak or select their choice.
- If the goal is fully achieved, return "DONE".
- If you are stuck, return "ERROR".
- TYPE actions will automatically clear the field before typing. You MUST provide target_box_2d for TYPE actions so the system can click the field first.
- box_2d is [ymin, xmin, ymax, xmax] on a 1000x1000 grid of the FULL screen.
- Place coordinates precisely in the CENTER of the target.
- For dropdowns: First CLICK the dropdown. On the next turn, you will see the options. If the choice is obvious and unambiguous, CLICK it. If ambiguous, use READ_OPTIONS.
"""

def analyze_agent_step(screenshot: Image.Image, goal: str, history: list) -> dict | None:
    """Stateful agent loop analyzer for single-step continuous execution."""
    if _client is None:
        return None

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    history_str = "\n".join([f"- {h}" for h in history]) if history else "None yet."
    
    prompt = f"{AGENT_PROMPT}\n\nUltimate Goal: {goal}\n\nAction History:\n{history_str}\n\nDetermine the SINGLE next action."

    contents = [
        prompt,
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
    ]

    try:
        # Use primary model (Gemini 1.5/2.5 Pro/Flash depending on config)
        model = _MODEL_PRIORITY[0] if isinstance(_MODEL_PRIORITY, list) else "gemini-2.5-pro"
        
        response = _client.models.generate_content(
            model=model, contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1, max_output_tokens=2048,
            ),
        )
        text = _strip_markdown_fences(response.text.strip())
        return json.loads(text)
    except Exception as e:
        print(f"[ScreenReader] Agent Step error: {e}")
        return None


if __name__ == "__main__":
    print("Testing Screen Reader...")
    img, mon = capture_screen()
    print(f"Captured: {img.size}")
    res = analyze_screen_and_intent(img, "What options do I have here?", {})
    print(json.dumps(res, indent=2))
