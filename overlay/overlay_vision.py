import os
import threading
import urllib.request
import cv2
import time
import math
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


class OverlayVision:
    # Re-calibrate baseline every N successful detections to adapt to user moving
    BASELINE_RECAL_INTERVAL = 60
    FACE_DETECTED_WINDOW = 4
    PITCH_SMOOTH_WINDOW = 5
    LOOKING_UP_DELTA = 0.07
    LOOKING_DOWN_DELTA = 0.07
    EYE_RECAL_INTERVAL = 120
    EYE_SMOOTH_WINDOW = 3
    SEATED_SMOOTH_WINDOW = 4
    
    SQUINT_BLENDSHAPE_THRESHOLD = 0.32
    BLINK_BLENDSHAPE_THRESHOLD = 0.65
    STANDING_DELTA_Y = 0.12
    TOP_FRAME_MARGIN = 0.08
    STANDING_EXIT_HOLD_SECS = 5.0

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
            num_faces=1,
            output_face_blendshapes=True
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
            "leaning_forward": False,
            "looking_down": False,
            "looking_up": False,
            "seated": False,
            "standing_above_frame": False
        }

        self._baseline_face_width = 0.0
        self._baseline_face_height = 0.0   # used to normalise eye gap threshold
        self._baseline_pitch = 0.0         # baseline head pitch (looking straight)
        self._baseline_eye_gap = 0.0       # baseline normalised eye openness (EAR)
        self._baseline_squint_score = 0.0  # baseline resting neural squint score
        self._baseline_seated_y = 0.0
        self._seated_calibration_buf = []
        self._pitch_calibration_buf = []
        self._squint_calibration_buf = []
        self._squint_history = []
        self._frames_since_pitch_adapt = 0
        
        self._frames_since_recal = 0
        self._frames_since_eye_recal = 0
        self._pitch_history = []           # rolling buffer for pitch smoothing
        self._eye_history = []             # rolling buffer for squinting smoothing
        self._eye_calibration_buf = []     # buffer to collect initial eye readings for baseline
        self._debug_frame_count = 0        # for initial debug logging
        
        # Standing exit tracking
        self._last_face_center_y = 0.5
        self._last_forehead_y = 0.5
        self._last_face_time = 0.0
        self._standing_above_frame = False

        # Debounce buffers
        self._face_detection_history = []
        self._reported_face_detected = False
        self._seated_history = []
        self._reported_seated = False

    def _update_face_detected(self, raw_detected: bool):
        """Helper to debounce face detection over a rolling window."""
        self._face_detection_history.append(raw_detected)
        if len(self._face_detection_history) > self.FACE_DETECTED_WINDOW:
            self._face_detection_history.pop(0)
        votes_true = sum(self._face_detection_history)
        if votes_true > len(self._face_detection_history) // 2:
            self._reported_face_detected = True
        else:
            self._reported_face_detected = False

    def get_latest_state(self) -> dict:
        """Captures one frame, runs landmark detection, and returns the updated state dict."""
        success, image = self.cap.read()
        
        def handle_no_face():
            # Check standing out-of-frame hold logic
            current_time = time.time()
            if (self._last_face_center_y < 0.25 or self._last_forehead_y < self.TOP_FRAME_MARGIN) and \
               (current_time - self._last_face_time < self.STANDING_EXIT_HOLD_SECS):
                self._update_face_detected(True)
                self._standing_above_frame = True
                self._reported_seated = False
            else:
                self._update_face_detected(False)
                self._standing_above_frame = False

            with self._lock:
                self.user_state["face_detected"] = self._reported_face_detected
                self.user_state["standing_above_frame"] = self._standing_above_frame
                if self._standing_above_frame:
                    self.user_state["seated"] = False
                return self.user_state.copy()

        if not success:
            return handle_no_face()

        image = cv2.flip(image, 1)
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)

        detection_result = self.detector.detect(mp_image)

        if not detection_result.face_landmarks:
            return handle_no_face()

        # Face is detected in this frame
        self._update_face_detected(True)
        self._standing_above_frame = False
        self._last_face_time = time.time()

        landmarks = detection_result.face_landmarks[0]
        blendshapes = detection_result.face_blendshapes[0] if detection_result.face_blendshapes else None

        # --- Face geometry ---
        left_cheek  = landmarks[234]
        right_cheek = landmarks[454]
        chin        = landmarks[152]
        forehead    = landmarks[10]
        face_width  = abs(left_cheek.x - right_cheek.x)
        face_height = abs(forehead.y  - chin.y)
        
        self._last_face_center_y = (forehead.y + chin.y) / 2
        self._last_forehead_y = forehead.y

        # 1. Head pitch estimation — robust Eye-Nose-Chin vertical proportion
        left_eye_corner  = landmarks[33]
        right_eye_corner = landmarks[263]
        nose_tip         = landmarks[1]

        eye_y = (left_eye_corner.y + right_eye_corner.y) / 2
        eye_to_nose = nose_tip.y - eye_y
        eye_to_chin = chin.y - eye_y

        norm_pitch = eye_to_nose / eye_to_chin if eye_to_chin > 0.01 else 0

        # Smooth pitch over PITCH_SMOOTH_WINDOW frames
        self._pitch_history.append(norm_pitch)
        if len(self._pitch_history) > self.PITCH_SMOOTH_WINDOW:
            self._pitch_history.pop(0)
        smoothed_pitch = sum(self._pitch_history) / len(self._pitch_history)

        # Calibrate baseline pitch using median of first 15 frames
        if self._baseline_pitch < 0.01:
            self._pitch_calibration_buf.append(smoothed_pitch)
            if len(self._pitch_calibration_buf) >= 15:
                sorted_buf = sorted(self._pitch_calibration_buf)
                self._baseline_pitch = sorted_buf[len(sorted_buf) // 2]
                print(f"[Vision] Baseline pitch calibrated: {self._baseline_pitch:.4f}")

        # Flag looking-down and looking-up
        is_looking_down = (self._baseline_pitch > 0.01
                           and smoothed_pitch > self._baseline_pitch + self.LOOKING_DOWN_DELTA)
        is_looking_up = (self._baseline_pitch > 0.01
                         and smoothed_pitch < self._baseline_pitch - self.LOOKING_UP_DELTA)

        # 2. Leaning-forward detection (face appears larger than OLD baseline)
        is_leaning = False
        if self._baseline_face_width > 0.01:
            is_leaning = face_width > (self._baseline_face_width * 1.25)

        # 3. Initialise or periodically recalibrate face size baselines
        self._frames_since_recal += 1
        if self._baseline_face_width < 0.01:
            self._baseline_face_width  = face_width
            self._baseline_face_height = face_height if face_height > 0.01 else self._baseline_face_height
            self._frames_since_recal   = 0
        elif self._frames_since_recal >= self.BASELINE_RECAL_INTERVAL and not is_leaning:
            self._baseline_face_width  = face_width
            self._baseline_face_height = face_height if face_height > 0.01 else self._baseline_face_height
            self._frames_since_recal   = 0
            # Also slowly adapt baseline pitch
            if self._baseline_pitch > 0.01 and not is_looking_down and not is_looking_up:
                self._baseline_pitch = 0.90 * self._baseline_pitch + 0.10 * smoothed_pitch

        # 4. Squinting detection — Dual-Engine Approach with Personalised Baseline Calibration
        
        # Engine A: Neural Blendshapes
        squint_score = 0.0
        blink_score = 0.0
        
        if blendshapes:
            # Map blendshape category names to their scores
            bs_dict = {category.category_name: category.score for category in blendshapes}
            squint_score = (bs_dict.get("eyeSquintLeft", 0) + bs_dict.get("eyeSquintRight", 0)) / 2
            blink_score = (bs_dict.get("eyeBlinkLeft", 0) + bs_dict.get("eyeBlinkRight", 0)) / 2

        # Engine B: Geometric EAR
        def dist(p1, p2):
            return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)
            
        ear_left = (dist(landmarks[160], landmarks[144]) + dist(landmarks[158], landmarks[153])) / (2 * dist(landmarks[33], landmarks[133]))
        ear_right = (dist(landmarks[385], landmarks[380]) + dist(landmarks[387], landmarks[373])) / (2 * dist(landmarks[362], landmarks[263]))
        ear = (ear_left + ear_right) / 2
        
        self._eye_history.append(ear)
        if len(self._eye_history) > self.EYE_SMOOTH_WINDOW:
            self._eye_history.pop(0)
        smoothed_ear = sum(self._eye_history) / len(self._eye_history)
        
        # Calibrate baseline EAR and baseline neural squint (median of first 15 stable non-blink frames)
        if len(self._eye_calibration_buf) < 15 and not is_leaning and blink_score < 0.40:
            self._eye_calibration_buf.append(smoothed_ear)
            if blendshapes:
                self._squint_calibration_buf.append(squint_score)
            if len(self._eye_calibration_buf) >= 15:
                sorted_buf = sorted(self._eye_calibration_buf)
                self._baseline_eye_gap = sorted_buf[len(sorted_buf) // 2]
                if self._squint_calibration_buf:
                    sorted_sq = sorted(self._squint_calibration_buf)
                    self._baseline_squint_score = sorted_sq[len(sorted_sq) // 2]
                print(f"[Vision] Calibration complete: baseline EAR={self._baseline_eye_gap:.4f}, baseline squint={self._baseline_squint_score:.4f}")
                
        # Evaluate Engine A: Neural Blendshapes (relative to user's personal baseline)
        neural_squint = False
        if blendshapes and self.is_calibrated():
            delta = squint_score - self._baseline_squint_score
            # Must exceed resting baseline by at least 0.18 AND reach absolute 0.42
            if delta >= 0.18 and squint_score >= 0.42 and blink_score < 0.55:
                neural_squint = True

        # Evaluate Engine B: Geometric EAR
        geometric_squint = False
        is_blink = False
        ear_ratio = 1.0
        if self._baseline_eye_gap > 0.001:
            ear_ratio = smoothed_ear / self._baseline_eye_gap
            if ear_ratio < 0.28 or blink_score >= 0.60:
                is_blink = True
            elif ear_ratio < 0.60 and not is_looking_down and not is_blink:
                geometric_squint = True
        elif blink_score >= 0.60:
            is_blink = True
                
        # Dual-Engine Fusion: suppress during calibration, require confirmation
        if not self.is_calibrated():
            raw_squint = False
            is_squinting = False
            self._squint_history.clear()
        else:
            raw_squint = False
            if not is_blink:
                if blendshapes:
                    if neural_squint and ear_ratio < 0.85:
                        raw_squint = True
                    elif geometric_squint and (squint_score > self._baseline_squint_score + 0.08):
                        raw_squint = True
                    elif neural_squint and geometric_squint:
                        raw_squint = True
                else:
                    if geometric_squint and ear_ratio < 0.55:
                        raw_squint = True

            self._squint_history.append(raw_squint)
            if len(self._squint_history) > 5:
                self._squint_history.pop(0)
            # Require 3 out of 5 frames (~150-200ms) to confirm genuine sustained squint
            is_squinting = sum(self._squint_history) >= 3

        # Periodic EAR & squint baseline re-anchoring when user is resting normally
        self._frames_since_eye_recal += 1
        if (self.is_calibrated()
            and self._frames_since_eye_recal >= self.EYE_RECAL_INTERVAL
            and not is_leaning
            and not is_squinting
            and not is_blink
            and not is_looking_down):
            self._baseline_eye_gap = 0.90 * self._baseline_eye_gap + 0.10 * smoothed_ear
            if blendshapes and self._baseline_squint_score > 0:
                self._baseline_squint_score = 0.90 * self._baseline_squint_score + 0.10 * squint_score
            self._frames_since_eye_recal = 0
            print(f"[Vision] Baselines re-anchored: EAR={self._baseline_eye_gap:.4f}, squint={self._baseline_squint_score:.4f}")

        # 5. Seated detection - Baseline-Relative
        face_center_y = self._last_face_center_y
        
        if self._baseline_seated_y < 0.001 and not is_leaning:
            self._seated_calibration_buf.append(face_center_y)
            if len(self._seated_calibration_buf) >= 15:
                sorted_buf = sorted(self._seated_calibration_buf)
                self._baseline_seated_y = sorted_buf[len(sorted_buf) // 2]
                print(f"[Vision] Baseline seated Y calibrated: {self._baseline_seated_y:.4f}")
                
        raw_seated = True
        if self._baseline_seated_y > 0.001:
            # Standing if face center is significantly higher than seated baseline OR touching top of frame
            if face_center_y < self._baseline_seated_y - self.STANDING_DELTA_Y or forehead.y < self.TOP_FRAME_MARGIN:
                raw_seated = False
        else:
            # Fallback if uncalibrated
            raw_seated = face_center_y > 0.45
        
        self._seated_history.append(raw_seated)
        if len(self._seated_history) > self.SEATED_SMOOTH_WINDOW:
            self._seated_history.pop(0)
        seated_votes = sum(self._seated_history)
        self._reported_seated = seated_votes > len(self._seated_history) // 2

        # Debug: log values for the first 40 frames and whenever squinting is reported
        self._debug_frame_count += 1
        if self._debug_frame_count <= 40 or is_squinting:
            print(f"[Vision] f#{self._debug_frame_count}: "
                  f"sq={squint_score:.2f}(bsl={self._baseline_squint_score:.2f}) "
                  f"EAR={smoothed_ear:.3f}(bsl={self._baseline_eye_gap:.3f},r={ear_ratio:.2f}) "
                  f"n_sq={neural_squint} g_sq={geometric_squint} "
                  f"blink={blink_score:.2f} squint={is_squinting} calib={not self.is_calibrated()}")

        with self._lock:
            self.user_state.update({
                "face_detected": self._reported_face_detected,
                "squinting": is_squinting,
                "looking_down": is_looking_down,
                "looking_up": is_looking_up,
                "leaning_forward": is_leaning,
                "seated": self._reported_seated,
                "standing_above_frame": self._standing_above_frame,
                "is_calibrating": not self.is_calibrated()
            })
            return self.user_state.copy()

    def is_calibrated(self) -> bool:
        """Returns True if baseline pitch and eye gap have been calculated."""
        return (self._baseline_pitch > 0.001 and
                self._baseline_eye_gap > 0.001 and
                len(self._eye_calibration_buf) >= 15)

    def release(self):
        self.cap.release()
