document.addEventListener('DOMContentLoaded', () => {
    // ─── DOM Element References ───
    const wsStatusEl = document.getElementById('ws-status');
    const logContainer = document.getElementById('system-log');
    const micBtn = document.getElementById('mic-btn');
    const transcriptBox = document.getElementById('transcript-box');
    const reasoningBox = document.getElementById('reasoning-box');
    const latencyBadge = document.getElementById('latency-badge');
    const accessibilityStatus = document.getElementById('accessibility-status');
    const kioskTitle = document.getElementById('kiosk-title');
    const conversationBox = document.getElementById('conversation-box');

    // Slider elements
    const sliders = {
        visual_capability:  document.getElementById('visual-cap'),
        motor_capability:   document.getElementById('motor-cap'),
        cognitive_load:     document.getElementById('cognitive-load'),
        frustration_level:  document.getElementById('frustration'),
    };
    const sliderValEls = {
        visual_capability:  document.getElementById('visual-cap-val'),
        motor_capability:   document.getElementById('motor-cap-val'),
        cognitive_load:     document.getElementById('cognitive-load-val'),
        frustration_level:  document.getElementById('frustration-val'),
    };
    const selectEls = {
        interaction_speed:  document.getElementById('interaction-speed'),
        age_group:          document.getElementById('age-group'),
        preferred_language: document.getElementById('language-pref'),
    };
    const kioskModeSelect = document.getElementById('kiosk-mode-select');

    // Webcam elements
    const webcamToggle = document.getElementById('webcam-toggle');
    const webcamOverlay = document.getElementById('webcam-overlay');
    const sigFace     = document.getElementById('sig-face');
    const sigEyes     = document.getElementById('sig-eyes');
    const sigDistance = document.getElementById('sig-distance');
    const sigTremor   = document.getElementById('sig-tremor');
    const sigWheelchair = document.getElementById('sig-wheelchair');
    const sigBystander  = document.getElementById('sig-bystander');
    const sigAge        = document.getElementById('sig-age');
    const autoDetectLabel = document.getElementById('auto-detect-label');

    // ─── Initialize Kiosk Renderer ───
    const kioskRenderer = new KioskRenderer('kiosk-screen');

    kioskRenderer.onAutoAdvance = (command) => {
        addLog(`Auto-advancing: ${command}`, 'info');
        wsClient.send({ type: "kiosk_button_press", action: command, parameters: {} });
    };

    // ─── Logging ───
    function addLog(message, type = 'info') {
        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        const now = new Date().toLocaleTimeString();
        entry.textContent = `[${now}] ${message}`;
        logContainer.appendChild(entry);
        logContainer.scrollTop = logContainer.scrollHeight;
        while (logContainer.children.length > 100) {
            logContainer.removeChild(logContainer.firstChild);
        }
    }

    // ─── Conversation History Display ───
    function addConversationBubble(role, text) {
        const bubble = document.createElement('div');
        bubble.className = `conv-bubble conv-${role}`;
        bubble.textContent = text;
        conversationBox.appendChild(bubble);
        conversationBox.scrollTop = conversationBox.scrollHeight;
        // Keep last 20 bubbles
        while (conversationBox.children.length > 20) {
            conversationBox.removeChild(conversationBox.firstChild);
        }
    }

    // ─── Gather current user state from all controls ───
    function gatherUserState() {
        const flags = new Set();

        document
            .querySelectorAll('.behavior-flag:checked')
            .forEach(cb => flags.add(cb.value));

        // Camera observations are signals, not capability values.
        const vs = visionAnalyzer.signals || {};

        if (vs.squinting) {
            flags.add('squinting');
        }

        if (vs.leaning_forward) {
            flags.add('leaning_forward');
        }

        if (vs.hand_detected && vs.hand_tremor > 0.35) {
            flags.add('hand_tremor');
        }

        return {
            visual_capability:
                parseFloat(sliders.visual_capability.value),

            motor_capability:
                parseFloat(sliders.motor_capability.value),

            cognitive_load:
                parseFloat(sliders.cognitive_load.value),

            frustration_level:
                parseFloat(sliders.frustration_level.value),

            interaction_speed:
                selectEls.interaction_speed.value,

            age_group: 
                selectEls.age_group.value,

            preferred_language:
                selectEls.preferred_language.value,

            behavioral_flags:
                [...flags],

            hand_tremor:
                vs.hand_tremor || 0,

            looking_down:
                vs.looking_down || false,

            gaze_direction:
                vs.gaze_direction || 'center',

            wheelchair_detected:
                vs.wheelchair_detected || false,

            bystander_present:
                vs.bystander_present || false,

            estimated_age:
                vs.estimated_age || 'adult',

            // Perception confidence is preserved in the canonical state.
            squint_confidence:
                Number(vs.squint_confidence || 0),

            lean_confidence:
                Number(vs.lean_confidence || 0),

            tremor_confidence:
                Number(vs.tremor_confidence || 0),

            face_confidence:
                Number(vs.face_confidence || 0),

            hand_confidence:
                Number(vs.hand_confidence || 0),
        };
    }

    function sendUserStateUpdate() {
        const state = gatherUserState();

        wsClient.send({
            type: "user_state_update",
            data: state
        });
    }

    // ─── Voice System ───
    const voiceSystem = new UIAAVoiceSystem(
        (finalTranscript, interimTranscript) => {
            if (interimTranscript) {
                transcriptBox.textContent = interimTranscript;
                transcriptBox.classList.add('interim');
            }
            if (finalTranscript) {
                transcriptBox.textContent = finalTranscript;
                transcriptBox.classList.remove('interim');
                addLog(`User: "${finalTranscript}"`, 'info');
                addConversationBubble('user', finalTranscript);

                wsClient.send({
                    type: "user_audio_text",
                    text: finalTranscript,
                    response_time_ms: Date.now() - (window._lastInteractionTime || Date.now())
                });
                addLog('Sent to backend → awaiting LLM...', 'tx');
                accessibilityStatus.textContent = 'Thinking...';
                accessibilityStatus.classList.add('thinking');
            }
        },
        (state) => {
            if (state === 'listening') {
                micBtn.classList.add('listening');
                transcriptBox.textContent = 'Listening...';
            } else {
                micBtn.classList.remove('listening');
            }
        }
    );

    // ─── Vision Analyzer (Webcam) ───

    // Track when user last manually changed a slider
    const _sliderManualTimestamps = {};

    // ─── Proactive Empathetic Voice Assistant ───
    // Uses the same AccessibilityPolicy decision as the backend/overlay.
    // Perception supplies observations; policy decides when assistance is needed.
    let _latestAccessibilityDecision = {};
    let _latestVisionSignals = {};
    let _proactiveCooldownUntil = 0;
    let _proactiveTremorStart = 0;
    let _proactiveVisionStart = 0;
    let _lastTremorSeen = 0;
    let _lastVisionNeedSeen = 0;

    function triggerEmpatheticPrompt(text) {
        const now = Date.now();
        if (now < _proactiveCooldownUntil) return;

        _proactiveCooldownUntil = now + 60000;
        addLog(`💬 Empathetic assist: "${text}"`, 'rx');
        addConversationBubble('agent', text);

        // Keep the prompt in the backend conversation history, matching the overlay.
        if (wsClient) {
            wsClient.send({ type: 'empathetic_prompt_logged', text });
        }

        voiceSystem.speak(text, 'en-IN', () => {
            setTimeout(() => {
                voiceSystem.startListening();

                setTimeout(() => {
                    voiceSystem.stopListening();
                }, 5000);
            }, 100);
        });
    }

    function updateProactiveVoiceMonitor(signals, decision) {
        _latestVisionSignals = signals || {};
        _latestAccessibilityDecision = decision || _latestAccessibilityDecision;

        if (!_latestVisionSignals.face_detected) {
            _proactiveTremorStart = 0;
            _proactiveVisionStart = 0;
            return;
        }

        const now = Date.now();
        if (now < _proactiveCooldownUntil) return;

        const tremorNeed = !!_latestAccessibilityDecision.tremor_need;
        const visualNeed = !!_latestAccessibilityDecision.visual_need;

        if (tremorNeed) {
            _lastTremorSeen = now;
            if (!_proactiveTremorStart) _proactiveTremorStart = now;
            if (now - _proactiveTremorStart >= 2500) {
                triggerEmpatheticPrompt(
                    'I noticed some hand tremor. Would you like me to navigate by voice for you?'
                );
                _proactiveTremorStart = 0;
                return;
            }
        } else if (now - _lastTremorSeen > 800) {
            _proactiveTremorStart = 0;
        }

        if (visualNeed) {
            _lastVisionNeedSeen = now;
            if (!_proactiveVisionStart) _proactiveVisionStart = now;
            if (now - _proactiveVisionStart >= 2500) {
                triggerEmpatheticPrompt(
                    `I noticed you're looking closely. Would you like me to read the screen aloud?`
                );
                _proactiveVisionStart = 0;
            }
        } else if (now - _lastVisionNeedSeen > 1000) {
            _proactiveVisionStart = 0;
        }
    }

    // Camera observations can arrive frequently.
    // We only send meaningful camera-state changes to the backend.
    let _lastVisionStateSignature = '';
    let _lastVisionStateSentAt = 0;

    const VISION_STATE_SEND_INTERVAL_MS = 300;

    function sendVisionStateUpdate(force = false) {
        // wsClient is declared later in this file. This function runs from
        // asynchronous camera callbacks, but the guard also protects
        // unusual startup timing.
        if (typeof wsClient === 'undefined' || !wsClient) {
            return;
        }

        const state = gatherUserState();

        const signature = JSON.stringify({
            behavioral_flags: state.behavioral_flags,
            hand_tremor: Number(state.hand_tremor.toFixed(2)),
            squint_confidence:
                Number(state.squint_confidence.toFixed(2)),
            lean_confidence:
                Number(state.lean_confidence.toFixed(2)),
            tremor_confidence:
                Number(state.tremor_confidence.toFixed(2)),
            looking_down: state.looking_down,
            gaze_direction: state.gaze_direction,
            wheelchair_detected: state.wheelchair_detected,
            bystander_present: state.bystander_present,
            estimated_age: state.estimated_age
        });

        const now = Date.now();

        // Do not resend identical camera state just because the timer
        // elapsed. Send only when meaningful perception state changes.
        if (!force && signature === _lastVisionStateSignature) {
            return;
        }

        // Still rate-limit rapidly changing camera signals.
        if (
            !force &&
            now - _lastVisionStateSentAt <
                VISION_STATE_SEND_INTERVAL_MS
        ) {
            return;
        }

        _lastVisionStateSignature = signature;
        _lastVisionStateSentAt = now;

        wsClient.send({
            type: "user_state_update",
            data: state
        });
    }
    const visionAnalyzer = new VisionAnalyzer((signals) => {
        // Update signal display tags
        sigFace.textContent = signals.face_detected ? '✅ Face' : '❌ No Face';
        sigFace.className = `signal-tag ${signals.face_detected ? 'active' : ''}`;

        sigEyes.textContent = signals.squinting 
            ? '👁️ Squinting!' 
            : (signals.looking_down ? '👁️ Looking Down' : '👁️ Eyes OK');
        sigEyes.className = `signal-tag ${signals.squinting ? 'warning' : (signals.looking_down ? 'active' : '')}`;

        const distLabel = signals.leaning_forward ? '↗️ Leaning!' : '↗️ Normal';
        sigDistance.textContent = distLabel;
        sigDistance.className = `signal-tag ${signals.leaning_forward ? 'warning' : ''}`;

        // ── New perception signals ──
        const tremorPct = Math.round((signals.hand_tremor || 0) * 100);
        if (signals.hand_detected) {
            sigTremor.textContent = `✋ Tremor: ${tremorPct}%`;
            sigTremor.className = `signal-tag ${tremorPct > 35 ? 'warning' : 'active'}`;
        } else {
            sigTremor.textContent = `✋ Hand: None`;
            sigTremor.className = `signal-tag`;
        }

        sigWheelchair.textContent = signals.wheelchair_detected ? '♿ Wheelchair: YES' : '♿ Wheelchair: No';
        sigWheelchair.className = `signal-tag ${signals.wheelchair_detected ? 'active' : ''}`;

        sigBystander.textContent = signals.bystander_present ? '👥 Bystander: YES' : '👥 Bystander: No';
        sigBystander.className = `signal-tag ${signals.bystander_present ? 'warning' : ''}`;

        sigAge.textContent = `👤 Age: ${signals.estimated_age || 'adult'}`;
        sigAge.className = `signal-tag`;

        if (!signals.face_detected) {
            const squintFlag = document.getElementById('flag-squinting');
            const leanFlag = document.getElementById('flag-leaning');
            const tremorFlag = document.querySelector('input.behavior-flag[value="hand_tremor"]');

            if (squintFlag) squintFlag.checked = false;
            if (leanFlag) leanFlag.checked = false;
            if (tremorFlag) tremorFlag.checked = false;

            // Clear stale camera observations in backend state.
            sendVisionStateUpdate(true);

            return;
        }

        // Auto-update behavioral flag checkboxes
        const squintFlag = document.getElementById('flag-squinting');
        const leanFlag = document.getElementById('flag-leaning');
        const tremorFlag = document.querySelector('input.behavior-flag[value="hand_tremor"]');
        if (squintFlag) squintFlag.checked = signals.squinting;
        if (leanFlag) leanFlag.checked = signals.leaning_forward;
        if (tremorFlag) tremorFlag.checked = (signals.hand_detected && signals.hand_tremor > 0.4);

        // Camera only supplies observations.
        // AccessibilityPolicy on the backend decides the adaptation.
        sendVisionStateUpdate();
        updateProactiveVoiceMonitor(signals, _latestAccessibilityDecision);
    });

    let webcamActive = false;
    webcamToggle.addEventListener('click', async () => {
        if (!webcamActive) {
            const success = await visionAnalyzer.start('webcam-video', 'webcam-canvas');
            if (success) {
                webcamActive = true;
                webcamToggle.textContent = '🔴 Disable Camera';
                webcamToggle.classList.add('active');
                webcamOverlay.style.display = 'none';
                autoDetectLabel.textContent = '(auto-detecting)';
                addLog('📷 Webcam enabled — detecting face signals', 'rx');
            } else {
                addLog('📷 Failed to access webcam', 'error');
            }
        } else {
            visionAnalyzer.stop();
            webcamActive = false;
            webcamToggle.textContent = '📷 Enable Camera';
            webcamToggle.classList.remove('active');
            webcamOverlay.style.display = 'flex';
            autoDetectLabel.textContent = '';
            addLog('📷 Webcam disabled', 'info');
        }
    });

    // ─── Handle deterministic accessibility policy update ───
    function handleAccessibilityUpdate(data) {
        const decision = data.decision;
        _latestAccessibilityDecision = decision || {};

        if (!decision || !decision.adaptation) {
            return;
        }

        addLog(
            `♿ Accessibility policy → ${decision.accessibility_level}`,
            'rx'
        );

        applyUIAdaptation(decision.adaptation);
        updateProactiveVoiceMonitor(_latestVisionSignals, decision);

        if (decision.needs_accessibility_boost) {
            accessibilityStatus.textContent = '⚡ Adapted';
            accessibilityStatus.style.background = 'rgba(245, 158, 11, 0.2)';
            accessibilityStatus.style.color = '#f59e0b';
        } else {
            accessibilityStatus.textContent = 'Ready';
            accessibilityStatus.style.background = '';
            accessibilityStatus.style.color = '';
        }
    }

    // ─── Process LLM Agent Response ───

    function handleAgentResponse(data) {
        accessibilityStatus.textContent = 'Ready';
        accessibilityStatus.classList.remove('thinking');
        reasoningBox.textContent = data.reasoning || '(no reasoning provided)';
        if (data.latency_ms) {
            latencyBadge.textContent = `${data.latency_ms} ms`;
        }

        // Track errors for behavioral analysis
        if (data.reasoning && data.reasoning.toLowerCase().includes('error')) {
            if (window._behaviorTracker) window._behaviorTracker.recordError();
        }

        const actions = data.actions || [];
        for (const action of actions) {
            switch (action.type) {
                case 'speech_output':
                    addLog(`🔊 Agent: "${action.text}"`, 'rx');
                    addConversationBubble('agent', action.text);
                    voiceSystem.speak(action.text, action.language || 'en-IN');
                    break;
                case 'ui_adaptation':
                    addLog(
                        '⚠️ Ignoring LLM UI adaptation; AccessibilityPolicy is authoritative.',
                        'info'
                    );
                    break;
                case 'kiosk_command':
                    addLog(`⚙️ Kiosk: ${action.command} → ${action.target_screen || ''}`, 'rx');
                    break;
                case 'proactive_suggestion':
                    addLog(`💡 Proactive: ${action.suggestion}`, 'rx');
                    addConversationBubble('agent', `💡 ${action.suggestion}`);
                    break;
                default:
                    addLog(`Unknown action: ${action.type}`, 'info');
            }
        }
        window._lastInteractionTime = Date.now();
    }

    // ─── Handle Kiosk Screen Update ───
    function handleKioskScreenUpdate(data) {
        const screen = data.screen;
        if (!screen) return;
        addLog(`📺 Screen → ${screen.screen_id} (${screen.title})`, 'info');
        kioskRenderer.render(screen);
        // Track screen change for cognitive load analysis
        if (window._behaviorTracker) window._behaviorTracker.recordScreenChange();
    }

    // ─── Apply UI Adaptations to the Kiosk ───
    function applyUIAdaptation(adaptations) {
        const kioskScreen = document.getElementById('kiosk-screen');
        const kioskFrame = document.querySelector('.kiosk-frame');

        if (adaptations.font_size_multiplier) {
            kioskScreen.style.fontSize = `${adaptations.font_size_multiplier}rem`;
            addLog(`Font size → ${adaptations.font_size_multiplier}x`, 'info');
        }
        if (adaptations.contrast_mode) {
            kioskFrame.classList.remove('contrast-normal', 'contrast-high_contrast', 'contrast-dark');
            kioskFrame.classList.add(`contrast-${adaptations.contrast_mode}`);
            addLog(`Contrast → ${adaptations.contrast_mode}`, 'info');
        }
        if (adaptations.layout) {
            kioskFrame.classList.remove('layout-standard', 'layout-simplified');
            kioskFrame.classList.add(`layout-${adaptations.layout}`);
            addLog(`Layout → ${adaptations.layout}`, 'info');
        }
    }

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsClient = new UIAAWebSocket(
        `${wsProtocol}//${window.location.host}/ws`,
        (message) => {
            try {
                const data = JSON.parse(message);
                if (data.type === 'agent_response') {
                    handleAgentResponse(data);

                } else if (data.type === 'accessibility_update') {
                    handleAccessibilityUpdate(data);

                } else if (data.type === 'kiosk_screen_update') {
                    handleKioskScreenUpdate(data);

                } else if (data.type === 'agent_speech') {
                    addLog(`Agent: "${data.text}"`, 'rx');
                    voiceSystem.speak(data.text);

                } else {
                    addLog(`Unknown: ${message.substring(0, 80)}`, 'info');
                }
            } catch (e) {
                addLog(`Raw: ${message}`, 'rx');
            }
        },
        (status) => {
            wsStatusEl.textContent = status.toUpperCase();
            wsStatusEl.className = `status-indicator ${status === 'connected' ? 'connected' : 'error'}`;
            addLog(`WebSocket ${status}`, 'info');
        }
    );
    wsClient.connect();

    // Background inactivity check — mirrors the overlay's 30s proactive nudge.
    setInterval(() => {
        if (!_latestVisionSignals.face_detected) return;
        if (Date.now() < _proactiveCooldownUntil) return;
        const inactivity = Date.now() - (window._lastInteractionTime || Date.now());
        if (inactivity > 30000) {
            triggerEmpatheticPrompt(`I'm here if you need any help. Would you like me to guide you through the screen?`);
        }
    }, 1000);

    // ─── Event Listeners ───
    micBtn.addEventListener('click', () => {
        addLog('🎤 Mic clicked', 'info');
        if (!voiceSystem.recognition) {
            addLog('Speech Recognition not supported — use Chrome!', 'error');
            transcriptBox.textContent = 'Browser not supported. Use Chrome.';
            return;
        }
        voiceSystem.startListening();
    });

    // Slider listeners
    Object.entries(sliders).forEach(([key, el]) => {
        el.addEventListener('input', (e) => {
            sliderValEls[key].textContent = parseFloat(e.target.value).toFixed(1);
            _sliderManualTimestamps[key] = Date.now();
            sendUserStateUpdate();
        });
    });

    // Select listeners
    Object.values(selectEls).forEach(el => {
        el.addEventListener('change', () => sendUserStateUpdate());
    });

    // Behavioral flags
    document.querySelectorAll('.behavior-flag').forEach(cb => {
        cb.addEventListener('change', () => sendUserStateUpdate());
    });

    // Kiosk mode switch
    kioskModeSelect.addEventListener('change', (e) => {
        const mode = e.target.value;
        kioskTitle.textContent = mode === 'atm' ? '🏧 Smart ATM' : '🏥 Hospital Kiosk';
        wsClient.send({ type: "kiosk_mode_change", mode: mode });
        addLog(`Kiosk mode → ${mode}`, 'info');
    });

    // ─── Behavioral Analyzer (Motor, Cognitive, Frustration) ───
    // Tracks interaction patterns to auto-detect user state
    const behaviorTracker = {
        clickTimes: [],        // Timestamps of button clicks
        errorCount: 0,         // Errors reported by backend
        lastClickTime: 0,      // Last button click timestamp
        screenEntryTime: Date.now(), // When current screen appeared
        idleWarned: false,
        
        // Called on every kiosk button click
        recordClick() {
            const now = Date.now();
            this.clickTimes.push(now);
            if (this.clickTimes.length > 20) this.clickTimes.shift();
            this.lastClickTime = now;
            this.idleWarned = false;
            this._analyze();
        },

        // Called when backend reports an error
        recordError() {
            this.errorCount++;
            const errFlag = document.querySelector('.behavior-flag[value="repeated_errors"]');
            if (this.errorCount >= 3 && errFlag) {
                errFlag.checked = true;
            }
            this._analyze();
        },

        // Called when screen changes
        recordScreenChange() {
            this.screenEntryTime = Date.now();
        },

        _analyze() {
            // ─── Motor Capability: based on click speed ───
            // Slow or uneven clicking = motor difficulty
            let targetMotor = 1.0;
            if (this.clickTimes.length >= 3) {
                const gaps = [];
                for (let i = 1; i < this.clickTimes.length; i++) {
                    gaps.push(this.clickTimes[i] - this.clickTimes[i - 1]);
                }
                const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
                
                // Very slow clicking (>5s between clicks) = low motor
                if (avgGap > 5000) targetMotor = 0.3;
                else if (avgGap > 3000) targetMotor = 0.5;
                // Very fast repeated clicking (spam clicking) = frustration
                else if (avgGap < 500 && gaps.length >= 3) targetMotor = 0.5;
            }

            const currentMotor = parseFloat(sliders.motor_capability.value);
            if (Math.abs(currentMotor - targetMotor) > 0.1) {
                sliders.motor_capability.value = targetMotor.toString();
                sliderValEls.motor_capability.textContent = targetMotor.toFixed(1);
                if (targetMotor < 0.6) {
                    addLog(`🧠 Interaction analysis → Motor Capability: ${targetMotor}`, 'rx');
                }
                sendUserStateUpdate();
            }

            // ─── Cognitive Load: based on time on screen + errors ───
            let targetCognitive = 0.0;
            const timeOnScreen = (Date.now() - this.screenEntryTime) / 1000;
            
            // Spending >15s on a screen = confusion
            if (timeOnScreen > 30) targetCognitive = 0.8;
            else if (timeOnScreen > 15) targetCognitive = 0.5;
            
            // Errors increase cognitive load
            if (this.errorCount >= 3) targetCognitive = Math.max(targetCognitive, 0.7);
            else if (this.errorCount >= 1) targetCognitive = Math.max(targetCognitive, 0.4);

            const currentCog = parseFloat(sliders.cognitive_load.value);
            if (Math.abs(currentCog - targetCognitive) > 0.1) {
                sliders.cognitive_load.value = targetCognitive.toString();
                sliderValEls.cognitive_load.textContent = targetCognitive.toFixed(1);
                if (targetCognitive > 0.4) {
                    addLog(`🧠 Interaction analysis → Cognitive Load: ${targetCognitive}`, 'rx');
                }
                sendUserStateUpdate();
            }

            // ─── Frustration: based on error count + rapid clicks ───
            let targetFrust = 0.0;
            if (this.errorCount >= 4) targetFrust = 0.8;
            else if (this.errorCount >= 2) targetFrust = 0.5;
            else if (this.errorCount >= 1) targetFrust = 0.3;
            
            // Rapid clicking = frustration
            if (this.clickTimes.length >= 4) {
                const recentGaps = [];
                const recent = this.clickTimes.slice(-4);
                for (let i = 1; i < recent.length; i++) {
                    recentGaps.push(recent[i] - recent[i - 1]);
                }
                const avgRecent = recentGaps.reduce((a, b) => a + b, 0) / recentGaps.length;
                if (avgRecent < 800) targetFrust = Math.max(targetFrust, 0.6);
            }

            const currentFrust = parseFloat(sliders.frustration_level.value);
            if (Math.abs(currentFrust - targetFrust) > 0.1) {
                sliders.frustration_level.value = targetFrust.toString();
                sliderValEls.frustration_level.textContent = targetFrust.toFixed(1);
                if (targetFrust > 0.3) {
                    addLog(`🧠 Interaction analysis → Frustration: ${targetFrust}`, 'rx');
                }
                sendUserStateUpdate();
            }
        }
    };

    // Check for idle time periodically
    setInterval(() => {
        const idleTime = (Date.now() - behaviorTracker.lastClickTime) / 1000;
        if (idleTime > 20 && !behaviorTracker.idleWarned && behaviorTracker.lastClickTime > 0) {
            behaviorTracker.idleWarned = true;
            const cog = parseFloat(sliders.cognitive_load.value);
            if (cog < 0.5) {
                sliders.cognitive_load.value = '0.6';
                sliderValEls.cognitive_load.textContent = '0.6';
                addLog('🧠 Long idle → Cognitive Load ↑ (user may be confused)', 'rx');
                sendUserStateUpdate();
            }
        }
    }, 5000);

    // ─── Kiosk Screen Click Delegation ───
    const kioskScreen = document.getElementById('kiosk-screen');
    let numpadValue = '';

    kioskScreen.addEventListener('click', (e) => {
        const target = e.target.closest('[data-action]');
        const numpadKey = e.target.closest('.numpad-key');

        if (numpadKey) {
            const key = numpadKey.dataset.key;
            const display = document.getElementById('kiosk-input-display');
            if (!display) return;
            if (key === '⌫') {
                numpadValue = numpadValue.slice(0, -1);
            } else if (key && numpadValue.length < 10) {
                numpadValue += key;
            }
            display.textContent = numpadValue || display.dataset?.placeholder || '₹ 0';
            return;
        }

        if (target) {
            const action = target.dataset.action;
            addLog(`🖱️ Button pressed: ${action}`, 'info');
            behaviorTracker.recordClick(); // Track click timing

            const params = {};
            if (action === 'SUBMIT_AMOUNT' && numpadValue) {
                params.amount = parseInt(numpadValue, 10);
                numpadValue = '';
            }
            if (action === 'SUBMIT_PIN') {
                numpadValue = '';
            }
            wsClient.send({
                type: "kiosk_button_press",
                action: action,
                parameters: params
            });
        }
    });

    // Hook into agent responses to track errors and screen changes
    const _origHandleAgent = handleAgentResponse;
    const _origHandleScreen = handleKioskScreenUpdate;
    
    // Patch handleAgentResponse to detect errors
    window._behaviorTracker = behaviorTracker;

    window._lastInteractionTime = Date.now();
});
