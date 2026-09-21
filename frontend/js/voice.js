class UIAAVoiceSystem {
    constructor(onTranscriptCallback, onStateChangeCallback) {
        this.onTranscript = onTranscriptCallback;
        this.onStateChange = onStateChangeCallback; // e.g., 'listening', 'stopped', 'error'
        this._autoStopTimer = null;
        // ASR Support Check
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.error("Speech Recognition API not supported in this browser.");
            this.recognition = null;
        } else {
            this.recognition = new SpeechRecognition();
            this.recognition.continuous = false;
            this.recognition.interimResults = true;
            this.recognition.lang = 'en-IN'; // Default to Indian English, can be dynamic
            
            this.setupRecognitionEvents();
        }
        
        // TTS Setup
        this.synth = window.speechSynthesis;
    }

    setupRecognitionEvents() {
        if (!this.recognition) return;

        this.recognition.onstart = () => {
            this.onStateChange('listening');
        };

        this.recognition.onresult = (event) => {
            let finalTranscript = '';
            let interimTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }

            this.onTranscript(finalTranscript, interimTranscript);
        };

        this.recognition.onerror = (event) => {
            console.error("Speech Recognition Error:", event.error);
            this.onStateChange('error');
        };

        this.recognition.onend = () => {
            this.onStateChange('stopped');
        };
    }

    startListening() {
        if (this._autoStopTimer) {
            clearTimeout(this._autoStopTimer);
            this._autoStopTimer = null;
        }
        if (this.recognition) {
            try {
                this.recognition.start();
            } catch (e) {
                // If recognition is already started, restart it cleanly
                try {
                    this.recognition.stop();
                    setTimeout(() => {
                        try { this.recognition.start(); } catch (err) {}
                    }, 150);
                } catch (err) {}
            }
        }
    }

    stopListening() {
        if (this._autoStopTimer) {
            clearTimeout(this._autoStopTimer);
            this._autoStopTimer = null;
        }

        if (this.recognition) {
            try {
                this.recognition.stop();
            } catch (e) {}
        }
    }

    speak(text, lang = 'en-IN', onEnd = null) {
        if (!this.synth) {
            console.error("Speech Synthesis not supported");
            if (onEnd) onEnd();
            return;
        }

        // Cancel any ongoing speech so they don't overlap awkwardly
        this.synth.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = lang;
        utterance.rate = 1.0; 

        // Store reference on window to prevent Chrome GC bug dropping onend
        window._activeUtterance = utterance;

        if (onEnd) {
            let triggered = false;
            const finish = () => {
                if (!triggered) {
                    triggered = true;
                    onEnd();
                }
            };
            utterance.onend = finish;
            utterance.onerror = finish;
            // Fallback timeout: guarantees callback runs even if browser drops onend
            const wordCount = (text || "").split(/\s+/).length;
            const timeoutMs = Math.max(1500, (wordCount / 2.5) * 1000 + 400);
            setTimeout(finish, timeoutMs);
        }
        
        this.synth.speak(utterance);
    }
}
