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
        self._baseline_pitch = 0.0         # baseline head pitch (looking straight)
        self._baseline_eye_gap = 0.0       # baseline normalised eye openness
        self._frames_since_recal = 0
        self._pitch_history = []           # rolling buffer for pitch smoothing
        self._eye_history = []             # rolling buffer for squinting smoothing
        self._eye_calibration_buf = []     # buffer to collect initial eye readings for baseline
        self._debug_frame_count = 0        # for initial debug logging

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

        # Initialise or periodically recalibrate baselines
        self._frames_since_recal += 1
        if self._baseline_face_width < 0.01 or self._frames_since_recal >= self.BASELINE_RECAL_INTERVAL:
            self._baseline_face_width  = face_width
            self._baseline_face_height = face_height if face_height > 0.01 else self._baseline_face_height
            self._frames_since_recal   = 0

        # 1. Leaning-forward detection (face appears larger than baseline)
        is_leaning = face_width > (self._baseline_face_width * 1.25)

        # 2. Head pitch estimation — baseline-relative approach.
        #    The nose tip (#1) is ALWAYS below the nose bridge (#6) anatomically,
        #    so we can't use a fixed threshold.  Instead we calibrate the
        #    "straight-ahead" pitch when the face first appears, then flag
        #    "looking down" only when pitch exceeds baseline + delta.
        nose_tip    = landmarks[1]
        nose_bridge = landmarks[6]
        pitch_delta = nose_tip.y - nose_bridge.y          # always positive
        norm_pitch  = pitch_delta / face_height if face_height > 0.01 else 0

        # Smooth pitch over 6 frames to avoid flicker
        self._pitch_history.append(norm_pitch)
        if len(self._pitch_history) > 6:
            self._pitch_history.pop(0)
        smoothed_pitch = sum(self._pitch_history) / len(self._pitch_history)

        # Calibrate baseline pitch from the first stable readings
        if self._baseline_pitch < 0.01 and len(self._pitch_history) >= 4:
            self._baseline_pitch = smoothed_pitch
            print(f"[Vision] Baseline pitch calibrated: {self._baseline_pitch:.4f}")

        # Flag looking-down only when pitch exceeds baseline by >0.08
        is_looking_down = (self._baseline_pitch > 0.01
                           and smoothed_pitch > self._baseline_pitch + 0.08)

        # Debug: log values for the first 40 frames to help with tuning
        self._debug_frame_count += 1
        if self._debug_frame_count <= 40:
            print(f"[Vision] frame {self._debug_frame_count}: "
                  f"pitch={norm_pitch:.4f} sm_pitch={smoothed_pitch:.4f} "
                  f"bsl_pitch={self._baseline_pitch:.4f} down={is_looking_down}")

        # 3. Squinting detection — BASELINE-RELATIVE approach
        #    Instead of a fixed threshold, we calibrate the user's normal eye
        #    openness from the first ~15 frames and then detect squinting when
        #    the smoothed eye gap drops below 70% of their personal baseline.
        #    Average BOTH eyes (left: 159/145, right: 386/374) for robustness.
        left_eye_gap  = abs(landmarks[159].y - landmarks[145].y)
        right_eye_gap = abs(landmarks[386].y - landmarks[374].y)
        eye_gap = (left_eye_gap + right_eye_gap) / 2

        # Rolling 10-frame average to prevent single-blink false positives
        self._eye_history.append(eye_gap)
        if len(self._eye_history) > 10:
            self._eye_history.pop(0)
        smoothed_gap = sum(self._eye_history) / len(self._eye_history)

        norm_gap = smoothed_gap / face_height if face_height > 0.01 else smoothed_gap

        # Calibrate baseline eye openness from first 15 stable readings
        if self._baseline_eye_gap < 0.001 and not is_looking_down:
            self._eye_calibration_buf.append(norm_gap)
            if len(self._eye_calibration_buf) >= 15:
                # Use the median to be robust against blinks during calibration
                sorted_buf = sorted(self._eye_calibration_buf)
                self._baseline_eye_gap = sorted_buf[len(sorted_buf) // 2]
                print(f"[Vision] Baseline eye openness calibrated: {self._baseline_eye_gap:.4f}")

        # Determine squinting: eye gap < 70% of baseline, gated on neutral pitch
        if self._baseline_eye_gap > 0.001:
            squint_ratio = norm_gap / self._baseline_eye_gap
            is_squinting = squint_ratio < 0.70 and not is_looking_down
        else:
            # Not yet calibrated — don't flag squinting
            squint_ratio = 1.0
            is_squinting = False

        with self._lock:
            self.user_state.update({
                "face_detected": True,
                "squinting": is_squinting,
                "looking_down": is_looking_down,
                "leaning_forward": is_leaning
            })
            return self.user_state.copy()

    def release(self):
        self.cap.release()

