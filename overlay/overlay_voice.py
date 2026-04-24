import pyttsx3
import speech_recognition as sr
import threading


class OverlayVoice:
    def __init__(self):
        # SpeechRecognition recognizer — stateless, safe to share
        self.recognizer = sr.Recognizer()
        self._is_speaking = False
        self._speak_lock = threading.Lock()

    def speak(self, text: str):
        """Speaks the text aloud on a background thread.

        pyttsx3 on Windows is NOT safe to call from arbitrary threads if a
        persistent engine object is shared.  Re-initialising the engine inside
        the TTS thread is the most reliable workaround on Windows.
        """
        if not text:
            return
        with self._speak_lock:
            if self._is_speaking:
                print("[Voice] Already speaking — skipping overlapping TTS call.")
                return
            self._is_speaking = True

        def run_tts():
            try:
                engine = pyttsx3.init()
                engine.setProperty('rate', 160)   # slower for accessibility
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            except Exception as e:
                print(f"[Voice] TTS error: {e}")
            finally:
                with self._speak_lock:
                    self._is_speaking = False

        threading.Thread(target=run_tts, daemon=True).start()

    def listen_sync(self, timeout: int = 7) -> tuple[str, str]:
        """Blocks until speech is heard (or timeout) and returns (transcript, error_msg).

        Returns:
            tuple: (transcript_text, error_message)
                - On success: ("recognized text", "")
                - On failure: ("", "descriptive error message")

        Args:
            timeout: seconds to wait for speech to *start*
        """
        try:
            with sr.Microphone() as source:
                print("[Voice] Adjusting for ambient noise...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                print("[Voice] Listening...")
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=10    # never hang longer than 10 s
                )
                print("[Voice] Recognizing via Google Speech...")
                text = self.recognizer.recognize_google(audio)
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


if __name__ == "__main__":
    voice = OverlayVoice()
    voice.speak("System ready. Please say something.")
    text, err = voice.listen_sync(timeout=7)
    if text:
        voice.speak(f"You said: {text}")
    else:
        voice.speak(f"I didn't catch that. {err}")
