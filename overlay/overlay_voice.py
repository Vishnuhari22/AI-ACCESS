import pyttsx3
import speech_recognition as sr
import threading
import time


class OverlayVoice:
    def __init__(self):
        # SpeechRecognition recognizer — stateless, safe to share
        self.recognizer = sr.Recognizer()
        self._is_speaking = False
        self._speak_lock = threading.Lock()

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

    def listen_sync(self, timeout: int = 7, language: str = "en-IN") -> tuple[str, str]:
        """Blocks until speech is heard (or timeout) and returns (transcript, error_msg).

        Returns:
            tuple: (transcript_text, error_message)
                - On success: ("recognized text", "")
                - On failure: ("", "descriptive error message")

        Args:
            timeout: seconds to wait for speech to *start*
            language: language code for speech recognition (e.g. 'en-IN', 'hi-IN', 'ta-IN')
        """
        try:
            with sr.Microphone() as source:
                print("[Voice] Adjusting for ambient noise...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                print(f"[Voice] Listening ({language})...")
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=10    # never hang longer than 10 s
                )
                print(f"[Voice] Recognizing via Google Speech ({language})...")
                text = self.recognizer.recognize_google(audio, language=language)
                print(f"[Voice] Transcribed: '{text}'")
                return (text, "")
        except sr.WaitTimeoutError:
            print("[Voice] Timeout — no speech detected.")
            return ("", "No speech detected (timeout)")
        except sr.UnknownValueError:
            print("[Voice] Speech unclear — could not transcribe.")
            return ("", "Speech unclear — could not transcribe")
        except sr.RequestError as e:
            print(f"[Voice] Google Speech API error: {e}")
            return ("", f"Speech API unavailable: {e}")
        except OSError as e:
            print(f"[Voice] Microphone error: {e}")
            return ("", f"Microphone error: {e}")
        except Exception as e:
            print(f"[Voice] Unexpected ASR error: {e}")
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
            try:
                text = recognizer.recognize_google(audio, language=language)
                if text:
                    print(f"[Voice|Continuous] Heard ({language}): '{text}'")
                    if wake_pattern.search(text):
                        print(f"[Voice|Continuous] Wake word '{wake_word}' detected!")
                        # Remove wake word from text
                        clean_text = wake_pattern.sub('', text).strip()
                        # Invoke callback with the remainder
                        callback(clean_text)
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                pass
            except Exception as e:
                print(f"[Voice|Continuous] Error: {e}")

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
