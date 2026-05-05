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

# Load API keys from backend's .env file
env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
load_dotenv(env_path)

# --- Gemini client ---
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    _client = genai.Client(api_key=api_key)
else:
    print("WARNING: GEMINI_API_KEY not found in backend/.env")
    _client = None

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
    "targets": [
        {
            "name": "Label of the button, link, or input field",
            "type": "button | input | link | text",
            "box_2d": [ymin, xmin, ymax, xmax]
        }
    ],
    "selected_targets": [
        {
            "name": "The target(s) matched to the user's request",
            "box_2d": [ymin, xmin, ymax, xmax],
            "type_text": "Text to type into the field after clicking, or null",
            "press_keys": ["key1", "key2"],
            "follow_up": "Description of what to click next after this action opens a menu/dropdown, or null"
        }
    ]
}

Rules:
- box_2d values are integers 0-1000 representing [ymin, xmin, ymax, xmax] on a 1000x1000 grid.
- The grid maps to the FULL screenshot: (0,0) is top-left of the monitor, (1000,1000) is bottom-right.
- is_sensitive: set to true when the speech_response contains private data such as PINs, passwords, account numbers, balances, or OTPs. Otherwise false.
- EVERY item in 'targets' MUST have its own box_2d. Do not omit any.
- Make bounding boxes TIGHT around the clickable element — do not use overly large boxes.
- Leave 'selected_targets' as an empty array [] when the user is only asking what is available (not requesting an action).
- Never return null for selected_targets — always use an empty array [].
- When the user just wants to click a button or link with no text entry, set "type_text" to null.

TEXT INPUT RULES:
- When the user's voice input implies typing into a field (e.g. "from Chengannur", "enter 5000", "search for trains"), set "type_text" to ONLY the value to type (e.g. "Chengannur", "5000", "trains").
- The system will automatically clear any existing text in the field before typing.
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
                               user_state: dict) -> dict | None:
    """Sends screenshot + voice text to Gemini Vision and returns parsed JSON."""
    if _client is None:
        print("[ScreenReader] No Gemini client — API key missing.")
        return None

    # Convert PIL image → raw PNG bytes for the new SDK
    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    contents = [
        SYSTEM_PROMPT,
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        f"User State Context: {json.dumps(user_state)}",
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


if __name__ == "__main__":
    print("Testing Screen Reader...")
    img, mon = capture_screen()
    print(f"Captured: {img.size}")
    res = analyze_screen_and_intent(img, "What options do I have here?", {})
    print(json.dumps(res, indent=2))
