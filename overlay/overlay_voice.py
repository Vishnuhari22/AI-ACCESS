import io
import os
import re
import threading
import time
import winsound
import numpy as np
import pyttsx3
import speech_recognition as sr

# Optional faster-whisper import
try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False


def play_earcon(tone_type: str):
    """Plays non-blocking audio cues (earcons) to guide blind/visually impaired users."""
    def _beep():
        try:
            if tone_type == "wake":
                # Ascending dual chime ("I'm listening!")
                winsound.Beep(750, 90)
                winsound.Beep(1150, 140)
            elif tone_type == "listen":
                # Single gentle cue ("Mic is open")
                winsound.Beep(950, 90)
            elif tone_type == "processing":
                # Soft double click ("Processing your voice")
                winsound.Beep(1100, 70)
                winsound.Beep(850, 90)
            elif tone_type == "error":
                # Descending/low error tone ("Did not catch that")
                winsound.Beep(450, 120)
                time.sleep(0.04)
                winsound.Beep(350, 150)
        except Exception:
            pass

    threading.Thread(target=_beep, daemon=True).start()


class OverlayVoice:
    def __init__(self):
        # SpeechRecognition recognizer — stateless, safe to share
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        
        self._is_speaking = False
        self._speak_lock = threading.Lock()

        # Faster-Whisper local model for high-accuracy offline transcription
        self._whisper_model = None
        self._whisper_ready = False
        self._whisper_thread = None
        if HAS_WHISPER:
            self._whisper_thread = threading.Thread(target=self._init_whisper, daemon=True)
            self._whisper_thread.start()

    def _init_whisper(self):
        """Initializes Whisper in background so overlay UI starts instantly."""
        try:
            print("[Voice] Loading local Whisper model (tiny.en, int8)...")
            self._whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
            self._whisper_ready = True
            print("[Voice] Local Whisper model loaded and ready.")
        except Exception as e:
            print(f"[Voice] Whisper initialization notice: {e}. Will use Google Speech.")
            self._whisper_ready = False

    def play_earcon(self, tone_type: str):
        play_earcon(tone_type)

    def speak(self, text: str, rate: int = 175, sensitive: bool = False, block: bool = False) -> bool:
        """Speaks the given text using local TTS (pyttsx3). Returns False if blocked by privacy rules.
           If block is True, this method blocks until speech finishes."""
        if not text:
            return True

        # Privacy gate — never speak sensitive data over public speakers
        if sensitive:
            try:
                from audio_privacy import is_headphone_connected
                if not is_headphone_connected():
                    print("[Voice] Sensitive data suppressed — no headphones detected.")
                    return False
            except ImportError:
                # Module not available — assume public (safe default)
                print("[Voice] audio_privacy unavailable — suppressing sensitive TTS.")
                return False

        # Wait if another TTS is playing and this is a blocking call
        if block:
            while True:
                with self._speak_lock:
                    if not self._is_speaking:
                        self._is_speaking = True
                        break
                time.sleep(0.1)
        else:
            with self._speak_lock:
                if self._is_speaking:
                    print("[Voice] Already speaking — skipping overlapping TTS call.")
                    return True
                self._is_speaking = True

        def run_tts():
            try:
                engine = pyttsx3.init()
                engine.setProperty('rate', rate)   # configurable rate
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            except Exception as e:
                print(f"[Voice] TTS error: {e}")
            finally:
                with self._speak_lock:
                    self._is_speaking = False

        tts_thread = threading.Thread(target=run_tts, daemon=True)
        tts_thread.start()
        
        if block:
            tts_thread.join()
            
        return True

    def _transcribe_audio_data(self, audio_data: sr.AudioData, language: str = "en-IN") -> str:
        """Transcribes audio using local Whisper if available, falling back to Google Speech."""
        # Wait up to 3 seconds for Whisper to finish initial background load if it's currently loading
        if not self._whisper_ready and self._whisper_thread and self._whisper_thread.is_alive():
            self._whisper_thread.join(timeout=3.0)

        # Try local Whisper first (accurate, private, no network lag)
        if self._whisper_ready and self._whisper_model:
            try:
                raw_bytes = audio_data.get_raw_data(convert_rate=16000, convert_width=2)
                audio_np = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

                # Energy gate: check RMS to skip silence / background hum before running model
                rms = np.sqrt(np.mean(audio_np ** 2))
                if rms < 0.008:
                    # Pure background silence / breathing
                    return ""

                segments, info = self._whisper_model.transcribe(
                    audio_np, 
                    language="en", 
                    beam_size=1, 
                    vad_filter=False,
                    no_speech_threshold=0.6
                )
                filtered_texts = []
                for s in segments:
                    txt = s.text.strip()
                    # Filter common Whisper hallucination artifacts on ambient silence
                    cleaned_lower = re.sub(r'[^\w\s]', '', txt.lower()).strip()
                    if cleaned_lower in ["thank you", "thanks", "you", "okay", "bye", "subtitles by", "translated by"]:
                        continue
                    if txt:
                        filtered_texts.append(txt)

                text = " ".join(filtered_texts).strip()
                if text:
                    print(f"[Voice] Transcribed via Whisper: '{text}'")
                return text
            except Exception as e:
                print(f"[Voice] Whisper error ({e}), falling back to Google Speech...")

        # Fallback to Google Speech
        print(f"[Voice] Transcribing via Google Speech ({language})...")
        return self.recognizer.recognize_google(audio_data, language=language)

    def listen_sync(self, timeout: int = 7, language: str = "en-IN") -> tuple[str, str]:
        """Blocks until speech is heard (or timeout) and returns (transcript, error_msg).

        Returns:
            tuple: (transcript_text, error_message)
                - On success: ("recognized text", "")
                - On failure: ("", "descriptive error message")
        """
        try:
            with sr.Microphone() as source:
                print("[Voice] Adjusting for ambient noise...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                
                # Audio feedback for blind users: mic is open
                play_earcon("listen")
                print(f"[Voice] Listening ({language})...")
                
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=10    # never hang longer than 10 s
                )
                
                # Audio feedback for blind users: audio captured, processing
                play_earcon("processing")
                
                text = self._transcribe_audio_data(audio, language=language)
                return (text, "")
        except sr.WaitTimeoutError:
            play_earcon("error")
            print("[Voice] Timeout — no speech detected.")
            return ("", "No speech detected (timeout)")
        except sr.UnknownValueError:
            play_earcon("error")
            print("[Voice] Speech unclear — could not transcribe.")
            return ("", "Speech unclear — could not transcribe")
        except sr.RequestError as e:
            play_earcon("error")
            print(f"[Voice] Speech API error: {e}")
            return ("", f"Speech API unavailable: {e}")
        except OSError as e:
            play_earcon("error")
            print(f"[Voice] Microphone error: {e}")
            return ("", f"Microphone error: {e}")
        except Exception as e:
            play_earcon("error")
            print(f"[Voice] Unexpected ASR error: {e}")
            return ("", f"Voice error: {e}")

    def listen_continuous(self, wake_word: str = "access", callback=None, language: str = "en-IN"):
        """
        Listens continuously in the background for the wake word ('access', 'hey access', etc.).
        Immediately sounds an ascending chime when detected, extracts any trailing command,
        and invokes the callback.
        
        Returns a stop function to cancel listening.
        """
        # Supports variations like "access", "hey access", "ok access", "okay access"
        wake_pattern = re.compile(
            r'\b(?:hey\s+|ok\s+|okay\s+)?' + re.escape(wake_word.lower()) + r'\b', 
            re.IGNORECASE
        )
        
        def _callback(recognizer, audio):
            if self._is_speaking:
                return  # Don't listen to our own TTS voice
            try:
                text = self._transcribe_audio_data(audio, language=language)
                if text:
                    print(f"[Voice|Continuous] Heard: '{text}'")
                    if wake_pattern.search(text):
                        print(f"[Voice|Continuous] Wake word '{wake_word}' detected!")
                        # Instant auditory earcon for blind users
                        play_earcon("wake")
                        
                        # Extract the command after the wake word
                        clean_text = wake_pattern.sub('', text, count=1).strip()
                        # Clean leading punctuation like comma, dot, colon
                        clean_text = re.sub(r'^[,\.\:\;\!\?]+\s*', '', clean_text).strip()
                        
                        if callback:
                            callback(clean_text)
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                pass
            except Exception as e:
                print(f"[Voice|Continuous] Callback error: {e}")

        source = sr.Microphone()
        print("[Voice|Continuous] Calibrating microphone for background wake word listening...")
        with source as s:
            self.recognizer.adjust_for_ambient_noise(s, duration=0.8)
            
        print(f"[Voice|Continuous] Starting background listener (Wake word: '{wake_word}', Language: {language})...")
        # Use phrase_time_limit=4 so wake words are spotted promptly
        stop_listening = self.recognizer.listen_in_background(source, _callback, phrase_time_limit=4)
        return stop_listening


if __name__ == "__main__":
    voice = OverlayVoice()
    print("Testing OverlayVoice...")
    play_earcon("wake")
    time.sleep(0.5)
    voice.speak("System ready. Say 'access' or speak a command.")
    text, err = voice.listen_sync(timeout=5)
    if text:
        voice.speak(f"You said: {text}")
    else:
        voice.speak(f"I didn't catch that. {err}")
