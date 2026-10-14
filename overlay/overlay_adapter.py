import time
import pyautogui

# FAILSAFE: moving mouse to top-left corner aborts pyautogui immediately.
# During a live demo, avoid involuntarily flinging the mouse there.
pyautogui.FAILSAFE = True


def inject_click(normalized_x: float, normalized_y: float, monitor_info: dict, overlay_window=None, restore_overlay: bool = True) -> bool:
    """
    Uses pyautogui to inject a real OS-level mouse click, bypassing kiosk APIs.
    Checks if click would hit the overlay window and momentarily hides it if occluded.
    Returns True if overlay was hidden for the click.
    """
    screen_width  = monitor_info['width']
    screen_height = monitor_info['height']
    offset_x      = monitor_info['left']
    offset_y      = monitor_info['top']

    target_x = offset_x + int(screen_width  * normalized_x)
    target_y = offset_y + int(screen_height * normalized_y)

    print(f"[Adapter] Injecting click -> screen coords ({target_x}, {target_y})  "
          f"[norm: ({normalized_x:.3f}, {normalized_y:.3f})]")

    # Check for occlusion with overlay window
    was_hidden = False
    if overlay_window:
        try:
            if hasattr(overlay_window, 'winfo_rootx'):
                wx = overlay_window.winfo_rootx()
                wy = overlay_window.winfo_rooty()
                ww = overlay_window.winfo_width()
                wh = overlay_window.winfo_height()
                if (wx <= target_x <= wx + ww) and (wy <= target_y <= wy + wh):
                    print(f"[Adapter] ⚠️ Target ({target_x}, {target_y}) is under overlay! Briefly withdrawing...")
                    overlay_window.withdraw()
                    overlay_window.update() #Immediately process the withdrawal without any delay
                    was_hidden = True
                    time.sleep(0.15)
        except Exception as e:
            print(f"[Adapter] Notice checking overlay bounds: {e}")

    # Animate movement for visual clarity during demo (0.15 s is quick but visible)
    pyautogui.moveTo(target_x, target_y, duration=0.15)

    # Discrete down/up simulates a real hardware click more reliably on Windows
    time.sleep(0.08)
    pyautogui.mouseDown()
    time.sleep(0.05)
    pyautogui.mouseUp()
    
    if was_hidden and overlay_window and restore_overlay:
        try:
            print("[Adapter] Restoring overlay...")
            overlay_window.deiconify()
            overlay_window.update()
            time.sleep(0.08)
        except Exception:
            pass

    return was_hidden


def inject_text(text: str, overlay_window=None, press_enter: bool = False):
    """
    Types text into the currently focused input field using OS-level keystrokes.
    Safely clears input without global Ctrl+A webpage selection if unfocused.
    If press_enter is True, presses Enter after typing.
    Defaults to False so autocomplete suggestions and dropdowns stay open for observation.
    """
    if not text:
        return

    # Let the clicked target field settle and register OS focus
    time.sleep(0.15)

    # In modern travel sites (like ixigo, IRCTC), clicking a place field opens the search input or clears it.
    # We clear the field by selecting or backspacing gently:
    # First select field content, backspace, then type
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.04)
    pyautogui.press('backspace')
    time.sleep(0.04)

    # Check if text is pure ASCII
    try:
        text.encode('ascii')
        is_ascii = True
    except UnicodeEncodeError:
        is_ascii = False

    if is_ascii:
        print(f"[Adapter] Typing text: '{text}'")
        pyautogui.write(text, interval=0.03)
    else:
        import subprocess
        print(f"[Adapter] Pasting text (non-ASCII): '{text}'")
        subprocess.run(['clip'], input=text.encode('utf-16-le'), check=True,
                       creationflags=0x08000000)
        time.sleep(0.08)
        pyautogui.hotkey('ctrl', 'v')

    time.sleep(0.15)
    if press_enter:
        print("[Adapter] Pressing enter to commit text")
        pyautogui.press('enter')


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
            print(f"[Adapter]   Unknown key ignored: '{key}'")


def inject_scroll(direction: str):
    """
    Injects a mouse scroll event.
    
    Args:
        direction: "down" or "up"
    """
    if direction == "down":
        print("[Adapter] Scrolling DOWN")
        pyautogui.scroll(-500)
    elif direction == "up":
        print("[Adapter] Scrolling UP")
        pyautogui.scroll(500)
    time.sleep(0.5)
