import os
import threading
import urllib.request
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


class OverlayVision:
    # Re-calibrate baseline every N successful detections to adapt to user moving
    BASELINE_RECAL_INTERVAL = 60

    def __init__(self):
        model_path = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
        if not os.path.exists(model_path):
            print("[Vision] Downloading face_landmarker.task model...")
            urllib.request.urlretrieve(
                "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
                model_path
            )
            print("[Vision] Download complete.")

        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,  # explicit — synchronous frame-by-frame
            num_faces=1
        )
        self.detector = vision.FaceLandmarker.create_from_options(options)

        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            raise RuntimeError("[Vision] Could not open webcam (index 0). Is a camera connected?")

        # Shared state — protected by _lock
        self._lock = threading.Lock()
        self.user_state = {
            "face_detected": False,
            "squinting": False,
            "leaning_forward": False
        }

        self._baseline_face_width = 0.0
        self._baseline_face_height = 0.0   # used to normalise eye gap threshold
        self._frames_since_recal = 0
        self._eye_history = []              # rolling buffer for squinting smoothing

    def get_latest_state(self) -> dict:
        """Captures one frame, runs landmark detection, and returns the updated state dict."""
        success, image = self.cap.read()
        if not success:
            with self._lock:
                self.user_state["face_detected"] = False
                return self.user_state.copy()

        image = cv2.flip(image, 1)
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)

        detection_result = self.detector.detect(mp_image)

        if not detection_result.face_landmarks:
            with self._lock:
                self.user_state["face_detected"] = False
                return self.user_state.copy()

        landmarks = detection_result.face_landmarks[0]

        # --- Face geometry ---
        left_cheek  = landmarks[234]
        right_cheek = landmarks[454]
        chin        = landmarks[152]
        forehead    = landmarks[10]
        face_width  = abs(left_cheek.x - right_cheek.x)
        face_height = abs(forehead.y  - chin.y)

        # Initialise or periodically recalibrate the baseline width
        self._frames_since_recal += 1
        if self._baseline_face_width < 0.01 or self._frames_since_recal >= self.BASELINE_RECAL_INTERVAL:
            self._baseline_face_width  = face_width
            self._baseline_face_height = face_height if face_height > 0.01 else self._baseline_face_height
            self._frames_since_recal   = 0

        # 1. Leaning-forward detection (face appears larger than baseline)
        is_leaning = face_width > (self._baseline_face_width * 1.25)

        # 2. Squinting detection — eye gap normalised against face height
        #    Raw pixel gap varies strongly with distance; dividing by face_height makes it scale-invariant.
        #    Average BOTH eyes (left: 159/145, right: 386/374) for robustness — matches vision.js.
        left_eye_gap  = abs(landmarks[159].y - landmarks[145].y)
        right_eye_gap = abs(landmarks[386].y - landmarks[374].y)
        eye_gap = (left_eye_gap + right_eye_gap) / 2

        # Rolling 8-frame average to prevent single-blink false positives
        self._eye_history.append(eye_gap)
        if len(self._eye_history) > 8:
            self._eye_history.pop(0)
        smoothed_gap = sum(self._eye_history) / len(self._eye_history)

        norm_gap   = smoothed_gap / face_height if face_height > 0.01 else smoothed_gap
        # Threshold 0.06 of face height — empirically robust across distances
        is_squinting = norm_gap < 0.06

        with self._lock:
            self.user_state.update({
                "face_detected": True,
                "squinting": is_squinting,
                "leaning_forward": is_leaning
            })
            return self.user_state.copy()

    def release(self):
        self.cap.release()

