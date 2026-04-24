# UIAA — Full Project Documentation

> **Universal Intelligent Accessibility Agent**  
> AI-Powered Accessibility Middleware for Smart Kiosks  
> TCS iON Internship Project — April 2026

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Solution Overview](#2-solution-overview)
3. [System Architecture](#3-system-architecture)
4. [The 6-Layer Pipeline](#4-the-6-layer-pipeline)
5. [Module-by-Module Breakdown](#5-module-by-module-breakdown)
6. [The LLM Orchestrator — How It Works](#6-the-llm-orchestrator)
7. [Computer Vision — Perception Layer](#7-computer-vision)
8. [The Overlay Module — Real-World Integration](#8-the-overlay-module)
9. [UI Auto-Adaptation System](#9-ui-auto-adaptation)
10. [Safety & Validation](#10-safety--validation)
11. [Data Flow — End-to-End Walkthrough](#11-data-flow)
12. [Key Design Decisions](#12-key-design-decisions)
13. [Limitations & Future Work](#13-limitations--future-work)

---

## 1. Problem Statement

### The Accessibility Gap in Self-Service Kiosks

Self-service kiosks (ATMs, hospital token machines, railway ticket counters, government portals) are designed for the "average" user. They fail for:

- **Visually impaired users** — small fonts, low contrast, no audio guidance
- **Motor-impaired users** — tiny buttons, no alternative input methods
- **Elderly users** — complex workflows, confusing navigation, no patience-aware design
- **Non-English speakers** — English-only interfaces in multilingual countries like India
- **Cognitively challenged users** — too many options, no step-by-step guidance

### Why Existing Solutions Don't Work

| Approach | Problem |
|----------|---------|
| WCAG compliance | Static rules, no real-time adaptation |
| Screen readers (JAWS, NVDA) | Require software integration, don't work on locked kiosks |
| Hardware add-ons (braille pads) | Expensive, require physical installation |
| Redesigning kiosk software | Vendors won't change legacy systems |

### UIAA's Approach

Instead of changing the kiosk, UIAA wraps around it as an **intelligent middleware layer** that perceives the user, reasons about their needs, and adapts the interface — all in real time, using AI.

---

## 2. Solution Overview

UIAA has two complementary modules:

### Module A: Web Prototype (Simulated Integration)

A browser-based kiosk simulator with a FastAPI backend. Demonstrates the full pipeline:
- Voice input → LLM reasoning → kiosk navigation → adaptive UI
- Control panel with sliders to simulate/observe user states
- Webcam-based computer vision (MediaPipe)
- Two kiosk domains: ATM + Hospital (proves cross-domain universality)

### Module B: Desktop Overlay (Real Integration)

A Python desktop application that works on **any existing software**:
- Captures the entire screen → sends to Gemini Vision → identifies all UI elements
- User speaks a command → AI maps intent to detected elements
- Injects OS-level mouse clicks at target coordinates via `pyautogui`
- Independent MediaPipe vision for user state detection
- Virtual accessibility keypad with large buttons

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    BROWSER (Frontend)                         │
│                                                              │
│  ┌──────────────────┐  ┌─────────────────────────────────┐   │
│  │ KIOSK SIMULATOR  │  │  CONTROL & MONITORING PANEL     │   │
│  │ • ATM/Hospital   │  │  • User State Sliders           │   │
│  │ • Adaptive UI    │  │  • Webcam + Vision Signals      │   │
│  │ • Screen states  │  │  • Conversation History         │   │
│  └──────────────────┘  │  • LLM Reasoning Viewer         │   │
│                        │  • System Log                    │   │
│  ┌─────────────────┐   └─────────────────────────────────┘   │
│  │ VOICE INPUT BAR │                                         │
│  └─────────────────┘                                         │
└───────────────────────┬──────────────────────────────────────┘
                        │ WebSocket (bidirectional, real-time)
                        ▼
┌──────────────────────────────────────────────────────────────┐
│                  PYTHON BACKEND (FastAPI)                     │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ ASR Handler │  │ User Modeling│  │ LLM Orchestrator    │ │
│  │             │  │ Engine       │  │ (Gemini API)        │ │
│  └─────────────┘  └──────────────┘  └─────────────────────┘ │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Context     │  │ Kiosk State  │  │ Output Validator    │ │
│  │ Bundle      │  │ Machine      │  │ + Safety Layer      │ │
│  └─────────────┘  └──────────────┘  └─────────────────────┘ │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐                          │
│  │ Action      │  │ Session      │                          │
│  │ Executor    │  │ Manager      │                          │
│  └─────────────┘  └──────────────┘                          │
└──────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Component | Technology | Why |
|-----------|------------|-----|
| Backend | Python 3.11 + FastAPI | Async, WebSocket support, fast development |
| Frontend | HTML + CSS + Vanilla JS | No framework overhead, full control |
| LLM | Gemini (Flash/Lite) | Free tier, fast, structured JSON output |
| Vision (Browser) | MediaPipe Tasks Vision | 478 landmarks, GPU-accelerated, runs in browser |
| Vision (Overlay) | MediaPipe Python | Same quality, runs on desktop |
| Voice (Browser) | Web Speech API | Free, real-time, no API key needed |
| Voice (Overlay) | SpeechRecognition + pyttsx3 | Offline-capable, OS-native TTS |
| Screen Capture | mss | Fast, cross-platform screen grabbing |
| Click Injection | pyautogui | OS-level mouse/keyboard automation |
| Real-time Comm | WebSocket | Bidirectional push, low latency |

---

## 4. The 6-Layer Pipeline

Every user interaction flows through six layers:

```
Layer 1: PERCEPTION  →  Capture user signals (voice, face, behavior)
Layer 2: MODELING     →  Build user state vector (capabilities, frustration, age)
Layer 3: ORCHESTRATION → LLM reasons about what to do (Context Bundle → Gemini)
Layer 4: VALIDATION   →  Verify LLM output is safe and well-formed
Layer 5: EXECUTION    →  Apply actions (navigate kiosk, adapt UI, speak)
Layer 6: FEEDBACK     →  Verify the action worked, update state for next turn
```

### Layer 1: Perception

**What it captures:**
- Voice transcript (what did the user say?)
- Face landmarks (are they squinting? leaning forward?)
- Hand landmarks (is there tremor?)
- Pose landmarks (are they in a wheelchair?)
- Click behavior (are they clicking too fast? too slow? wrong targets?)

### Layer 2: Modeling

**The UserStateVector** (`backend/modeling/user_state.py`):

```python
@dataclass
class UserStateVector:
    visual_capability: float = 1.0      # 0.0 = blind, 1.0 = perfect vision
    motor_capability: float = 1.0       # 0.0 = no motor control, 1.0 = full
    cognitive_load: float = 0.0         # 0.0 = calm, 1.0 = overwhelmed
    frustration_level: float = 0.0      # 0.0 = calm, 1.0 = extremely frustrated
    hand_tremor: float = 0.0            # 0.0 = stable, 1.0 = severe tremor
    wheelchair_detected: bool = False
    bystander_present: bool = False
    estimated_age: str = "adult"        # child / adult / elderly
    behavioral_flags: List[str] = []    # squinting, leaning_forward, etc.
    error_count: int = 0
    avg_response_time_ms: float = 0.0
```

**Temporal Decay** (`backend/modeling/temporal_decay.py`):
- Frustration decays with 90-second half-life
- Cognitive load decays with 120-second half-life
- If user was frustrated 5 minutes ago but has been calm since, frustration naturally reduces

### Layer 3: Orchestration

The **Context Bundle** packages ALL signals into a single JSON:

```json
{
    "user_input": { "transcript": "I want to withdraw 2000 rupees" },
    "user_state": {
        "visual_capability": 0.3,
        "motor_capability": 1.0,
        "frustration_level": 0.2,
        "behavioral_flags": ["squinting"],
        "needs_accessibility_boost": true
    },
    "kiosk_state": {
        "mode": "atm",
        "current_screen": "main_menu",
        "available_buttons": [
            {"label": "Cash Withdrawal", "action": "SELECT_WITHDRAWAL"},
            {"label": "Balance Enquiry", "action": "SELECT_BALANCE"}
        ]
    },
    "conversation_history": [...]
}
```

The LLM receives this bundle + a system prompt and returns structured actions.

### Layer 4: Validation

The output validator checks:
- Valid JSON structure
- Required fields present (`reasoning`, `actions`)
- Valid action types (`speech_output`, `kiosk_command`, `ui_adaptation`, `proactive_suggestion`)
- Valid kiosk commands (from allowlist)
- If validation fails → retry with error feedback (up to 2 retries)
- If all retries fail → graceful fallback response

### Layer 5: Execution

The Action Executor processes each action:
- `kiosk_command` → updates the state machine → sends new screen to frontend
- `ui_adaptation` → sends CSS class changes to frontend (font scale, contrast, layout)
- `speech_output` → TTS reads the text aloud
- `proactive_suggestion` → delivered as speech + optional auto-apply

### Layer 6: Feedback

After execution:
- The new kiosk screen state is captured
- User behavior on the new screen is tracked
- Error count, response time, and interaction patterns feed back into the User State Vector
- Next turn's Context Bundle reflects the updated state

---

## 5. Module-by-Module Breakdown

### Backend Modules

| File | Purpose | Key Concepts |
|------|---------|--------------|
| `main.py` | FastAPI app, WebSocket endpoint, serves frontend | Async WebSocket handler, session routing |
| `config.py` | Loads API keys from `.env` | Environment variable management |
| `user_state.py` | UserStateVector dataclass | Running average for response times, auto-frustration escalation |
| `temporal_decay.py` | Exponential decay for volatile signals | `e^(-0.693 × elapsed / half_life)` formula |
| `context_bundle.py` | Assembles all signals into one JSON | The "data contract" between perception and intelligence |
| `llm_client.py` | Gemini API calls with retry | Primary model → fallback model → fallback response |
| `prompt_manager.py` | System prompt + templates | The most important file — defines the AI agent's behavior |
| `output_validator.py` | JSON schema validation | Checks action types, required fields, valid enums |
| `kiosk_state.py` | State machine for ATM + Hospital | Screen definitions, transitions, transaction data |
| `action_executor.py` | Processes LLM actions | Command routing, fuzzy screen ID matching, safety checks |
| `validators.py` | Safety enforcement | Amount limits (₹100-₹25,000), command allowlists, rate limiting |
| `session_manager.py` | Per-session state | Conversation history (last 10 turns), user state, kiosk instance |

### Frontend Modules

| File | Purpose | Key Concepts |
|------|---------|--------------|
| `index.html` | Page layout | Two-panel design: kiosk left, controls right |
| `main.css` | Design system | CSS variables, glassmorphism, high-contrast mode, simplified layout |
| `app.js` | Main logic | WebSocket handling, slider listeners, vision callbacks, hysteresis |
| `kiosk.js` | Screen rendering | Dynamic screen building, numpad, adaptation class toggling |
| `vision.js` | MediaPipe integration | Face/hand/pose detection, signal extraction, smoothing |
| `voice.js` | Web Speech API | ASR (Speech-to-Text) + TTS (Text-to-Speech) |
| `websocket.js` | WebSocket client | Auto-reconnect, JSON message handling |

### Overlay Modules

| File | Purpose | Key Concepts |
|------|---------|--------------|
| `overlay_main.py` | Main Tkinter app | Thread management (voice, vision, orchestrator), adaptation levels |
| `overlay_vision.py` | MediaPipe face detection | Both-eye squinting, 8-frame smoothing, leaning detection |
| `overlay_voice.py` | Voice I/O | SpeechRecognition for ASR, pyttsx3 for TTS, thread-safe locking |
| `screen_reader.py` | Gemini Vision analysis | Screenshot → AI → JSON with UI elements + coordinates |
| `overlay_adapter.py` | Click injection | pyautogui mouse control, DPI-aware coordinate mapping |
| `debug_coords.py` | Debug utility | Visual coordinate verification tool |

---

## 6. The LLM Orchestrator

### How It Works

The LLM is the "brain" of UIAA. It uses **zero-shot reasoning** — no training, no intent classification, no decision trees. It receives the full context and decides what to do.

### The System Prompt

Located in `prompt_manager.py`, the system prompt defines:

1. **Agent Identity** — "You are UIAA, an AI agent embedded inside a kiosk"
2. **Available Actions** — 4 action types the agent can perform
3. **Proactive Rules** — automatic triggers:
   - `visual_capability < 0.4` → high contrast + large fonts
   - `frustration_level > 0.5` → reassuring speech + simplify UI
   - User speaks Hindi but UI is English → offer language switch
   - `cognitive_load > 0.7` → simplified layout automatically
4. **Valid Commands** — exact command names and screen IDs
5. **Output Schema** — JSON format with `reasoning` + `actions` array

### Why Zero-Shot?

Traditional chatbots use intent classification:
```
"withdraw 2000" → intent: WITHDRAWAL → slot: amount=2000 → rule: navigate to PIN
```

This breaks on novel inputs: *"I need some cash, maybe around two thousand"*

UIAA uses zero-shot LLM reasoning:
```
Context: user said "I need some cash, maybe around two thousand", kiosk is at main menu
→ LLM reasons: user wants withdrawal of ₹2000
→ LLM outputs: [kiosk_command: WITHDRAW, params: {amount: 2000}] + [speech: "I'll help..."]
```

The LLM handles ambiguity, partial information, multi-turn context, and novel phrasings without any training.

### Multi-Model Fallback

```
gemini-3.1-flash-lite-preview  (fastest, cheapest)
         ↓ if fails
gemini-2.5-flash               (reliable fallback)
         ↓ if ALL Gemini fails
gpt-4o-mini                    (OpenAI fallback — paid)
         ↓ if everything fails
Hardcoded fallback response    ("Could you please repeat that?")
```

---

## 7. Computer Vision

### Browser (vision.js) — MediaPipe Tasks Vision

Uses three MediaPipe models simultaneously:

**1. Face Landmarker** (478 landmarks)
- **Squinting Detection**: Measures eye aspect ratio (EAR)
  - Landmarks 159/145 (left eye) + 386/374 (right eye)
  - Both eyes averaged for robustness
  - 8-frame rolling average prevents blink false positives
  - Normalized against face height for distance invariance
- **Leaning Detection**: Face width vs baseline comparison
  - If face is >35% larger than baseline → user is leaning forward
  - Baseline recalibrates every 100 frames

**2. Hand Landmarker**
- **Tremor Detection**: Measures wrist position variance over 10 frames
  - If jitter > threshold → `hand_tremor` signal activated

**3. Pose Landmarker**
- **Wheelchair Detection**: Compares torso height vs leg length
  - `shoulder_to_hip / hip_to_ankle` ratio analysis
- **Bystander Detection**: If >1 face detected → `bystander_present = true`
- **Age Estimation**: Forehead-to-chin ratio heuristic

### Overlay (overlay_vision.py) — MediaPipe Python

Same detection logic but runs natively in Python:
- OpenCV captures webcam frames
- MediaPipe FaceLandmarker processes each frame
- 8-frame rolling average for squinting smoothing
- Both eyes averaged (matches browser implementation)
- Hysteresis system: 6 consecutive readings (~3 seconds) before triggering adaptation

### Hysteresis — Preventing Flicker

Without hysteresis, a single blink would trigger: squinting → high contrast → normal → flicker.

The system requires **6 consecutive consistent readings** before changing adaptation level:

```python
if target_level == current_level:
    count += 1
else:
    current_level = target_level
    count = 1

if count < 6:  # Not stable yet
    return  # Don't adapt
```

---

## 8. The Overlay Module

### How It Enables Real-World Integration

The overlay proves UIAA can work on **any existing software** without source code access:

```
Step 1: Capture entire screen (mss)
Step 2: Send screenshot to Gemini Vision
Step 3: AI returns JSON with all detected UI elements + bounding boxes
Step 4: User speaks: "Click on Submit"
Step 5: AI matches "Submit" to detected element
Step 6: pyautogui injects click at element's center coordinates
```

### Screen Reader Pipeline (`screen_reader.py`)

1. **Capture**: `mss` grabs the primary monitor (with DPI awareness)
2. **Hide Overlay**: The overlay window is temporarily hidden (thread-safe via `after()`)
3. **Encode**: Screenshot converted to JPEG, base64-encoded
4. **Send to Gemini**: Image + user transcript + system prompt
5. **Parse Response**: JSON with `targets[]` (all detected elements) and `selected_targets[]` (matched elements)
6. **Coordinate Mapping**: `box_2d` values (0-1000 grid) → actual pixel coordinates

### Coordinate System

Gemini returns bounding boxes on a normalized 1000×1000 grid:
```
[ymin, xmin, ymax, xmax]  →  each value 0-1000
```

Conversion to screen pixels:
```python
center_x = monitor["left"] + (xmin + xmax) / 2 * monitor["width"] / 1000
center_y = monitor["top"] + (ymin + ymax) / 2 * monitor["height"] / 1000
```

### Thread Architecture

The overlay runs 3 background threads + 1 main thread:

```
Main Thread (Tkinter)
├── Vision Thread      — polls webcam every 0.5s
├── Voice Thread       — blocks on microphone input
└── Orchestrator Thread — runs the voice→capture→AI→click pipeline
```

All UI updates are dispatched to the main thread via `root.after(0, callback)`.

---

## 9. UI Auto-Adaptation System

### Adaptation Levels

| Level | Trigger | Changes Applied |
|-------|---------|-----------------|
| Normal | Default state | Standard fonts, colors, layout |
| Visual | Squinting detected OR `visual_capability < 0.4` | 1.5× font, high contrast (yellow-on-black) |
| Motor | Tremor detected OR `motor_capability < 0.4` | Simplified layout, larger buttons |
| Full | Both visual + motor signals | All adaptations combined at 1.5× scale |

### CSS Classes

```css
.kiosk-frame.contrast-high_contrast .kiosk-screen {
    background: #000;
    color: #ffff00;     /* Yellow on black — maximum contrast */
}

.kiosk-frame.layout-simplified .kiosk-btn {
    padding: 1.2rem 2rem;
    font-size: 1.25rem;
    min-width: 200px;   /* Large touch targets */
}
```

### Manual Override Protection

When the camera auto-adjusts sliders, a **10-second cooldown** prevents overriding manual slider values:

```javascript
// If user manually moved slider within 10 seconds, don't auto-update
const MANUAL_COOLDOWN_MS = 10000;
const lastManual = _sliderManualTimestamps['visual_capability'] || 0;
if (Date.now() - lastManual < MANUAL_COOLDOWN_MS) return;
```

---

## 10. Safety & Validation

### Output Validator (`output_validator.py`)

Checks every LLM response before execution:
- ✅ Valid JSON object with `reasoning` and `actions`
- ✅ Non-empty `actions` array
- ✅ At least one `speech_output` action (user must always hear a response)
- ✅ Valid action types: `speech_output`, `kiosk_command`, `ui_adaptation`, `proactive_suggestion`
- ✅ Valid enum values for `contrast_mode`, `layout`, `language`

### Safety Validator (`validators.py`)

- **Amount Limits**: ₹100 minimum, ₹25,000 maximum, multiples of ₹100
- **Command Allowlist**: Only predefined ATM/Hospital commands accepted
- **Rate Limiting**: 500ms minimum between commands (prevents rapid-fire)
- **Transaction Limit**: Max 5 transactions per session

### Retry Logic

```
LLM Response → Validate → FAIL → Retry with error feedback
                                   ↓
                          FAIL again → 2nd retry
                                   ↓
                          FAIL → Hardcoded fallback response
```

---

## 11. Data Flow — End-to-End Walkthrough

### Example: "I want to withdraw 2000 rupees"

```
1. User speaks into microphone
   └→ Web Speech API transcribes: "I want to withdraw 2000 rupees"

2. Frontend sends via WebSocket:
   └→ { type: "voice_input", transcript: "I want to withdraw 2000 rupees" }

3. Backend assembles Context Bundle:
   └→ transcript + UserStateVector + KioskState(main_menu) + conversation_history

4. Context Bundle sent to Gemini API:
   └→ System prompt + formatted context → structured JSON response

5. Gemini responds:
   └→ { reasoning: "User wants ₹2000 withdrawal...",
        actions: [
          { type: "speech_output", text: "I'll help you withdraw 2000 rupees..." },
          { type: "kiosk_command", command: "WITHDRAW", parameters: { amount: 2000 } },
          { type: "ui_adaptation", adaptations: { font_size_multiplier: 1.3 } }
        ]}

6. Output Validator checks JSON → ✅ valid

7. Action Executor processes:
   └→ WITHDRAW(2000) → amount stored → navigate to enter_pin screen
   └→ UI adaptation applied (1.3× font)

8. Results sent to frontend:
   └→ New screen rendered (PIN entry)
   └→ TTS speaks: "I'll help you withdraw 2000 rupees..."
   └→ Font size scaled to 1.3×

9. User state updated:
   └→ interaction_count++, response_time recorded
```

---

## 12. Key Design Decisions

### Why Zero-Shot LLM Instead of Rule-Based?

Rule-based systems require predefined intent patterns. For accessibility, the space of possible user inputs is too large: broken speech, mixed languages, ambiguous requests, emotional states. An LLM handles all of these without explicit programming.

### Why WebSocket Instead of REST?

REST (HTTP) is request-response: frontend must poll for updates. WebSocket is bidirectional: backend can push screen updates, proactive suggestions, and adaptation changes instantly.

### Why MediaPipe Instead of OpenCV/dlib?

MediaPipe provides 478 face landmarks (vs 68 for dlib), runs on GPU in the browser, includes hand and pose detection, and is actively maintained by Google. The model is only 3.7 MB.

### Why Tkinter for the Overlay?

The overlay needs to be a lightweight, always-on-top window. Tkinter is built into Python (no extra dependencies), supports transparency/always-on-top, and is sufficient for the simple overlay UI.

### Why In-Memory Sessions (No Database)?

This is a prototype. In-memory sessions are simpler, faster, and sufficient for demonstration. Production would use Redis or a database.

---

## 13. Limitations & Future Work

### Current Limitations

| Limitation | Reason | Production Solution |
|------------|--------|-------------------|
| 2-5 second LLM latency | Cloud API round-trip | Local models (Gemini Nano) or response caching |
| Requires internet | Gemini API is cloud-based | Edge deployment with on-device models |
| Single monitor only | Overlay captures primary monitor | Multi-monitor support via monitor selection |
| English-focused ASR | Web Speech API limitation | Whisper API for better multilingual support |
| No persistent user profiles | In-memory sessions | Database-backed user preferences |
| Simulated kiosk | No real hardware | Vendor API integration or hardware middleware |

### Future Work

1. **Edge Deployment** — Run on Jetson/Coral for offline operation
2. **Hardware Integration** — Physical kiosk sensors (proximity, noise, lighting)
3. **User Profiles** — Remember returning users and their preferences
4. **Multi-Language TTS** — Natural-sounding Hindi/Tamil voice synthesis
5. **Security Hardening** — PIN masking, data encryption, audit logging
6. **A/B Testing Framework** — Measure accessibility improvement metrics
7. **Browser Extension Mode** — Inject UIAA into web-based kiosks via Chrome extension

---

*This documentation covers the complete UIAA system as built. For architecture diagrams, see [ARCHITECTURE.md](ARCHITECTURE.md). For setup instructions, see the main [README.md](../README.md).*
