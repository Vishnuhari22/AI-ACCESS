class UIAAVoiceSystem {
    constructor(onTranscriptCallback, onStateChangeCallback) {
        this.onTranscript = onTranscriptCallback;
        this.onStateChange = onStateChangeCallback; // e.g., 'listening', 'stopped', 'error'
        
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
        if (this.recognition) {
            try {
                this.recognition.start();
            } catch (e) {
                console.error("Could not start recognition", e);
            }
        }
    }

    stopListening() {
        if (this.recognition) {
            this.recognition.stop();
        }
    }

    speak(text, lang = 'en-IN') {
        if (!this.synth) {
            console.error("Speech Synthesis not supported");
            return;
        }

        // Cancel any ongoing speech so they don't overlap awkwardly
        this.synth.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = lang;
        utterance.rate = 1.0; 
        
        this.synth.speak(utterance);
    }
}
