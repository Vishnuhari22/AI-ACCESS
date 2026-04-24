# 🦾 UIAA — Universal Intelligent Accessibility Agent

> **AI-Powered Accessibility Middleware for Smart Kiosks**  
> *TCS iON Internship Project — April 2026*

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Gemini API](https://img.shields.io/badge/Gemini-AI%20Studio-4285F4?logo=google&logoColor=white)](https://aistudio.google.com)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-0.10+-00897B?logo=google&logoColor=white)](https://ai.google.dev/edge/mediapipe/solutions/guide)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Overview

UIAA is an AI agent that makes **any** self-service kiosk (ATM, hospital token machine, government portal) accessible to **every** user — including those with visual impairments, motor disabilities, cognitive challenges, or language barriers.

Instead of requiring kiosk vendors to redesign their software, UIAA sits as an **intelligent middleware layer** that:
- 🎤 **Listens** — understands voice commands in English, Hindi, and Tamil
- 👁️ **Sees** — uses computer vision to detect user disabilities (squinting, tremor, wheelchair)
- 🧠 **Reasons** — an LLM orchestrator decides how to adapt the interface
- ✋ **Acts** — injects clicks, changes fonts/contrast, simplifies layouts in real time

### Key Innovation

Traditional accessibility is **rule-based** (WCAG guidelines) and **static** (configured once). UIAA is:
- **AI-Driven** — a zero-shot LLM orchestrator handles novel situations without training
- **Real-Time Adaptive** — UI continuously adjusts based on live perception signals
- **Universal** — works on any software via screen capture + click injection (no API needed)

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────┐
│                   PERCEPTION LAYER                         │
│  🎤 Voice (ASR)  │  👁️ Vision (MediaPipe)  │  📊 Behavior│
└──────────────────────────┬─────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                  INTELLIGENCE LAYER                          │
│  📦 Context Bundle  →  🤖 LLM Orchestrator  →  ✅ Validator │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                   EXECUTION LAYER                            │
│  🖥️ UI Adaptation  │  🎯 Kiosk Control  │  🔊 TTS Output   │
└──────────────────────────────────────────────────────────────┘
```

The system follows a **6-layer pipeline**: Perception → Modeling → Orchestration → Validation → Execution → Feedback.

---

## 📁 Project Structure

```
uiaa-prototype/
│
├── backend/                    # Python FastAPI backend
│   ├── main.py                 # WebSocket server + API routes
│   ├── config.py               # Environment configuration
│   ├── .env.example            # API key template (copy to .env)
│   ├── requirements.txt        # Python dependencies
│   │
│   ├── modeling/               # User state modeling
│   │   ├── user_state.py       # UserStateVector dataclass
│   │   └── temporal_decay.py   # Signal decay over time
│   │
│   ├── orchestrator/           # LLM intelligence
│   │   ├── context_bundle.py   # Assembles all signals for LLM
│   │   ├── llm_client.py       # Gemini API client + retry logic
│   │   ├── prompt_manager.py   # System prompt + templates
│   │   └── output_validator.py # JSON schema validation
│   │
│   ├── execution/              # Action execution
│   │   ├── kiosk_state.py      # Kiosk state machine (ATM + Hospital)
│   │   └── action_executor.py  # Processes LLM actions → state changes
│   │
│   ├── safety/                 # Safety layer
│   │   └── validators.py       # Allowlists, amount limits, rate limiting
│   │
│   └── session/                # Session management
│       └── session_manager.py  # Per-session state tracking
│
├── frontend/                   # Browser-based kiosk simulator
│   ├── index.html              # Main page
│   ├── css/
│   │   └── main.css            # Design system (glassmorphism, dark theme)
│   └── js/
│       ├── app.js              # Main app logic + WebSocket
│       ├── kiosk.js            # Kiosk screen rendering + adaptation
│       ├── vision.js           # MediaPipe face/hand/pose detection
│       ├── voice.js            # Web Speech API (ASR + TTS)
│       └── websocket.js        # WebSocket client wrapper
│
├── overlay/                    # Desktop accessibility overlay
│   ├── overlay_main.py         # Tkinter UI + thread management
│   ├── overlay_vision.py       # MediaPipe face detection (Python)
│   ├── overlay_voice.py        # Speech recognition + TTS (pyttsx3)
│   ├── overlay_adapter.py      # pyautogui click injection
│   ├── screen_reader.py        # Gemini Vision screen analysis
│   ├── debug_coords.py         # Coordinate debugging utility
│   ├── .env.example            # API key template
│   └── requirements.txt        # Python dependencies
│
├── docs/                       # Documentation
│   ├── ARCHITECTURE.md         # Detailed architecture diagrams
│   └── PROJECT_DOCUMENTATION.md # Full technical documentation
│
├── .gitignore
├── LICENSE
└── README.md                   # ← You are here
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Google Chrome** (for Web Speech API)
- **Gemini API Key** — free from [Google AI Studio](https://aistudio.google.com/)
- **Webcam** (optional — for computer vision features)

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/uiaa-prototype.git
cd uiaa-prototype
```

### 2. Set Up the Backend

```bash
cd backend
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Run the Web Prototype

```bash
# From the backend/ directory
python main.py
```

Open **http://localhost:8000** in Google Chrome.

### 4. Run the Overlay (Optional)

```bash
cd overlay
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

python overlay_main.py
```

---

## 🎮 Demo Guide

### Web Prototype Demo

1. **Open** `http://localhost:8000` in Chrome
2. **Click the microphone** button and say: *"I want to withdraw 2000 rupees"*
3. Watch the AI navigate the ATM through the workflow
4. **Adjust sliders** — set Visual Capability to 0.2 and watch the UI switch to high contrast
5. **Enable camera** — squint at the screen to trigger automatic visual adaptation
6. **Switch to Hospital mode** — say *"I need a token for cardiology"*

### Overlay Demo

1. **Open any application** on your desktop (browser, settings, anything)
2. **Run** `python overlay_main.py`
3. **Click "Run Voice Cycle"** and say: *"What's on the screen?"*
4. The AI will describe all UI elements it detects
5. Say: *"Click on [button name]"* to inject a click at that element

---

## 🔑 Features

### Perception Layer
| Signal | Technology | Description |
|--------|------------|-------------|
| Voice input | Web Speech API / SpeechRecognition | Real-time ASR in English, Hindi, Tamil |
| Face detection | MediaPipe Face Landmarker | 478-point facial landmark tracking |
| Squinting detection | Eye aspect ratio analysis | Both eyes averaged, 8-frame smoothing |
| Distance/leaning | Face-to-camera ratio | Detects user leaning toward screen |
| Hand tremor | MediaPipe Hand Landmarker | Wrist jitter measurement |
| Wheelchair detection | MediaPipe Pose Landmarker | Shoulder-to-hip vs hip-to-ankle ratio |
| Bystander detection | Multi-face counting | Privacy-aware presence detection |
| Age estimation | Face proportion analysis | Forehead-to-chin ratio heuristic |
| Behavioral analysis | Click timing + error tracking | Detects spam-clicks, idle, repeated errors |

### Intelligence Layer
- **LLM Zero-Shot Orchestrator** — Gemini processes a Context Bundle and returns structured JSON actions
- **No intent classification training** — handles novel inputs out of the box
- **Multi-turn conversation** — maintains context across interactions
- **Proactive assistance** — detects user struggles and offers help unprompted
- **Output validation** — JSON schema enforcement with retry logic

### Execution Layer
- **Kiosk state machine** — ATM mode (9 screens) + Hospital mode (7 screens)
- **Adaptive UI** — font scaling, high contrast, simplified layout, language switching
- **Safety validators** — amount limits (₹100–₹25,000), command allowlists, rate limiting
- **Screen capture + click injection** — OS-level interaction via pyautogui

---

## 🛡️ Safety & Privacy

- **Command Allowlist** — only valid kiosk commands are executed
- **Amount Validation** — withdrawal amounts capped at ₹25,000, multiples of ₹100
- **Rate Limiting** — minimum 500ms between commands
- **Transaction Limits** — max 5 transactions per session
- **No data storage** — all sessions are in-memory, no personal data persisted
- **Bystander awareness** — system detects third-party presence for privacy

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | ✅ | Google AI Studio API key |
| `OPENAI_API_KEY` | ❌ | OpenAI fallback (when Gemini is rate-limited) |

### Gemini Free Tier

The project is designed to work within Gemini's free tier. A typical 15-minute demo session uses ~8 API calls, well within free limits.

---

## 📚 Documentation

- [Full Project Documentation](docs/PROJECT_DOCUMENTATION.md) — detailed technical writeup
- [Architecture Diagrams](docs/ARCHITECTURE.md) — system architecture visualizations

---

## 🧪 Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| LLM | Google Gemini (gemini-3.1-flash-lite / gemini-2.5-flash) |
| Computer Vision | MediaPipe (Face, Hand, Pose Landmarkers) |
| Voice (Browser) | Web Speech API (ASR + TTS) |
| Voice (Desktop) | SpeechRecognition + pyttsx3 |
| Screen Capture | mss |
| Click Injection | pyautogui |
| Real-time Comm | WebSocket |

---

## 📄 License

This project is developed as part of a TCS iON Internship. See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- **TCS iON** — Internship program and mentorship
- **Google AI Studio** — Gemini API access
- **MediaPipe** — On-device ML framework
- **FastAPI** — High-performance Python web framework
