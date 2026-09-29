import pyttsx3
import speech_recognition as sr
import threading
import time
import queue

class OverlayVoice:
    def __init__(self):
        # SpeechRecognition recognizer — stateless, safe to share
        self.recognizer = sr.Recognizer()
        # Improve default transcription accuracy by raising energy threshold implicitly
        self.recognizer.energy_threshold = 300 
        self.recognizer.dynamic_energy_threshold = True

        self._is_speaking = False
        self._speak_lock = threading.Lock()
        
        # Dedicated TTS Queue & Worker
        self._speech_queue = queue.Queue()
        self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self._tts_thread.start()

    def _tts_worker(self):
        """Background worker that initializes pyttsx3 once and speaks queued items.
        Solves COM initialization leaks on Windows."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass

        while True:
            try:
                item = self._speech_queue.get()
                if item is None: # Poison pill
                    break
                text, rate, sensitive = item
                
                # Privacy gate: Only suppress if it explicitly reveals secret credential values
                suppressed = False
                if sensitive:
                    # Only suppress if text actually reveals passwords, pins or cvvs
                    lower_t = text.lower()
                    has_secrets = any(w in lower_t for w in ["cvv is", "password is", "pin is", "card number is"])
                    if has_secrets:
                        try:
                            from audio_privacy import is_headphone_connected
                            if not is_headphone_connected():
                                print(f"[Voice] Sensitive secret suppressed from speakers: '{text[:30]}...'")
                                suppressed = True
                        except Exception:
                            pass
                
                if not suppressed:
                    with self._speak_lock:
                        self._is_speaking = True
                    try:
                        # Re-initialize pyttsx3 on every utterance!
                        # This forces SAPI5 to bind to the CURRENT default audio device,
                        # fixing the bug where audio doesn't route to newly plugged-in headphones.
                        engine = pyttsx3.init()
                        engine.setProperty('rate', rate)
                        engine.say(text)
                        engine.runAndWait()
                        # Cleanup the engine to release COM resources
                        del engine
                    except Exception as e:
                        print(f"[Voice] TTS playback error ({e}). Trying Windows PowerShell TTS fallback...")
                        try:
                            # PowerShell fallback
                            import subprocess
                            clean_text = text.replace('"', '`"').replace("'", " ")
                            ps_cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{clean_text}')"
                            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], timeout=10, creationflags=0x08000000)
                        except Exception as ps_err:
                            print(f"[Voice] PowerShell TTS fallback error: {ps_err}")
                    finally:
                        with self._speak_lock:
                            self._is_speaking = False
                
                self._speech_queue.task_done()
            except Exception as e:
                print(f"[Voice] TTS worker error: {e}")

    def speak(self, text: str, rate: int = 175, sensitive: bool = False, block: bool = False) -> bool:
        """Queues text to be spoken. If block=True, waits until it finishes."""
        if not text or not text.strip():
            return True

        # Never suppress speech if it contains questions or assistance instructions
        lower_t = text.lower()
        is_secret_value = any(w in lower_t for w in ["cvv is", "password is", "pin is", "card number is"])
        
        if sensitive and is_secret_value:
            try:
                from audio_privacy import is_headphone_connected
                if not is_headphone_connected():
                    print(f"[Voice] Secret credentials suppressed from speakers — no headphones. (Text: '{text[:30]}...')")
                    import winsound
                    threading.Thread(target=lambda: winsound.Beep(600, 150), daemon=True).start()
                    return False
            except Exception as e:
                print(f"[Voice] audio_privacy check failed: {e}")
            
        self._speech_queue.put((text, rate, sensitive))
        if block:
            self._speech_queue.join()
            
        return True

    def _transcribe_with_gemini(self, audio: sr.AudioData, language: str = "en-IN", context: str = "") -> str:
        """Transcribes audio using Gemini Flash models with automatic fallback on overload/high demand."""
        try:
            from screen_reader import get_gemini_client
            from google.genai import types
            client = get_gemini_client()
            if not client:
                return ""
            wav_bytes = audio.get_wav_data()
            print(f"[Voice] Transcribing via Gemini Flash ({len(wav_bytes)} bytes)...")
            
            prompt = (f"You are a speech-to-text transcriber. Transcribe this spoken audio verbatim. "
                      f"Expected language: {language}. Return ONLY the exact transcribed words. "
                      f"If the audio contains no human speech or only background noise, return an empty string.")
            if context:
                prompt += f"\nContext: The user is currently looking at a screen where the following context applies: {context}. Use this to help recognize proper nouns, domain-specific words, or city names."
            
            # Models to try for ASR (gemini-3.5-flash-lite has active quota)
            asr_models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]
            
            for m in asr_models:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=[
                            prompt,
                            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
                        ],
                        config=types.GenerateContentConfig(
                            temperature=0.0,
                            max_output_tokens=256
                        )
                    )
                    text = (response.text or "").strip()
                    if text.startswith('"') and text.endswith('"'):
                        text = text[1:-1].strip()
                    if text:
                        return text
                except Exception as asr_err:
                    print(f"[Voice] Gemini ASR model {m} failed/busy: {asr_err}")
                    continue
            return ""
        except Exception as e:
            print(f"[Voice] Gemini ASR overall error: {e}")
            return ""

    def _normalize_digits(self, text: str) -> str:
        """Converts spoken number words into clean numeric digits (e.g., 'four five' -> '45')."""
        import re
        word_to_num = {
            'zero': '0', 'oh': '0', 'one': '1', 'two': '2', 'three': '3',
            'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
            'for': '4', 'to': '2', 'too': '2'
        }
        words = text.split()
        normalized = []
        for w in words:
            clean_w = w.lower().strip(',.?!')
            if clean_w in word_to_num:
                normalized.append(word_to_num[clean_w])
            else:
                normalized.append(w)
        
        result = " ".join(normalized)
        # Squish consecutive digits separated by spaces (e.g. "4 5 8 9" -> "4589")
        result = re.sub(r'(?<=\d)\s+(?=\d)', '', result)
        return result

    def listen_sync(self, timeout: int = 7, language: str = "en-IN", context: str = "") -> tuple[str, str]:
        """Blocks until speech is heard (or timeout) and returns (transcript, error_msg)."""
        import winsound
        audio = None
        try:
            with sr.Microphone() as source:
                print("[Voice] Adjusting for ambient noise...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                print(f"[Voice] Listening ({language})...")
                # Play high chime to indicate mic is ON
                winsound.Beep(1000, 150)
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=15    # Extended from 10s to allow fuller sentences
                )
                # Play lower chime to indicate speech captured
                winsound.Beep(700, 150)
        except sr.WaitTimeoutError:
            print("[Voice] Timeout — no speech detected.")
            winsound.Beep(400, 250)
            return ("", "No speech detected (timeout)")
        except Exception as mic_err:
            print(f"[Voice] Microphone recording error: {mic_err}")
            return ("", f"Microphone error: {mic_err}")

        # Try Google Web Speech first; seamlessly fall back to Gemini on any connection issue or unclear audio
        def process_transcript(t):
            t = self._normalize_digits(t)
            print(f"[Voice] Final Transcript: '{t}'")
            return (t, "")

        try:
            print(f"[Voice] Recognizing via Google Speech ({language})...")
            text = self.recognizer.recognize_google(audio, language=language)
            return process_transcript(text)
        except sr.UnknownValueError:
            print("[Voice] Google Speech marked audio unclear. Checking Gemini ASR...")
            gemini_text = self._transcribe_with_gemini(audio, language=language, context=context)
            if gemini_text:
                return process_transcript(gemini_text)
            return ("", "Speech unclear — could not transcribe")
        except (sr.RequestError, OSError, ConnectionError) as net_err:
            print(f"[Voice] Google Speech connection failed ({net_err}). Falling back to Gemini ASR...")
            gemini_text = self._transcribe_with_gemini(audio, language=language, context=context)
            if gemini_text:
                return process_transcript(gemini_text)
            return ("", f"Speech service unavailable: {net_err}")
        except Exception as e:
            print(f"[Voice] Unexpected recognition error ({e}). Trying Gemini ASR...")
            gemini_text = self._transcribe_with_gemini(audio, language=language, context=context)
            if gemini_text:
                return process_transcript(gemini_text)
            return ("", f"Voice error: {e}")

    def listen_continuous(self, wake_word: str, callback, language: str = "en-IN"):
        """
        Listens continuously in the background for a wake word.
        When wake word is heard, it calls the callback function with the full text.
        
        Returns a stop function to stop listening.
        """
        import re
        wake_pattern = re.compile(r'\b' + re.escape(wake_word.lower()) + r'\b', re.IGNORECASE)
        
        def _callback(recognizer, audio):
            if self._is_speaking:
                return # Don't listen to our own voice
            text = ""
            try:
                text = recognizer.recognize_google(audio, language=language)
            except (sr.RequestError, OSError, ConnectionError):
                text = self._transcribe_with_gemini(audio, language=language)
            except Exception:
                pass

            if text:
                print(f"[Voice|Continuous] Heard ({language}): '{text}'")
                if wake_pattern.search(text):
                    print(f"[Voice|Continuous] Wake word '{wake_word}' detected!")
                    clean_text = wake_pattern.sub('', text).strip()
                    callback(clean_text)

        source = sr.Microphone()
        print("[Voice|Continuous] Calibrating microphone for background listening...")
        with source as s:
            self.recognizer.adjust_for_ambient_noise(s, duration=1.0)
            
        print(f"[Voice|Continuous] Starting background listener (Wake word: '{wake_word}', Language: {language})...")
        stop_listening = self.recognizer.listen_in_background(source, _callback, phrase_time_limit=5)
        return stop_listening
if __name__ == "__main__":
    voice = OverlayVoice()
    voice.speak("System ready. Please say something.")
    text, err = voice.listen_sync(timeout=7)
    if text:
        voice.speak(f"You said: {text}")
    else:
        voice.speak(f"I didn't catch that. {err}")
