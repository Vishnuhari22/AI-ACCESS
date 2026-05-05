import time
import pyautogui

# FAILSAFE: moving mouse to top-left corner aborts pyautogui immediately.
# During a live demo, avoid involuntarily flinging the mouse there.
pyautogui.FAILSAFE = True


def inject_click(normalized_x: float, normalized_y: float, monitor_info: dict):
    """
    Uses pyautogui to inject a real OS-level mouse click, bypassing kiosk APIs.

    Args:
        normalized_x   : 0.0 – 1.0 fraction of monitor width  (from box_2d centre)
        normalized_y   : 0.0 – 1.0 fraction of monitor height (from box_2d centre)
        monitor_info   : dict from mss, e.g. {'left': 0, 'top': 0, 'width': 1920, 'height': 1080}
    """
    screen_width  = monitor_info['width']
    screen_height = monitor_info['height']
    offset_x      = monitor_info['left']
    offset_y      = monitor_info['top']

    target_x = offset_x + int(screen_width  * normalized_x)
    target_y = offset_y + int(screen_height * normalized_y)

    print(f"[Adapter] Injecting click -> screen coords ({target_x}, {target_y})  "
          f"[norm: ({normalized_x:.3f}, {normalized_y:.3f})]")

    # Animate movement for visual clarity during demo (0.15 s is quick but visible)
    pyautogui.moveTo(target_x, target_y, duration=0.15)

    # Discrete down/up simulates a real hardware click more reliably on Windows
    time.sleep(0.08)
    pyautogui.mouseDown()
    time.sleep(0.05)
    pyautogui.mouseUp()


def inject_text(text: str):
    """
    Types text into the currently focused input field using OS-level keystrokes.

    Args:
        text: The string to type. Only ASCII-safe characters are typed directly;
              for Unicode text (e.g. non-Latin scripts), clipboard paste is used.
    """
    if not text:
        return

    # Brief pause to let the target field fully gain focus after a click
    time.sleep(0.25)

    # Select all existing text first so new text replaces it (prevents appending)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.05)

    # Check if text is pure ASCII — pyautogui.write() only handles ASCII
    try:
        text.encode('ascii')
        is_ascii = True
    except UnicodeEncodeError:
        is_ascii = False

    if is_ascii:
        # Type character-by-character with a small interval for reliability
        print(f"[Adapter] Typing text: '{text}'")
        pyautogui.write(text, interval=0.03)
    else:
        # For Unicode text, use clipboard paste (Ctrl+V)
        import subprocess
        print(f"[Adapter] Pasting text (non-ASCII): '{text}'")
        subprocess.run(['clip'], input=text.encode('utf-16-le'), check=True,
                       creationflags=0x08000000)  # CREATE_NO_WINDOW
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', 'v')


def inject_keys(keys: list):
    """
    Presses a sequence of keyboard keys using OS-level input injection.

    Args:
        keys: A list of key names to press in order.
              Supported keys: enter, tab, down, up, left, right, escape,
                              backspace, delete, space, home, end,
                              pageup, pagedown, f1-f12
              Special commands:
                  "wait:N"  — pause for N milliseconds before next key
              Examples:
                  ["wait:1000", "down", "enter"]     — wait 1s, arrow down, enter
                  ["tab", "tab", "enter"]             — tab twice then enter
                  ["escape"]                          — close a dropdown/popup
    """
    if not keys or not isinstance(keys, list):
        return

    # Map of friendly names to pyautogui key names
    key_map = {
        "enter": "enter", "return": "enter",
        "tab": "tab",
        "down": "down", "up": "up", "left": "left", "right": "right",
        "escape": "escape", "esc": "escape",
        "backspace": "backspace", "delete": "delete",
        "space": "space",
        "home": "home", "end": "end",
        "pageup": "pageup", "pagedown": "pagedown",
    }
    # Add function keys
    for i in range(1, 13):
        key_map[f"f{i}"] = f"f{i}"

    print(f"[Adapter] Pressing keys: {keys}")

    for key in keys:
        if not isinstance(key, str):
            continue

        key_lower = key.strip().lower()

        # Handle wait command: "wait:1000" pauses for 1000ms
        if key_lower.startswith("wait:"):
            try:
                ms = int(key_lower.split(":", 1)[1])
                wait_s = min(ms / 1000.0, 10.0)  # cap at 10 seconds
                print(f"[Adapter]   Waiting {ms}ms...")
                time.sleep(wait_s)
            except ValueError:
                pass
            continue

        # Map and press the key
        mapped = key_map.get(key_lower)
        if mapped:
            print(f"[Adapter]   Pressing: {mapped}")
            pyautogui.press(mapped)
            time.sleep(0.08)  # small gap between keypresses
        else:
            print(f"[Adapter]   Unknown key: '{key}' — skipping")
