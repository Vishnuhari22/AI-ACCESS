import http.server
import socketserver
import json
import socket
import threading
from typing import Any, Callable, Optional

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>UIAA Wheelchair Companion</title>
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background: #0d1117; color: #e6edf3; padding: 14px; min-height: 100vh; }
    .header { text-align: center; margin-bottom: 14px; }
    .header h1 { font-size: 20px; color: #00e5ff; margin-bottom: 4px; display: flex; align-items: center; justify-content: center; gap: 8px; }
    .header p { font-size: 12px; color: #8b949e; }
    
    .status-bar { display: flex; align-items: center; justify-content: space-between; background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 10px 14px; margin-bottom: 12px; }
    .status-pill { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: bold; padding: 4px 10px; border-radius: 20px; }
    .status-pill.idle { background: #1b2f21; color: #4caf50; border: 1px solid #2e7d32; }
    .status-pill.running { background: #332610; color: #ffb74d; border: 1px solid #ff9800; }
    .status-pill.waiting { background: #3b1219; color: #ff5252; border: 1px solid #f44336; animation: pulse 1.5s infinite; }
    
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.6; }
        100% { opacity: 1; }
    }
    
    .progress-box { background: #111b27; border: 1px solid #1f6feb; border-radius: 10px; padding: 12px; margin-bottom: 12px; font-size: 13px; color: #79c0ff; display: flex; align-items: center; gap: 10px; }
    .spinner { width: 16px; height: 16px; border: 2px solid #388bfd; border-top-color: transparent; border-radius: 50%; animation: spin 1s linear infinite; flex-shrink: 0; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 14px; margin-bottom: 14px; }
    .card-title { font-size: 14px; font-weight: bold; margin-bottom: 10px; color: #00e5ff; display: flex; align-items: center; justify-content: space-between; }
    
    /* Clarification Question Card */
    .card-question { background: #261c10; border: 2px solid #ff9800; box-shadow: 0 0 16px rgba(255, 152, 0, 0.25); }
    .question-body { font-size: 14px; color: #ffe0b2; margin-bottom: 12px; line-height: 1.4; font-weight: 500; }
    .options-grid { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
    .btn-opt { background: #3e2723; border: 1px solid #ffb74d; color: #fff; padding: 12px; border-radius: 8px; font-size: 14px; font-weight: bold; text-align: left; cursor: pointer; transition: background 0.2s; }
    .btn-opt:hover, .btn-opt:active { background: #d84315; border-color: #ffcc80; }
    
    label { display: block; font-size: 12px; color: #8b949e; margin-bottom: 4px; font-weight: 500; }
    input[type="text"], select { width: 100%; background: #1c2333; border: 1px solid #30363d; border-radius: 8px; color: #fff; padding: 11px; font-size: 15px; margin-bottom: 10px; }
    input[type="text"]:focus, select:focus { outline: none; border-color: #00e5ff; }
    
    .toggle-row { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
    .toggle-btn { flex: 1; min-width: 90px; padding: 10px; border-radius: 8px; border: 1px solid #30363d; background: #21262d; color: #e6edf3; font-size: 13px; font-weight: bold; text-align: center; cursor: pointer; }
    .toggle-btn.active { background: #1565c0; border-color: #00e5ff; color: #fff; }
    
    .btn-submit { width: 100%; background: #2e7d32; border: none; border-radius: 10px; color: white; padding: 14px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 6px; }
    .btn-submit:active { background: #1b5e20; }
    .btn-voice { width: 100%; background: #0077b6; border: none; border-radius: 10px; color: white; padding: 12px; font-size: 15px; font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 8px; }
    .btn-scan { background: #21262d; border: 1px solid #30363d; color: #58a6ff; font-size: 12px; font-weight: bold; padding: 6px 12px; border-radius: 6px; cursor: pointer; }
    
    .status-box { background: #111; border-radius: 8px; padding: 10px; font-size: 13px; color: #4caf50; text-align: center; margin-top: 10px; display: none; }
    .hint-text { font-size: 12px; color: #8b949e; text-align: center; margin-top: 4px; }
</style>
</head>
<body>
    <div class="header">
        <h1>♿ UIAA Mobile Companion</h1>
        <p>Wheelchair Ergonomic Kiosk Controller</p>
    </div>

    <!-- Live Status Pill -->
    <div class="status-bar">
        <span style="font-size: 13px; color: #8b949e;">Kiosk Status:</span>
        <div id="kiosk-status-pill" class="status-pill idle">● Kiosk Ready</div>
    </div>

    <!-- Live Agent Step Progress -->
    <div id="agent-progress-box" class="progress-box" style="display: none;">
        <div class="spinner"></div>
        <div id="agent-progress-text" style="line-height: 1.3;">Executing step...</div>
    </div>

    <!-- Question / Clarification Prompt -->
    <div id="question-card" class="card card-question" style="display: none;">
        <div class="card-title" style="color: #ffb74d;">❓ Agent Needs Your Choice</div>
        <div id="question-text" class="question-body">Please select an option:</div>
        <div id="question-options" class="options-grid"></div>
        <label>Or type a custom response:</label>
        <div style="display: flex; gap: 8px;">
            <input type="text" id="custom-answer-field" placeholder="e.g. Cochin India, Morning flight..." style="margin-bottom: 0;">
            <button class="btn-submit" style="width: auto; padding: 0 16px; margin-top: 0; background: #e65100;" onclick="submitCustomAnswer()">Send</button>
        </div>
    </div>

    <!-- Dynamic Form Elements (Classified from Screen) -->
    <div class="card" id="card-dynamic-form">
        <div class="card-title">
            <span>📋 Screen Form Controls</span>
            <button class="btn-scan" onclick="triggerScan()">🔍 Re-Scan</button>
        </div>
        <div id="dynamic-form-container">
            <p class="hint-text" style="text-align: left; padding: 8px 0;">Scanning kiosk screen for interactive fields...</p>
        </div>
        <button id="btn-submit-dyn" class="btn-submit" onclick="submitDynamicForm()" style="display: none;">✓ Submit Form to Kiosk</button>
    </div>

    <!-- Hands-Free Voice & Custom Instructions -->
    <div class="card">
        <div class="card-title">🎙️ Hands-Free Mobile Voice</div>
        <button class="btn-voice" onclick="startMobileVoice()">🎤 Speak Instruction / Answer</button>
        <p class="hint-text">Speaks directly to the kiosk agent or answers pending questions.</p>
    </div>

    <div class="card">
        <div class="card-title">💬 Custom Command / Goal</div>
        <input type="text" id="custom-goal-field" placeholder="e.g. Click terminal 2, select cheapest flight...">
        <button class="btn-voice" style="background: #5e35b1; margin-bottom: 0;" onclick="submitCustomGoal()">🤖 Send Goal to Agent</button>
    </div>

    <!-- Fallback / Quick Travel Form -->
    <details class="card" style="cursor: pointer;">
        <summary class="card-title" style="margin-bottom: 6px;">✈️ Quick Travel Shortcut (Fallback)</summary>
        <div style="cursor: default; padding-top: 8px;">
            <label>Trip Type</label>
            <div class="toggle-row">
                <div class="toggle-btn active" id="btn-oneway" onclick="setTripType('One Way')">One Way</div>
                <div class="toggle-btn" id="btn-roundtrip" onclick="setTripType('Round Trip')">Round Trip</div>
            </div>

            <label>From (Departure)</label>
            <input type="text" id="from-field" placeholder="e.g. Mumbai, Kochi">

            <label>To (Destination)</label>
            <input type="text" id="to-field" placeholder="e.g. Pune, Delhi">

            <label>Departure Date</label>
            <input type="text" id="date-field" placeholder="e.g. 15 October 2026">

            <button class="btn-submit" onclick="submitQuickTravel()">✓ Submit Flight Search</button>
        </div>
    </details>

    <div id="status-msg" class="status-box"></div>

<script>
    let currentTripType = "One Way";
    let dynamicToggles = {};
    let lastRenderedFormHash = "";

    function setTripType(type) {
        currentTripType = type;
        document.getElementById('btn-oneway').className = type === 'One Way' ? 'toggle-btn active' : 'toggle-btn';
        document.getElementById('btn-roundtrip').className = type === 'Round Trip' ? 'toggle-btn active' : 'toggle-btn';
    }

    function showStatus(text, color, autoHide = false) {
        const statusBox = document.getElementById('status-msg');
        statusBox.style.display = 'block';
        statusBox.style.color = color;
        statusBox.innerText = text;
        if (autoHide) {
            setTimeout(() => { statusBox.style.display = 'none'; }, 4000);
        }
    }

    function handleResponse(res) {
        return res.json().then(data => {
            if (res.status === 409 || data.status === 'busy') {
                showStatus("⏳ " + (data.message || "Kiosk is currently busy with another task. Please wait."), '#ff9800');
            } else if (!res.ok) {
                showStatus("❌ Error (" + res.status + "): " + (data.message || "Request failed"), '#f44336');
            } else {
                showStatus("✓ " + (data.message || "Sent! Kiosk AI agent is executing..."), '#4caf50', true);
            }
        });
    }

    // ─────────────────────────────────────────────────────────────────
    // Polling / State Synchronization
    // ─────────────────────────────────────────────────────────────────
    function fetchKioskState() {
        fetch('/api/state')
            .then(res => res.json())
            .then(state => {
                updateStatusPill(state);
                updateProgressBox(state);
                updateQuestionCard(state);
                renderDynamicForm(state.form);
            })
            .catch(() => {});
    }

    setInterval(fetchKioskState, 1000);
    fetchKioskState();

    function updateStatusPill(state) {
        const pill = document.getElementById('kiosk-status-pill');
        if (state.pending_question) {
            pill.className = "status-pill waiting";
            pill.innerText = "● Action Needed";
        } else if (state.is_busy) {
            pill.className = "status-pill running";
            pill.innerText = "● Agent Working";
        } else {
            pill.className = "status-pill idle";
            pill.innerText = "● Kiosk Ready";
        }
    }

    function updateProgressBox(state) {
        const box = document.getElementById('agent-progress-box');
        const txt = document.getElementById('agent-progress-text');
        if (state.is_busy && state.step_info) {
            box.style.display = 'flex';
            txt.innerText = state.step_info;
        } else {
            box.style.display = 'none';
        }
    }

    function updateQuestionCard(state) {
        const qCard = document.getElementById('question-card');
        const qText = document.getElementById('question-text');
        const qOpts = document.getElementById('question-options');

        if (state.pending_question) {
            const pq = state.pending_question;
            qCard.style.display = 'block';
            qText.innerText = pq.question || "Please clarify your choice:";
            
            qOpts.innerHTML = '';
            if (pq.options && pq.options.length > 0) {
                pq.options.forEach(opt => {
                    const btn = document.createElement('button');
                    btn.className = 'btn-opt';
                    btn.innerText = `👉 ${opt}`;
                    btn.onclick = () => submitAnswer(opt);
                    qOpts.appendChild(btn);
                });
            }
        } else {
            qCard.style.display = 'none';
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // Dynamic Form Rendering
    // ─────────────────────────────────────────────────────────────────
    function renderDynamicForm(form) {
        if (!form) return;
        
        // Avoid clobbering input fields while user is typing
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
        const isEditing = activeTag === 'input' || activeTag === 'select';
        
        const currentHash = JSON.stringify({
            inp: (form.inputs || []).map(i => i.name),
            drop: (form.dropdowns || []).map(d => d.name),
            tog: form.toggle_groups || {}
        });

        if (currentHash === lastRenderedFormHash && isEditing) {
            return;
        }
        if (currentHash === lastRenderedFormHash) {
            return;
        }
        lastRenderedFormHash = currentHash;

        const container = document.getElementById('dynamic-form-container');
        const submitBtn = document.getElementById('btn-submit-dyn');
        container.innerHTML = '';

        let hasElements = false;

        // 1. Render Toggle Groups
        if (form.toggle_groups) {
            for (const [groupName, options] of Object.entries(form.toggle_groups)) {
                hasElements = true;
                const grpLabel = document.createElement('label');
                grpLabel.innerText = groupName;
                container.appendChild(grpLabel);

                const row = document.createElement('div');
                row.className = 'toggle-row';

                options.forEach(optName => {
                    const btn = document.createElement('div');
                    const isActive = dynamicToggles[groupName] === optName;
                    btn.className = isActive ? 'toggle-btn active' : 'toggle-btn';
                    btn.innerText = optName;
                    btn.onclick = () => {
                        dynamicToggles[groupName] = optName;
                        Array.from(row.children).forEach(c => c.className = 'toggle-btn');
                        btn.className = 'toggle-btn active';
                    };
                    row.appendChild(btn);
                });
                container.appendChild(row);
            }
        }

        // 2. Render Input Fields
        if (form.inputs && form.inputs.length > 0) {
            hasElements = true;
            form.inputs.forEach(inp => {
                const lbl = document.createElement('label');
                lbl.innerText = inp.name;
                container.appendChild(lbl);

                const inputEl = document.createElement('input');
                inputEl.type = 'text';
                inputEl.className = 'dyn-input';
                inputEl.dataset.fieldName = inp.name;
                inputEl.placeholder = `Enter ${inp.name}`;
                if (inp.current_value) inputEl.value = inp.current_value;
                container.appendChild(inputEl);
            });
        }

        // 3. Render Dropdowns
        if (form.dropdowns && form.dropdowns.length > 0) {
            hasElements = true;
            form.dropdowns.forEach(drop => {
                const lbl = document.createElement('label');
                lbl.innerText = drop.name;
                container.appendChild(lbl);

                const selectEl = document.createElement('select');
                selectEl.className = 'dyn-select';
                selectEl.dataset.fieldName = drop.name;

                (drop.options || ["Select option"]).forEach(opt => {
                    const optionEl = document.createElement('option');
                    optionEl.value = opt;
                    optionEl.innerText = opt;
                    if (opt === drop.current_value) optionEl.selected = true;
                    selectEl.appendChild(optionEl);
                });
                container.appendChild(selectEl);
            });
        }

        if (hasElements) {
            submitBtn.style.display = 'block';
        } else {
            submitBtn.style.display = 'none';
            container.innerHTML = '<p class="hint-text" style="text-align: left; padding: 8px 0;">No form fields detected on screen. Tap "Re-Scan" or use the quick shortcuts below.</p>';
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // Submissions
    // ─────────────────────────────────────────────────────────────────
    function submitDynamicForm() {
        const fields = {};
        document.querySelectorAll('.dyn-input').forEach(inp => {
            const val = inp.value.trim();
            if (val) fields[inp.dataset.fieldName] = val;
        });
        document.querySelectorAll('.dyn-select').forEach(sel => {
            const val = sel.value;
            if (val && val !== "Select option") fields[sel.dataset.fieldName] = val;
        });
        for (const [groupName, val] of Object.entries(dynamicToggles)) {
            if (val) fields[groupName] = val;
        }

        if (Object.keys(fields).length === 0) {
            alert("Please fill in or select at least one field.");
            return;
        }

        showStatus("Transmitting form to kiosk agent...", '#ffeb3b');
        fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: "submit_form", fields: fields })
        })
        .then(handleResponse)
        .catch(err => {
            showStatus("Error transmitting: " + err, '#f44336');
        });
    }

    function submitAnswer(text) {
        showStatus(`Submitting choice: "${text}"...`, '#ffeb3b');
        fetch('/api/answer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ answer: text })
        })
        .then(handleResponse)
        .catch(err => {
            showStatus("Error transmitting: " + err, '#f44336');
        });
    }

    function submitCustomAnswer() {
        const ans = document.getElementById('custom-answer-field').value.trim();
        if (!ans) {
            alert("Please type your reply first.");
            return;
        }
        submitAnswer(ans);
        document.getElementById('custom-answer-field').value = '';
    }

    function triggerScan() {
        showStatus("Requesting screen scan from kiosk...", '#ffeb3b');
        fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: "scan" })
        })
        .then(handleResponse)
        .catch(err => {
            showStatus("Error transmitting: " + err, '#f44336');
        });
    }

    function submitQuickTravel() {
        const payload = {
            action: "submit",
            trip_type: currentTripType,
            from: document.getElementById('from-field').value.trim(),
            to: document.getElementById('to-field').value.trim(),
            date: document.getElementById('date-field').value.trim()
        };

        showStatus("Transmitting flight search to Kiosk...", '#ffeb3b');
        fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(handleResponse)
        .catch(err => {
            showStatus("Error transmitting: " + err, '#f44336');
        });
    }

    function submitCustomGoal() {
        const goal = document.getElementById('custom-goal-field').value.trim();
        if (!goal) {
            alert("Please type an instruction first.");
            return;
        }

        showStatus(`Transmitting goal: "${goal}"...`, '#ffeb3b');
        fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: "voice", text: goal })
        })
        .then(handleResponse)
        .catch(err => {
            showStatus("Error transmitting: " + err, '#f44336');
        });
    }

    function startMobileVoice() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            alert("Speech recognition not supported on this mobile browser. Please type inputs.");
            return;
        }
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        const rec = new SpeechRec();
        rec.lang = 'en-IN';
        rec.start();

        showStatus("Listening to your voice...", '#00e5ff');

        rec.onresult = function(event) {
            const transcript = event.results[0][0].transcript;
            showStatus(`Heard: "${transcript}". Sending to Kiosk...`, '#ffeb3b');
            fetch('/api/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: "voice", text: transcript })
            })
            .then(handleResponse)
            .catch(err => {
                showStatus("Error transmitting: " + err, '#f44336');
            });
        };
        rec.onerror = function(e) {
            showStatus("Voice error: " + e.error, '#f44336');
        };
    }
</script>
</body>
</html>
"""

def get_local_ip() -> str:
    """Detects the workstation's local Wi-Fi / LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting to a public DNS without sending packets extracts local interface IP
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


class CompanionServer:
    def __init__(
        self,
        port: int = 8080,
        on_command: Optional[Callable[[dict], Any]] = None,
        get_state: Optional[Callable[[], dict]] = None,
    ):
        self.port = port
        self.on_command = on_command
        self.get_state = get_state
        self.server: Optional[socketserver.TCPServer] = None
        self.local_ip = get_local_ip()
        self.server_thread: Optional[threading.Thread] = None

    def start(self):
        handler_cls = self._make_handler()
        # Allow immediate socket reuse
        socketserver.TCPServer.allow_reuse_address = True
        try:
            self.server = socketserver.TCPServer(("0.0.0.0", self.port), handler_cls)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            print(f"[CompanionServer] Running on http://{self.local_ip}:{self.port}")
        except Exception as e:
            print(f"[CompanionServer] Could not bind port {self.port}: {e}")

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass

    def get_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}"

    def _make_handler(self):
        on_cmd = self.on_command
        get_st = self.get_state

        class CompanionHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress console clutter

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                if self.path == "/api/state":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    state_data = get_st() if get_st else {"status": "idle", "is_busy": False, "form": {}}
                    self.wfile.write(json.dumps(state_data).encode("utf-8"))
                elif self.path == "/" or self.path.startswith("/index"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

            def do_POST(self):
                if self.path in ("/api/command", "/api/answer"):
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    try:
                        data = json.loads(body.decode("utf-8")) if body else {}
                        if self.path == "/api/answer":
                            data = {"action": "answer", "answer": data.get("answer", "")}

                        status_code = 200
                        res_data = {"status": "ok"}
                        if on_cmd:
                            result = on_cmd(data)
                            if isinstance(result, tuple) and len(result) == 2:
                                status_code, res_data = result
                            elif isinstance(result, dict):
                                res_data = result
                                if res_data.get("status") == "busy":
                                    status_code = 409

                        self.send_response(status_code)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps(res_data).encode("utf-8"))
                    except Exception as e:
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

        return CompanionHandler
