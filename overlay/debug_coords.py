import sys
sys.path.append('.')
from screen_reader import capture_screen, analyze_screen_and_intent

img, mon = capture_screen()

# Save the image to see what Gemini is actually seeing
img.save("debug_screenshot.png")

print("Monitor info:", mon)
res = analyze_screen_and_intent(img, "click on the Windows Start button", {})
print("Gemini response:", res)

if res:
    # Check selected_targets (new schema — always a list)
    selected = res.get("selected_targets", [])
    print(f"\nSelected targets: {len(selected)}")

    for i, target in enumerate(selected):
        name = target.get("name", "Unknown")
        box = target.get("box_2d")
        print(f"\n  Target {i+1}: '{name}'")
        print(f"  Box: {box}")
        if box and len(box) == 4:
            y_min, x_min, y_max, x_max = box
            y = (y_min + y_max) / 2
            x = (x_min + x_max) / 2

            target_x = mon['left'] + int(mon['width'] * (x / 1000.0))
            target_y = mon['top'] + int(mon['height'] * (y / 1000.0))
            print(f"  Calculated Screen X: {target_x}, Y: {target_y}")

    # Also show all detected targets
    all_targets = res.get("targets", [])
    print(f"\nAll detected targets: {len(all_targets)}")
    for i, t in enumerate(all_targets):
        print(f"  {i+1}. {t.get('name', '?')} [{t.get('type', '?')}] box={t.get('box_2d')}")
