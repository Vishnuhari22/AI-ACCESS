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

    print(f"[Adapter] Injecting click → screen coords ({target_x}, {target_y})  "
          f"[norm: ({normalized_x:.3f}, {normalized_y:.3f})]")

    # Animate movement for visual clarity during demo (0.15 s is quick but visible)
    pyautogui.moveTo(target_x, target_y, duration=0.15)

    # Discrete down/up simulates a real hardware click more reliably on Windows
    time.sleep(0.08)
    pyautogui.mouseDown()
    time.sleep(0.05)
    pyautogui.mouseUp()
