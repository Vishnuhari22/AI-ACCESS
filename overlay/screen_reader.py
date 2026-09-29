import os
import io
import re
import json
import time
from datetime import datetime
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
SYSTEM_PROMPT = """You are the UIAA Accessibility Agent controlling a web browser.
You observe the user's screen via a screenshot and help them complete tasks step-by-step.

COORDINATE RULES:
- Screenshot shows the ENTIRE monitor. IGNORE the small dark UIAA Overlay panel and Windows taskbar.
- box_2d = [ymin, xmin, ymax, xmax] integers 0-1000 on a normalised 1000×1000 grid of the full screenshot.
- Target the CENTER of the element precisely.

Return ONLY a single valid JSON object matching this schema:
{
  "form_plan": {
    "form_type": "e.g. train_booking, login, search",
    "explicit_user_values_extracted": {"field_name": "EXACT value user spoke, or null if NOT explicitly stated"},
    "required_missing": ["List all mandatory fields that map to null above"]
  },
  "observation": "What I see on the screen right now (e.g., popups, forms, loading spinners)",
  "reasoning": "Step-by-step logic. If required fields are null, I must ask. If a popup is blocking, I must close it. Otherwise, explain the action.",
  "task_status": "in_progress",
  "action": {
    "type": "click" | "type" | "select" | "scroll" | "key_press" | "wait" | "none",
    "target_description": "e.g. From station input field",
    "box_2d": [ymin, xmin, ymax, xmax],
    "text": "text to type (null if not typing)",
    "keys": ["key names for key_press"],
    "scroll_direction": "up" | "down",
    "clear_first": false,
    "requires_confirmation": false
  },
  "speech": "Brief message to speak aloud to the user",
  "is_sensitive": false,
  "expected_result": "What should change on screen after this action",
  "max_wait_ms": 3000,
  "expects_response": false
}

=== CRITICAL RULES ===

0. ABSOLUTE RULE - NEVER INVENT DATA: You may ONLY type or select values that the user has EXPLICITLY stated in their voice input or conversation replies. If the user said 'book tickets' without specifying origin, destination, date, or any other field — you MUST set task_status='needs_input' and ASK. You are FORBIDDEN from guessing, assuming, or using placeholder values like 'Mumbai', 'Delhi', or any default date. If you don't have the data, ASK for it.

1. ONE ACTION PER STEP. Never try to fill multiple fields in one response.

2. FORM PLANNING (form_plan):
   - In explicit_user_values_extracted, create a key for every required field on screen (e.g., 'From', 'To', 'Date').
   - For each key, extract the EXACT string the user spoke. If the user did NOT mention it, map it to `null`.
   - required_missing MUST contain every field that mapped to `null`.
   - For travel booking: required fields typically include origin, destination, date, class, passengers.

3. NEVER CLICK SEARCH/SUBMIT WHILE required_missing IS NON-EMPTY.
   Instead: set task_status="needs_input", action.type="none", expects_response=true.
   In speech, ask the user for ALL missing fields at once. Example:
   "I still need your travel date and preferred class. Could you tell me?"

3b. PRE-SEARCH / PRE-SUBMIT CONFIRMATION (CRITICAL ACCESSIBILITY RULE):
   NEVER click the final 'Search', 'Find Trains', 'Book', or 'Submit' button silently or automatically!
   Even when all mandatory fields (From, To, Date) are filled, travel websites have default optional fields (Class, Quota, Passengers).
   You MUST pause, set task_status="needs_input", expects_response=true, action.type="none".
   In speech, clearly summarize what is filled, mention the default values of remaining fields, and ask if you can proceed:
   Example: "I have set origin as Kochi, destination as Pune, and date as tomorrow. Class and Quota are currently set to All Classes and General. Shall I go ahead and search, or would you like to change anything?"
   ONLY click Search AFTER the user explicitly replies to proceed (e.g., "yes", "search", "go ahead", "looks good").

4. DROPDOWN / AUTOCOMPLETE HANDLING:
   - When you type into a field that triggers a dropdown (e.g., station name autocomplete):
     Step A: type the text → set task_status="in_progress" (the dropdown will appear).
     Step B (next iteration): You will see the dropdown list. Click the BEST matching option.
     If multiple similar options exist (e.g., "Trivandrum Central" vs "Trivandrum Pettah"), 
     set task_status="needs_input", expects_response=true, and ASK the user which one.

5. FORM FIELDS:
   - If a field already contains text and you need to replace it, set clear_first=true.
   - After typing, do NOT press Enter unless the field explicitly requires it.

6. DATE PICKERS / CALENDARS (ACCURACY RULES):
   - PREFER TYPING: If the date input field can be typed into directly, click the field and TYPE the date (e.g., DD/MM/YYYY or DD MMM) with clear_first=true. Typing is 100% accurate and avoids small target misclicks.
   - CALENDAR GRID CLICKS: If you must click a calendar day cell:
     * NEVER target just the tiny number glyph.
     * Your box_2d MUST cover the ENTIRE square date tile/cell so the click lands in the center of the tile.
     * Verify the month name at the top of the calendar. If the desired date is in next month, click the '>' next-month arrow first.

7. POPUPS, ADS, & BLOCKERS:
   - If a modal popup, advertisement, "Sign in", or "Special Offer" dialog is blocking the screen, your FIRST action must be to close it (look for an 'X' button, 'Skip', or 'Close'). Do not try to interact with the background form while a popup is active.

8. task_status values:
   - "in_progress": More steps needed. Keep going.
   - "needs_input": Waiting for user info. Set action.type="none" and expects_response=true.
   - "completed": Task finished. Set action.type="none" and give a summary speech.
   - "blocked": Cannot proceed (e.g., CAPTCHA, login wall).
   - "failed": Unrecoverable error.

9. expects_response: Set true ONLY when you are asking the user a question and need their answer.

10. STEP HISTORY: Review the step history carefully. It contains what was already done, what the agent asked, and what the user replied. Use user replies as input data for filling fields.

11. is_sensitive: Set to true ONLY if the speech explicitly reads out a secret credential (passwords, PINs, OTPs, CVV). NEVER set to true when asking for an OTP, routine speech, or booking assistance.

12. OTP & MULTI-BOX PIN FIELDS:
    - If you see an OTP/PIN screen, ALWAYS ask the user for the code first if you don't have it (using task_status='needs_input' and expects_response=true).
    - When you DO have the code, set action.type="type" with the exact digits.
    - Target the FIRST (left-most) digit box if there are multiple boxes. The system uses clipboard paste to auto-distribute the full code across all boxes. NEVER target individual boxes separately.
"""

# Gemini models to try in order (gemini-3.5-flash-lite has active quota; gemini-2.5-flash free daily is capped at 20)
_MODEL_PRIORITY = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

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
    """Normalise the ReAct response to ensure all expected fields exist."""
    parsed.setdefault("form_plan", {"form_type": "unknown", "fields_on_screen": [], "fields_provided_by_user": [], "required_missing": []})
    parsed.setdefault("observation", "")
    parsed.setdefault("reasoning", "")
    parsed.setdefault("task_status", "in_progress")
    
    action = parsed.get("action")
    if not isinstance(action, dict):
        action = {"type": "none"}
    
    action.setdefault("type", "none")
    action.setdefault("target_description", "")
    action.setdefault("box_2d", None)
    action.setdefault("text", None)
    action.setdefault("keys", None)
    action.setdefault("scroll_direction", None)
    action.setdefault("clear_first", False)
    action.setdefault("requires_confirmation", False)
    
    parsed["action"] = action
    
    parsed.setdefault("speech", "")
    parsed.setdefault("is_sensitive", False)
    parsed.setdefault("expected_result", "")
    parsed.setdefault("max_wait_ms", 3000)
    parsed.setdefault("expects_response", False)

    return parsed


def analyze_screen_and_intent(screenshot: Image.Image,
                               user_voice_text: str,
                               user_state: dict,
                               conversation_context: list = None,
                               step_history: list = None) -> dict | None:
    """Sends screenshot + voice text to Gemini Vision and returns parsed JSON."""
    client = get_gemini_client()
    if client is None:
        print("[ScreenReader] No Gemini client — API key missing.")
        return None

    # Compress and resize screenshot to save bandwidth and API latency
    max_size = (1600, 1600)
    img_copy = screenshot.copy()
    img_copy.thumbnail(max_size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img_copy.convert("RGB").save(buf, format="JPEG", quality=85)
    image_bytes = buf.getvalue()

    context_str = ""
    if conversation_context:
        context_str = "Recent Interaction History:\n" + "\n".join(f"- {c}" for c in conversation_context)

    step_history_str = ""
    if step_history:
        step_history_str = "Steps taken so far for current request:\n" + "\n".join(f"{i+1}. {c}" for i, c in enumerate(step_history))

    contents = [
        SYSTEM_PROMPT,
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        f"User State Context: {json.dumps(user_state)}\nToday's date is: {datetime.now().strftime('%A, %B %d, %Y')}. NEVER select or type a date in the past.",
        context_str,
        step_history_str,
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

                # Handle 429 rate-limit / quota exhaustion
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    # If daily quota is exhausted, sleeping won't help — switch models immediately!
                    if any(kw in error_str.lower() for kw in ["perday", "limit: 20", "quota failure", "daily"]):
                        print(f"[ScreenReader] Daily quota reached for {model_name}. Switching to next model immediately...")
                        break

                    # Otherwise it's a per-minute rate limit — wait briefly and retry
                    wait_time = 5  # default wait
                    delay_match = re.search(r'retry(?:Delay)?.*?(\d+)', error_str)
                    if delay_match:
                        wait_time = min(int(delay_match.group(1)), 30)

                    if attempt < _MAX_RATE_LIMIT_RETRIES:
                        print(f"[ScreenReader] Per-minute rate limit on {model_name}. "
                              f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                        continue  # Retry same model
                    else:
                        print(f"[ScreenReader] Rate limit exhausted for {model_name}. Trying next model...")
                        break  # Try next model

                # Handle 503 server overload / high demand: wait briefly and retry or try next model
                elif any(kw in error_str.lower() for kw in ["503", "unavailable", "high demand", "overloaded", "busy", "temporarily"]):
                    if attempt < _MAX_RATE_LIMIT_RETRIES:
                        print(f"[ScreenReader] {model_name} is experiencing high demand / temporarily busy. "
                              f"Retrying in 2s...")
                        time.sleep(2)
                        continue  # Retry same model
                    else:
                        print(f"[ScreenReader] {model_name} still overloaded after retries. Trying next model...")
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
                        "url": f"data:image/jpeg;base64,{b64_image}",
                        "detail": "high"
                    }
                },
                {
                    "type": "text",
                    "text": (
                        f"User State Context: {json.dumps(user_state)}\nToday's date is: {datetime.now().strftime('%A, %B %d, %Y')}. NEVER select or type a date in the past.\n"
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


if __name__ == "__main__":
    print("Testing Screen Reader...")
    img, mon = capture_screen()
    print(f"Captured: {img.size}")
    res = analyze_screen_and_intent(img, "What options do I have here?", {})
    print(json.dumps(res, indent=2))
