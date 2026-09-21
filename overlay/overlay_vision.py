import os
import threading
import time
import math
import urllib.request
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


class OverlayVision:
    def __init__(self):
        # Face model
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

        # Hand model
        hand_model_path = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")
        if not os.path.exists(hand_model_path):
            print("[Vision] Downloading hand_landmarker.task model...")
            urllib.request.urlretrieve(
                "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
                hand_model_path
            )
            print("[Vision] Download complete.")
        
        hand_base_options = python.BaseOptions(model_asset_path=hand_model_path)
        hand_options = vision.HandLandmarkerOptions(
            base_options=hand_base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.3,
            min_hand_presence_confidence=0.3,
            min_tracking_confidence=0.3
        )
        self.hand_detector = vision.HandLandmarker.create_from_options(hand_options)

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
            "hand_detected": False,
            "hand_tremor": 0.0,
            "squint_confidence": 0.0,
            "lean_confidence": 0.0,
            "tremor_confidence": 0.0,
            "face_confidence": 0.0,
            "hand_confidence": 0.0,
            "ear": 1.0,
            "eye_openness": 1.0
        }

        # Face detection smoothing (2-second sliding window)
        self._face_presence_history = []   # list of (timestamp, detected_bool)
        self._consecutive_detections = 0
        
        # Hand tremor tracking
        self._wrist_history = [] # list of (x, y, t)

        # Calibration & baselines
        self._baseline_face_width = 0.0
        self._face_width_history = []
        self._face_width_calibration_buf = []
        self._lean_candidate_count = 0

        self._baseline_pitch = 0.0         # baseline head pitch (looking straight)
        self._pitch_history = []           # rolling buffer for pitch smoothing

        self._baseline_ear = 0.0           # baseline scale-invariant EAR
        self._ear_history = []             # rolling buffer for EAR smoothing
        self._eye_calibration_buf = []     # buffer to collect initial EAR readings for baseline
        self._squint_candidate_count = 0
        self._debug_frame_count = 0        # for initial debug logging

    def get_latest_state(self) -> dict:
        """Captures one frame, runs landmark detection, and returns the updated state dict with 2-second smoothing."""
        now = time.time()
        success, image = self.cap.read()
        has_raw_face = False
        landmarks = None

        hand_detected = False
        if success:
            image = cv2.flip(image, 1)
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
            
            # 1. Face detection
            detection_result = self.detector.detect(mp_image)
            if detection_result and detection_result.face_landmarks:
                has_raw_face = True
                landmarks = detection_result.face_landmarks[0]

            # 2. Hand detection (always runs regardless of face presence)
            try:
                hand_result = self.hand_detector.detect(mp_image)
                if hand_result and hand_result.hand_landmarks:
                    hand_detected = True
                    hand = hand_result.hand_landmarks[0]
                    wrist = hand[0]
                    
                    self._wrist_history.append((wrist.x, wrist.y, now))
                    if len(self._wrist_history) > 32:
                        self._wrist_history.pop(0)
                        
                    if len(self._wrist_history) >= 24:
                        hist = self._wrist_history
                        n = len(hist)
                        dt = hist[-1][2] - hist[0][2]
                        if dt > 1.2:
                            t_mean = sum(p[2] for p in hist) / n
                            x_mean = sum(p[0] for p in hist) / n
                            y_mean = sum(p[1] for p in hist) / n
                            denom = sum((p[2] - t_mean) ** 2 for p in hist)
                            slope_x = sum((p[2] - t_mean) * (p[0] - x_mean) for p in hist) / denom if denom > 1e-9 else 0.0
                            slope_y = sum((p[2] - t_mean) * (p[1] - y_mean) for p in hist) / denom if denom > 1e-9 else 0.0
                            residuals = [((p[0] - x_mean) - slope_x * (p[2] - t_mean), (p[1] - y_mean) - slope_y * (p[2] - t_mean), p[2]) for p in hist]
                            rms = math.sqrt(sum(x * x + y * y for x, y, _ in residuals) / n)
                            reversal_times = []
                            prev_dx = prev_dy = 0.0
                            MIN_DELTA = 0.0015
                            for i in range(1, n):
                                dx = residuals[i][0] - residuals[i - 1][0]
                                dy = residuals[i][1] - residuals[i - 1][1]
                                if abs(dx) > MIN_DELTA:
                                    if prev_dx != 0.0 and dx * prev_dx < 0: reversal_times.append(residuals[i][2])
                                    prev_dx = dx
                                if abs(dy) > MIN_DELTA:
                                    if prev_dy != 0.0 and dy * prev_dy < 0: reversal_times.append(residuals[i][2])
                                    prev_dy = dy
                            reversal_times.sort()
                            intervals = [reversal_times[i] - reversal_times[i - 1] for i in range(1, len(reversal_times)) if 0.05 <= reversal_times[i] - reversal_times[i - 1] <= 0.6]
                            median_interval = 0.0
                            interval_cv = 1.0
                            if len(intervals) >= 4:
                                ordered = sorted(intervals)
                                median_interval = ordered[len(ordered) // 2]
                                mean_gap = sum(intervals) / len(intervals)
                                variance = sum((x - mean_gap) ** 2 for x in intervals) / len(intervals)
                                interval_cv = math.sqrt(variance) / mean_gap if mean_gap > 1e-6 else 1.0
                            estimated_frequency = 1.0 / (2.0 * median_interval) if median_interval > 0 else 0.0
                            total_path = sum(math.hypot(hist[i][0] - hist[i - 1][0], hist[i][1] - hist[i - 1][1]) for i in range(1, n))
                            net_disp = math.hypot(hist[-1][0] - hist[0][0], hist[-1][1] - hist[0][1])
                            tortuosity = total_path / (net_disp + 1e-4)
                            speed = total_path / dt
                            amplitude_score = min(1.0, max(0.0, (rms - 0.0020) / 0.0060))
                            frequency_score = min(1.0, max(0.0, (estimated_frequency - 2.5) / 3.5))
                            periodicity_score = min(1.0, max(0.0, 1.0 - interval_cv / 0.55)) if len(intervals) >= 4 else 0.0
                            is_voluntary = (
                                (net_disp > 0.14 and speed > 0.18)
                                or (tortuosity < 1.25 and len(reversal_times) / dt < 3.0)
                            )

                            tremor_candidate = (
                                not is_voluntary
                                and len(reversal_times) >= 5
                                and len(intervals) >= 3
                                and 2.0 <= estimated_frequency <= 8.0
                                and interval_cv <= 0.70
                                and rms >= 0.0015
                            )
                            if tremor_candidate:
                                raw_score = min(
                                    1.0,
                                    0.40 * amplitude_score
                                    + 0.25 * frequency_score
                                    + 0.35 * periodicity_score
                                )
                                prev = self.user_state.get("hand_tremor", 0.0)
                                self.user_state["hand_tremor"] = prev * 0.78 + raw_score * 0.22
                                self.user_state["tremor_confidence"] = min(1.0, (len(hist) / 32.0) * (0.45 + 0.55 * periodicity_score))
                            else:
                                prev = self.user_state.get("hand_tremor", 0.0)
                                self.user_state["hand_tremor"] = prev * 0.68
                                self.user_state["tremor_confidence"] *= 0.72
                                if self.user_state["hand_tremor"] < 0.04: self.user_state["hand_tremor"] = 0.0
            except Exception as e:
                if self._debug_frame_count < 3:
                    print(f"[Vision] Hand detection error: {e}")

        if not hand_detected:
            self._wrist_history.clear()
            prev = self.user_state.get("hand_tremor", 0.0)
            self.user_state["hand_tremor"] = prev * 0.6
            if self.user_state["hand_tremor"] < 0.04:
                self.user_state["hand_tremor"] = 0.0

        # Update sliding 2.0-second presence window
        self._face_presence_history.append((now, has_raw_face))
        self._face_presence_history = [entry for entry in self._face_presence_history if (now - entry[0]) <= 2.0]

        if has_raw_face:
            self._consecutive_detections += 1
            if self._consecutive_detections >= 2:
                face_detected = True
            else:
                face_detected = self.user_state.get("face_detected", True)
        else:
            self._consecutive_detections = 0
            # Only transition to "No Face" if no face was detected across the entire 2.0-second window
            recent_positive = any(det for t, det in self._face_presence_history)
            if not recent_positive:
                face_detected = False
            else:
                face_detected = self.user_state.get("face_detected", True)

        if not has_raw_face:
            with self._lock:
                if not face_detected:
                    self.user_state.update({
                        "face_detected": False,
                        "squinting": False,
                        "leaning_forward": False,
                        "looking_down": False,
                        "hand_detected": hand_detected,
                        "squint_confidence": 0.0,
                        "lean_confidence": 0.0,
                        "tremor_confidence": 0.0,
                        "face_confidence": 0.0,
                        "hand_confidence": 1.0 if hand_detected else 0.0,
                    })
                    self._squint_candidate_count = 0
                    self._lean_candidate_count = 0
                else:
                    self.user_state["face_detected"] = True
                    self.user_state["hand_detected"] = hand_detected
                return self.user_state.copy()

        # --- Face geometry ---
        left_cheek  = landmarks[234]
        right_cheek = landmarks[454]
        chin        = landmarks[152]
        forehead    = landmarks[10]
        face_width  = abs(left_cheek.x - right_cheek.x)
        face_height = abs(forehead.y  - chin.y)

        # Smooth face width over rolling window (3 frames ~ 1.0 second at 0.35s polling)
        self._face_width_history.append(face_width)
        if len(self._face_width_history) > 3:
            self._face_width_history.pop(0)
        smoothed_width = sum(self._face_width_history) / len(self._face_width_history)

        # 1. Head pitch estimation (nose tip #1 vs nose bridge #6)
        nose_tip    = landmarks[1]
        nose_bridge = landmarks[6]
        pitch_delta = nose_tip.y - nose_bridge.y          # always positive
        norm_pitch  = pitch_delta / face_height if face_height > 0.01 else 0

        # Smooth pitch over 4 frames to avoid flicker
        self._pitch_history.append(norm_pitch)
        if len(self._pitch_history) > 4:
            self._pitch_history.pop(0)
        smoothed_pitch = sum(self._pitch_history) / len(self._pitch_history)

        # Calibrate baseline pitch from the first stable readings
        if self._baseline_pitch < 0.01 and len(self._pitch_history) >= 4:
            self._baseline_pitch = smoothed_pitch
            print(f"[Vision] Baseline pitch calibrated: {self._baseline_pitch:.4f}")

        # 2. Iris Vertical Gaze Tracking (landmarks 468 left, 473 right)
        left_gaze_y = 0.5
        right_gaze_y = 0.5
        if len(landmarks) > 468:
            lid_h = landmarks[145].y - landmarks[159].y
            if abs(lid_h) > 0.001:
                left_gaze_y = (landmarks[468].y - landmarks[159].y) / lid_h

        if len(landmarks) > 473:
            lid_h = landmarks[374].y - landmarks[386].y
            if abs(lid_h) > 0.001:
                right_gaze_y = (landmarks[473].y - landmarks[386].y) / lid_h

        avg_gaze_y = (left_gaze_y + right_gaze_y) / 2

        # Flag looking-down if iris is depressed towards bottom lid (>0.62) OR head is pitched down
        is_looking_down = (avg_gaze_y > 0.62) or (
            self._baseline_pitch > 0.01 and smoothed_pitch > self._baseline_pitch + 0.07
        )

        # 3. Robust Face Width Baseline Calibration (median of 6 stable forward-facing samples ~ 2 seconds)
        if self._baseline_face_width < 0.01 and not is_looking_down and (0.10 < face_width < 0.40):
            self._face_width_calibration_buf.append(smoothed_width)
            if len(self._face_width_calibration_buf) >= 6:
                sorted_widths = sorted(self._face_width_calibration_buf)
                self._baseline_face_width = sorted_widths[len(sorted_widths) // 2]
                print(f"[Vision] Baseline face width calibrated (median): {self._baseline_face_width:.4f}")

        # Leaning-forward detection with hysteresis
        if self._baseline_face_width > 0.01:
            ratio = smoothed_width / self._baseline_face_width
            if ratio > 1.28:
                self._lean_candidate_count += 1
            elif ratio < 1.18:
                self._lean_candidate_count = max(0, self._lean_candidate_count - 1)

            is_leaning = (self._lean_candidate_count >= 1 and ratio > 1.28)
        else:
            is_leaning = False

        # 4. Scale-Invariant Eye Aspect Ratio (EAR)
        # Left eye: 159 (upper), 145 (lower), 33 (outer), 133 (inner)
        left_v = math.hypot(landmarks[159].x - landmarks[145].x, landmarks[159].y - landmarks[145].y)
        left_h = math.hypot(landmarks[33].x - landmarks[133].x, landmarks[33].y - landmarks[133].y)
        left_ear = left_v / left_h if left_h > 0.001 else 0.0

        # Right eye: 386 (upper), 374 (lower), 263 (outer), 362 (inner)
        right_v = math.hypot(landmarks[386].x - landmarks[374].x, landmarks[386].y - landmarks[374].y)
        right_h = math.hypot(landmarks[263].x - landmarks[362].x, landmarks[263].y - landmarks[362].y)
        right_ear = right_v / right_h if right_h > 0.001 else 0.0

        current_ear = (left_ear + right_ear) / 2

        # Rolling 3-frame average (~1.0s) for responsive yet stable tracking
        self._ear_history.append(current_ear)
        if len(self._ear_history) > 3:
            self._ear_history.pop(0)
        smoothed_ear = sum(self._ear_history) / len(self._ear_history)

        # Calibrate baseline EAR from stable forward-looking readings (not looking down, ~2.0s)
        if self._baseline_ear < 0.001 and not is_looking_down and current_ear > 0.15:
            self._eye_calibration_buf.append(current_ear)
            if len(self._eye_calibration_buf) >= 6:
                sorted_buf = sorted(self._eye_calibration_buf)
                self._baseline_ear = sorted_buf[len(sorted_buf) // 2]
                print(f"[Vision] Baseline EAR calibrated: {self._baseline_ear:.4f}")

        # Determine squinting:
        # Natural squint threshold: < 0.77 of baseline (comfortable, no forced squeezing)
        # Gated on NOT looking down, not a blink
        if self._baseline_ear > 0.001:
            squint_ratio = smoothed_ear / self._baseline_ear
            is_squint_candidate = (0.25 <= squint_ratio < 0.77) and not is_looking_down
            is_squinting = is_squint_candidate
            eye_openness = min(smoothed_ear / self._baseline_ear, 1.0)
        else:
            squint_ratio = 1.0
            is_squinting = False
            eye_openness = 1.0

        self._debug_frame_count += 1

        with self._lock:
            self.user_state.update({
                "face_detected": True,
                "squinting": is_squinting,
                "looking_down": is_looking_down,
                "leaning_forward": is_leaning,
                "ear": smoothed_ear,
                "eye_openness": eye_openness,
                "gaze_y": avg_gaze_y,
                "hand_detected": hand_detected,
                "squint_confidence": 1.0 if is_squinting else 0.0,
                "lean_confidence": 1.0 if is_leaning else 0.0,
                "tremor_confidence": (
                    1.0 if hand_detected and self.user_state.get("hand_tremor", 0.0) > 0.35 else 0.0
                ),
                "face_confidence": min(1.0, self._consecutive_detections / 4.0),
                "hand_confidence": 1.0 if hand_detected else 0.0,
            })
            return self.user_state.copy()

    def release(self):
        self.cap.release()


