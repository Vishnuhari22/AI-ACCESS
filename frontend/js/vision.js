/**
 * Vision Analyzer — MediaPipe Face Landmarker integration.
 * 
 * Uses the @mediapipe/tasks-vision API (optimized for browser).
 * Key design decisions to prevent browser freezing:
 * 1. We call detectForVideo() manually every 500ms (2fps)
 * 2. Model loads asynchronously on first camera enable
 * 3. Only 1 face tracked (reduces computation)
 * 4. Uses float16 model (smaller, faster)
 * 
 * Detects:
 * - Squinting: eye aperture ratio from landmarks
 * - Leaning forward: face width relative to baseline
 */

class VisionAnalyzer {
    constructor(onSignalUpdate) {
        this.onSignalUpdate = onSignalUpdate;
        this.videoEl = null;
        this.canvasEl = null;
        this.ctx = null;
        this.isRunning = false;
        this.stream = null;
        this.faceLandmarker = null;
        this.handLandmarker = null;
        this.poseLandmarker = null;
        this._handHistory = [];
        this._intervalId = null;
        this._loaded = false;

        // Calibration & baselines
        this._baselineFaceWidth = null;
        this._baselineFaceY = null;
        this._faceWidthCalibrationBuf = [];
        this._faceWidthHistory = [];
        this._baselineEar = null;
        this._earCalibrationBuf = [];
        this._earHistory = [];
        this._baselinePitch = null;
        this._pitchHistory = [];
        this._baselinePoseDepthGap = null;
        this._poseDepthCalibrationBuf = [];
        this._wristHistory = [];
        this._frameCount = 0;

        // Temporal smoothing & persistence
        this._facePresenceHistory = [];
        this._consecutiveFaceDetections = 0;
        this._leanCandidateCount = 0;
        this._squintCandidateCount = 0;

        this.signals = {
            squinting: false,
            squint_score: 0.0,
            squint_confidence: 0.0,
            looking_down: false,
            gaze_direction: "center",
            leaning_forward: false,
            lean_score: 0.0,
            lean_confidence: 0.0,
            face_detected: false,
            face_confidence: 0.0,
            eye_openness: 1.0,
            ear: 0.0,
            proximity: 1.0,
            hand_tremor: 0.0,
            tremor_confidence: 0.0,
            hand_detected: false,
            hand_confidence: 0.0,
            wheelchair_detected: false,
            bystander_present: false,
            estimated_age: "adult",
        };
    }

    async start(videoElementId, canvasElementId) {
        this.videoEl = document.getElementById(videoElementId);
        this.canvasEl = document.getElementById(canvasElementId);
        if (!this.videoEl || !this.canvasEl) {
            console.error('[Vision] Video or canvas element not found');
            return false;
        }

        this.ctx = this.canvasEl.getContext('2d');
        this._drawStatus('Starting camera...');

        try {
            // Step 1: Start webcam FIRST (so user sees their face quickly)
            console.log('[Vision] Requesting camera access...');
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: { width: 320, height: 240, facingMode: 'user' }
            });
            console.log('[Vision] Camera access granted');
            this.videoEl.srcObject = this.stream;
            await this.videoEl.play();
            console.log('[Vision] Video playing');

            this.isRunning = true;
            this._baselineFaceWidth = null;
            this._faceWidthCalibrationBuf = [];
            this._faceWidthHistory = [];
            this._baselineEar = null;
            this._baselinePitch = null;
            this._earHistory = [];
            this._earCalibrationBuf = [];
            this._pitchHistory = [];
            this._baselinePoseDepthGap = null;
            this._poseDepthCalibrationBuf = [];
            this._wristHistory = [];
            this._facePresenceHistory = [];
            this._consecutiveFaceDetections = 0;
            this._leanCandidateCount = 0;
            this._squintCandidateCount = 0;
            this._frameCount = 0;

            // Step 2: Start showing the video feed immediately (80ms ~ 12.5 FPS for responsive detection & tremor sampling)
            this._intervalId = setInterval(() => this._processFrame(), 80);

            // Step 3: Load MediaPipe model in background (non-blocking)
            this._drawStatus('Loading AI model...');
            this._loadMediaPipe();

            return true;

        } catch (err) {
            console.error('[Vision] Camera start failed:', err.name, err.message);
            this._drawStatus('Camera access denied. Allow in browser.');
            return false;
        }
    }

    stop() {
        this.isRunning = false;

        if (this._intervalId) {
            clearInterval(this._intervalId);
            this._intervalId = null;
        }

        if (this.stream) {
            this.stream.getTracks().forEach(t => t.stop());
            this.stream = null;
        }

        if (this.videoEl) {
            this.videoEl.srcObject = null;
        }

        // Clear camera-derived observations so disabling the camera cannot
        // leave stale accessibility state in the backend.
        this._clearPerceptionSignals();
        this._emitSignals();
    }

    _clearPerceptionSignals() {
        this.signals.squinting = false;
        this.signals.squint_score = 0.0;
        this.signals.squint_confidence = 0.0;
        this.signals.looking_down = false;
        this.signals.gaze_direction = "center";
        this.signals.leaning_forward = false;
        this.signals.lean_score = 0.0;
        this.signals.lean_confidence = 0.0;
        this.signals.face_detected = false;
        this.signals.face_confidence = 0.0;
        this.signals.eye_openness = 1.0;
        this.signals.ear = 0.0;
        this.signals.proximity = 1.0;
        this.signals.hand_tremor = 0.0;
        this.signals.tremor_confidence = 0.0;
        this.signals.hand_detected = false;
        this.signals.hand_confidence = 0.0;
        this.signals.wheelchair_detected = false;
        this.signals.bystander_present = false;
        this.signals.estimated_age = "adult";

        this._wristHistory = [];
        this._facePresenceHistory = [];
        this._consecutiveFaceDetections = 0;
        this._leanCandidateCount = 0;
        this._squintCandidateCount = 0;
    }

    async _loadMediaPipe() {
        try {
            // Dynamically import MediaPipe Tasks Vision module
            const mod = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/+esm');
            console.log('[Vision] MediaPipe module imported');

            const {FaceLandmarker, HandLandmarker, PoseLandmarker, FilesetResolver} = mod;

            // Initialize WASM fileset resolver
            const filesetResolver = await FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm');

            // Face Landmarker (2 faces: 1 primary + 1 for bystander detection)
            this.faceLandmarker = await FaceLandmarker.createFromOptions(filesetResolver, {
                baseOptions: {
                    modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
                    delegate: 'GPU'
                },
                runningMode: 'VIDEO',
                numFaces: 2,
                minFaceDetectionConfidence: 0.5,
                minTrackingConfidence: 0.5,
                outputFaceBlendshapes: false,
                outputFacialTransformationMatrixes: false,
            });

            // Hand Landmarker (single hand for tremor detection)
            this.handLandmarker = await HandLandmarker.createFromOptions(filesetResolver, {
                baseOptions: {
                    modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
                    delegate: 'GPU'
                },
                runningMode: 'VIDEO',
                numHands: 1,
                minHandDetectionConfidence: 0.5,
                minTrackingConfidence: 0.5,
            });

            // Pose Landmarker (for wheelchair detection)
            this.poseLandmarker = await PoseLandmarker.createFromOptions(filesetResolver, {
                baseOptions: {
                    modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
                    delegate: 'GPU'
                },
                runningMode: 'VIDEO',
                minPoseDetectionConfidence: 0.5,
                minTrackingConfidence: 0.5,
            });

            this._loaded = true;
            console.log('[Vision] ✅ MediaPipe models loaded');
        } catch (err) {
            console.error('[Vision] MediaPipe load failed:', err);
            console.log('[Vision] Falling back to video-only mode');
            // Models stay null; _processFrame will just show the raw video
        }
    }

    _processFrame() {
        if (!this.isRunning || !this.videoEl || this.videoEl.readyState < 2) return;

        const W = 320, H = 240;
        this.canvasEl.width = W;
        this.canvasEl.height = H;

        // Draw mirrored video
        this.ctx.save();
        this.ctx.translate(W, 0);
        this.ctx.scale(-1, 1);
        this.ctx.drawImage(this.videoEl, 0, 0, W, H);
        this.ctx.restore();

        // If MediaPipe isn't loaded yet, show loading overlay
        if (!this.faceLandmarker) {
            this.ctx.fillStyle = 'rgba(0,0,0,0.5)';
            this.ctx.fillRect(0, H - 28, W, 28);
            this.ctx.fillStyle = '#f59e0b';
            this.ctx.font = '12px Arial';
            this.ctx.fillText('⏳ Loading face AI model...', 8, H - 9);
            this.signals.face_detected = true; // Camera is working at least
            this._emitSignals();
            return;
        }

        // Run MediaPipe detections (Face, Hands, Pose)
        // Guard: models may be null if CDN load failed — run only what loaded
        let faceResults, handResults = null, poseResults = null;
        try {
            faceResults = this.faceLandmarker.detectForVideo(this.videoEl, performance.now());
            if (this.handLandmarker) {
                handResults = this.handLandmarker.detectForVideo(this.videoEl, performance.now());
            }
            if (this.poseLandmarker) {
                poseResults = this.poseLandmarker.detectForVideo(this.videoEl, performance.now());
            }
        } catch (e) {
            console.warn('[Vision] Detection error:', e);
            return;
        }

        // ---------- Face Detection with 2-Second Smoothing ----------
        const hasRawFace = Boolean(faceResults && faceResults.faceLandmarks && faceResults.faceLandmarks.length > 0);
        const nowSec = performance.now() / 1000;

        this._facePresenceHistory.push({ t: nowSec, detected: hasRawFace });
        // Maintain sliding 2.0-second window
        while (this._facePresenceHistory.length > 0 && (nowSec - this._facePresenceHistory[0].t) > 2.0) {
            this._facePresenceHistory.shift();
        }

        if (hasRawFace) {
            this._consecutiveFaceDetections++;

            // Activate quickly, but confidence increases with persistence.
            if (this._consecutiveFaceDetections >= 2) {
                this.signals.face_detected = true;
            }

            this.signals.face_confidence = Math.min(
                1.0,
                this._consecutiveFaceDetections / 4
            );
        } else {
            this._consecutiveFaceDetections = 0;

            // A single missed frame should not cause UI flicker.
            const recentPositive =
                this._facePresenceHistory.some(h => h.detected);

            if (!recentPositive) {
                this._clearPerceptionSignals();
            } else {
                this.signals.face_confidence *= 0.85;
                this.signals.squint_confidence *= 0.85;
                this.signals.lean_confidence *= 0.85;
                this.signals.tremor_confidence *= 0.85;
                this.signals.hand_tremor *= 0.70;

                if (this.signals.hand_tremor < 0.04) {
                    this.signals.hand_tremor = 0.0;
                }
            }
        }

        if (!hasRawFace) {
            // No landmarks in this raw frame. Keep the smoothed state rather
            // than reacting to a single detector miss.
            this._drawOverlay(W, H);
            this._frameCount++;
            this._emitSignals();
            return;
        }

        // Use first face for primary signals
        const landmarks = faceResults.faceLandmarks[0];
        this.signals.face_detected = true;
        this.signals.face_confidence = Math.min(
            1.0,
            this._consecutiveFaceDetections / 4
        );
        // Bystander detection: more than one face detected
        this.signals.bystander_present = (faceResults.faceLandmarks.length > 1);

        // ---------- Hand Tremor Detection ----------
        // Tremor is treated as an oscillatory signal, not simply "hand
        // movement". A longer rolling window improves separation between
        // repetitive involuntary motion and ordinary reaching/swiping.
        const hands = handResults
            ? (handResults.landmarks || handResults.handLandmarks)
            : null;

        if (hands && hands.length > 0) {
            this.signals.hand_detected = true;

            const hand = hands[0];
            const wrist = hand[0];

            this._wristHistory.push({
                x: wrist.x,
                y: wrist.y,
                t: performance.now() / 1000
            });

            // About 2.5 seconds at the current processing rate.
            if (this._wristHistory.length > 32) {
                this._wristHistory.shift();
            }

            this.signals.hand_confidence = Math.min(
                1.0,
                this._wristHistory.length / 18
            );

            if (this._wristHistory.length >= 24) {
                const hist = this._wristHistory;
                const n = hist.length;
                const dt = hist[n - 1].t - hist[0].t;

                if (dt > 1.2) {
                    const tMean = hist.reduce((s, p) => s + p.t, 0) / n;
                    const xMean = hist.reduce((s, p) => s + p.x, 0) / n;
                    const yMean = hist.reduce((s, p) => s + p.y, 0) / n;
                    let denom = 0, xNum = 0, yNum = 0;
                    for (const p of hist) {
                        const dtp = p.t - tMean;
                        denom += dtp * dtp;
                        xNum += dtp * (p.x - xMean);
                        yNum += dtp * (p.y - yMean);
                    }
                    const slopeX = denom > 1e-9 ? xNum / denom : 0;
                    const slopeY = denom > 1e-9 ? yNum / denom : 0;
                    const residuals = hist.map(p => {
                        const dtp = p.t - tMean;
                        return { x: (p.x - xMean) - slopeX * dtp, y: (p.y - yMean) - slopeY * dtp, t: p.t };
                    });

                    const rms = Math.sqrt(residuals.reduce((sum, p) => sum + p.x * p.x + p.y * p.y, 0) / n);
                    const reversalTimes = [];
                    let prevDx = 0, prevDy = 0;
                    const MIN_DELTA = 0.0015;
                    for (let i = 1; i < residuals.length; i++) {
                        const dx = residuals[i].x - residuals[i - 1].x;
                        const dy = residuals[i].y - residuals[i - 1].y;
                        if (Math.abs(dx) > MIN_DELTA) {
                            if (prevDx !== 0 && dx * prevDx < 0) reversalTimes.push(residuals[i].t);
                            prevDx = dx;
                        }
                        if (Math.abs(dy) > MIN_DELTA) {
                            if (prevDy !== 0 && dy * prevDy < 0) reversalTimes.push(residuals[i].t);
                            prevDy = dy;
                        }
                    }
                    reversalTimes.sort((a, b) => a - b);
                    const intervals = [];
                    for (let i = 1; i < reversalTimes.length; i++) {
                        const gap = reversalTimes[i] - reversalTimes[i - 1];
                        if (gap >= 0.05 && gap <= 0.6) intervals.push(gap);
                    }
                    let medianInterval = 0, intervalCV = 1.0;
                    if (intervals.length >= 4) {
                        const sorted = [...intervals].sort((a, b) => a - b);
                        medianInterval = sorted[Math.floor(sorted.length / 2)];
                        const meanGap = intervals.reduce((a, b) => a + b, 0) / intervals.length;
                        const variance = intervals.reduce((sum, x) => sum + (x - meanGap) ** 2, 0) / intervals.length;
                        intervalCV = meanGap > 1e-6 ? Math.sqrt(variance) / meanGap : 1.0;
                    }
                    const estimatedFrequency = medianInterval > 0 ? 1 / (2 * medianInterval) : 0;
                    const totalPath = hist.reduce((sum, p, i) => i === 0 ? 0 : sum + Math.hypot(p.x - hist[i - 1].x, p.y - hist[i - 1].y), 0);
                    const netDisp = Math.hypot(hist[n - 1].x - hist[0].x, hist[n - 1].y - hist[0].y);
                    const tortuosity = totalPath / (netDisp + 1e-4);
                    const speed = totalPath / dt;
                    const amplitudeScore = Math.min(1.0, Math.max(0.0, (rms - 0.0020) / 0.0060));
                    const frequencyScore = Math.min(1.0, Math.max(0.0, (estimatedFrequency - 2.5) / 3.5));
                    const periodicityScore = intervals.length >= 4 ? Math.min(1.0, Math.max(0.0, 1.0 - intervalCV / 0.55)) : 0.0;
                    const voluntaryMovement = (netDisp > 0.10 && speed > 0.16) || (tortuosity < 1.45 && reversalTimes.length / dt < 4.0);
                    const tremorCandidate = !voluntaryMovement && reversalTimes.length >= 6 && intervals.length >= 4 && estimatedFrequency >= 2.5 && estimatedFrequency <= 7.5 && intervalCV <= 0.55 && rms >= 0.0020;

                    if (tremorCandidate) {
                        const rawScore = Math.min(1.0, 0.35 * amplitudeScore + 0.25 * frequencyScore + 0.40 * periodicityScore);
                        const previous = this.signals.hand_tremor || 0;
                        this.signals.hand_tremor = previous * 0.78 + rawScore * 0.22;
                        this.signals.tremor_confidence = Math.min(1.0, (hist.length / 32) * (0.45 + 0.55 * periodicityScore));
                    } else {
                        this.signals.hand_tremor = (this.signals.hand_tremor || 0) * 0.68;
                        this.signals.tremor_confidence *= 0.72;
                        if (this.signals.hand_tremor < 0.04) this.signals.hand_tremor = 0.0;
                    }
                }
            }
        } else {
            this.signals.hand_detected = false;
            this.signals.hand_confidence *= 0.65;
            this.signals.tremor_confidence *= 0.65;

            this.signals.hand_tremor =
                (this.signals.hand_tremor || 0) * 0.60;

            if (this.signals.hand_tremor < 0.04) {
                this.signals.hand_tremor = 0.0;
            }

            // Keep a short history through a momentary occlusion, but do
            // not retain the entire old trajectory.
            if (this._wristHistory.length > 8) {
                this._wristHistory =
                    this._wristHistory.slice(-8);
            }
        }

        // ---------- Seated/Wheelchair Detection ----------
        // Strategy: Use face vertical height relative to frame as primary signal.
        // Seated at desk → face is closer to webcam → face takes up MORE vertical space.
        // Standing/walking → further from webcam → face takes up LESS vertical space.
        // Also: nose Y-position tends to be in the middle/upper area when seated (laptop on desk).
        const faceY = landmarks[1].y; // nose Y in normalized coords (0=top, 1=bottom)
        const faceH = Math.abs(landmarks[10].y - landmarks[152].y); // forehead to chin height

        // Pose model takes priority when shoulder/hip landmarks are available
        const poses = poseResults ? (poseResults.landmarks || poseResults.poseLandmarks) : null;
        if (poses && poses.length > 0) {
            const pose = poses[0];
            const leftShoulder = pose[11], rightShoulder = pose[12];
            const leftHip = pose[23], rightHip = pose[24];
            if (leftHip && rightHip && leftShoulder && rightShoulder) {
                const shoulderY = (leftShoulder.y + rightShoulder.y) / 2;
                const hipY = (leftHip.y + rightHip.y) / 2;
                const torsoLen = Math.abs(hipY - shoulderY);
                // Short visible torso = seated (hips hidden behind desk)
                // Landmarks always exist but visibility/confidence matters
                this.signals.wheelchair_detected = (torsoLen < 0.15);
            } else {
                // Shoulder/hip landmarks present but null — use face heuristic
                this.signals.wheelchair_detected = (faceH > 0.2 && faceY > 0.35);
            }
        } else {
            // No pose model: face fills large vertical portion + mid-to-lower frame = seated
            this.signals.wheelchair_detected = (faceH > 0.2 && faceY > 0.35);
        }

        // ---------- Age estimation ----------
        // Uses face proportions as heuristic proxy:
        //   - Face width relative to frame (normalized 0–1)
        //   - Face aspect ratio (height/width) — children have rounder faces
        // Calibrated from live testing: typical adult face width ~0.15–0.25 at laptop distance
        const faceWidth = Math.abs(landmarks[234].x - landmarks[454].x);
        const faceAspect = faceH / Math.max(faceWidth, 0.001); // height / width

        // Classification logic:
        // Children: small face + round proportions (aspect < 1.2)
        // Elderly: large face (close to screen) OR high aspect ratio (longer face)
        // Adult: everything else
        if (faceWidth < 0.12 && faceAspect < 1.2) {
            this.signals.estimated_age = "child";
        } else if (faceWidth > 0.28 || faceAspect > 1.5) {
            this.signals.estimated_age = "elderly";
        } else {
            this.signals.estimated_age = "adult";
        }

        // ─── Head Pitch & Downward Gaze Analysis ───
        const noseTip = landmarks[1];
        const noseBridge =
            landmarks[6] || landmarks[168] || landmarks[197];

        const pitchDelta =
            (noseTip && noseBridge)
                ? (noseTip.y - noseBridge.y)
                : 0;

        const normPitch =
            faceH > 0.01 ? pitchDelta / faceH : 0;

        this._pitchHistory.push(normPitch);

        if (this._pitchHistory.length > 10) {
            this._pitchHistory.shift();
        }

        const smoothedPitch =
            this._pitchHistory.reduce((a, b) => a + b, 0) /
            this._pitchHistory.length;

        if (
            this._baselinePitch === null &&
            this._pitchHistory.length >= 6
        ) {
            this._baselinePitch = smoothedPitch;
        }

        // Vertical gaze tracking using iris landmarks.
        let leftGazeY = 0.5;
        let rightGazeY = 0.5;

        if (landmarks[468]) {
            const leftLidH =
                landmarks[145].y - landmarks[159].y;

            if (Math.abs(leftLidH) > 0.001) {
                leftGazeY =
                    (landmarks[468].y - landmarks[159].y) /
                    leftLidH;
            }
        }

        if (landmarks[473]) {
            const rightLidH =
                landmarks[374].y - landmarks[386].y;

            if (Math.abs(rightLidH) > 0.001) {
                rightGazeY =
                    (landmarks[473].y - landmarks[386].y) /
                    rightLidH;
            }
        }

        const avgGazeY =
            (leftGazeY + rightGazeY) / 2;

        const pitchLookingDown =
            this._baselinePitch !== null &&
            smoothedPitch > this._baselinePitch + 0.07;

        const isLookingDown =
            avgGazeY > 0.62 || pitchLookingDown;

        this.signals.looking_down = isLookingDown;
        this.signals.gaze_direction =
            isLookingDown ? "down" : "center";

        // ─── Scale-Invariant Eye Aspect Ratio (EAR) ───
        const leftV = Math.hypot(
            landmarks[159].x - landmarks[145].x,
            landmarks[159].y - landmarks[145].y
        );

        const leftH = Math.hypot(
            landmarks[33].x - landmarks[133].x,
            landmarks[33].y - landmarks[133].y
        );

        const leftEar =
            leftH > 0.001 ? leftV / leftH : 0.0;

        const rightV = Math.hypot(
            landmarks[386].x - landmarks[374].x,
            landmarks[386].y - landmarks[374].y
        );

        const rightH = Math.hypot(
            landmarks[263].x - landmarks[362].x,
            landmarks[263].y - landmarks[362].y
        );

        const rightEar =
            rightH > 0.001 ? rightV / rightH : 0.0;

        const currentEar =
            (leftEar + rightEar) / 2;

        const eyeAsymmetry =
            Math.abs(leftEar - rightEar) /
            Math.max(currentEar, 0.001);

        // Initial calibration: only use clearly open, forward-looking,
        // reasonably symmetric eyes.
        if (
            this._baselineEar === null &&
            !isLookingDown &&
            currentEar > 0.15 &&
            eyeAsymmetry < 0.25
        ) {
            this._earCalibrationBuf.push(currentEar);

            if (this._earCalibrationBuf.length >= 14) {
                const sorted =
                    [...this._earCalibrationBuf]
                        .sort((a, b) => a - b);

                this._baselineEar =
                    sorted[Math.floor(sorted.length / 2)];

                console.log(
                    '[Vision] Baseline EAR calibrated:',
                    this._baselineEar.toFixed(3)
                );
            }
        }

        this._earHistory.push(currentEar);

        if (this._earHistory.length > 8) {
            this._earHistory.shift();
        }

        const smoothedEar =
            this._earHistory.reduce((a, b) => a + b, 0) /
            this._earHistory.length;

        this.signals.ear = smoothedEar;

        const refEar =
            this._baselineEar || 0.28;

        const earRatio =
            smoothedEar / refEar;

        this.signals.eye_openness =
            Math.min(1.0, Math.max(0.0, earRatio));

        // Slowly adapt the baseline only when the eyes are clearly open.
        // This prevents a long-term change in camera/expression from
        // permanently biasing the detector, while avoiding "learning"
        // a squint as the new normal.
        if (
            this._baselineEar !== null &&
            !isLookingDown &&
            earRatio > 0.92 &&
            eyeAsymmetry < 0.18
        ) {
            this._baselineEar =
                this._baselineEar * 0.985 +
                smoothedEar * 0.015;
        }

        // Squint = sustained partial closure of BOTH eyes.
        // Deep, short closures are treated as blinks rather than squints.
        const isBlinkCandidate =
            earRatio < 0.25;

        const bilateralSquint =
            earRatio < 0.78 &&
            earRatio >= 0.25 &&
            eyeAsymmetry < 0.30;

        const isSquintCandidate =
            bilateralSquint &&
            !isLookingDown &&
            !isBlinkCandidate;

        if (isSquintCandidate) {
            this._squintCandidateCount++;
        } else {
            this._squintCandidateCount =
                Math.max(
                    0,
                    this._squintCandidateCount - 2
                );
        }

        const squintPersistence =
            Math.min(
                1.0,
                this._squintCandidateCount / 7
            );

        const closureScore =
            Math.min(
                1.0,
                Math.max(
                    0.0,
                    (0.92 - earRatio) / 0.25
                )
            );

        const symmetryScore =
            Math.min(
                1.0,
                Math.max(
                    0.0,
                    1.0 - eyeAsymmetry / 0.30
                )
            );

        this.signals.squint_score =
            closureScore * symmetryScore;

        this.signals.squinting =
            this._squintCandidateCount >= 7;

        this.signals.squint_confidence =
            this.signals.squinting
                ? Math.min(
                    1.0,
                    0.55 * squintPersistence +
                    0.45 * symmetryScore
                )
                : Math.min(
                    1.0,
                    0.35 * squintPersistence
                );

        // ─── Forward Lean / Proximity Detection ───
        // Face scale is a strong cue for movement toward the camera.
        // Pose depth, when available, provides a second cue.
        const leanFaceWidth =
            Math.abs(
                landmarks[234].x -
                landmarks[454].x
            );

        this._faceWidthHistory.push(leanFaceWidth);

        if (this._faceWidthHistory.length > 12) {
            this._faceWidthHistory.shift();
        }

        const smoothedWidth =
            this._faceWidthHistory.reduce((a, b) => a + b, 0) /
            this._faceWidthHistory.length;

        if (
            this._baselineFaceWidth === null &&
            !isLookingDown &&
            leanFaceWidth > 0.10 &&
            leanFaceWidth < 0.38
        ) {
            this._faceWidthCalibrationBuf.push(
                smoothedWidth
            );

            if (this._faceWidthCalibrationBuf.length >= 20) {
                const sortedBuf =
                    [...this._faceWidthCalibrationBuf]
                        .sort((a, b) => a - b);

                this._baselineFaceWidth =
                    sortedBuf[
                        Math.floor(
                            sortedBuf.length / 2
                        )
                    ];

                console.log(
                    '[Vision] Baseline face width calibrated:',
                    this._baselineFaceWidth.toFixed(4)
                );
            }
        }

        if (this._baselineFaceWidth !== null) {
            const ratio =
                smoothedWidth /
                this._baselineFaceWidth;

            this.signals.proximity = ratio;

            const faceScaleScore =
                Math.min(
                    1.0,
                    Math.max(
                        0.0,
                        (ratio - 1.08) / 0.30
                    )
                );

            let depthScore = null;

            const poses = poseResults
                ? (
                    poseResults.landmarks ||
                    poseResults.poseLandmarks
                )
                : null;

            if (poses && poses.length > 0) {
                const pose = poses[0];
                const poseNose = pose[0];
                const leftShoulder = pose[11];
                const rightShoulder = pose[12];

                if (
                    poseNose &&
                    leftShoulder &&
                    rightShoulder
                ) {
                    const shoulderZ =
                        (
                            leftShoulder.z +
                            rightShoulder.z
                        ) / 2;

                    const depthGap =
                        shoulderZ - poseNose.z;

                    if (
                        this._baselinePoseDepthGap === null &&
                        !isLookingDown &&
                        Math.abs(depthGap) < 1.0
                    ) {
                        this._poseDepthCalibrationBuf.push(
                            depthGap
                        );

                        if (
                            this._poseDepthCalibrationBuf.length >= 12
                        ) {
                            const sortedDepth =
                                [...this._poseDepthCalibrationBuf]
                                    .sort((a, b) => a - b);

                            this._baselinePoseDepthGap =
                                sortedDepth[
                                    Math.floor(
                                        sortedDepth.length / 2
                                    )
                                ];
                        }
                    }

                    if (
                        this._baselinePoseDepthGap !== null
                    ) {
                        depthScore =
                            Math.min(
                                1.0,
                                Math.max(
                                    0.0,
                                    (
                                        depthGap -
                                        this._baselinePoseDepthGap -
                                        0.015
                                    ) / 0.10
                                )
                            );
                    }
                }
            }

            const combinedLeanScore =
                depthScore === null
                    ? faceScaleScore
                    : (
                        0.70 * faceScaleScore +
                        0.30 * depthScore
                    );

            this.signals.lean_score =
                combinedLeanScore;

            if (combinedLeanScore > 0.55) {
                this._leanCandidateCount++;
            } else if (combinedLeanScore < 0.35) {
                this._leanCandidateCount =
                    Math.max(
                        0,
                        this._leanCandidateCount - 2
                    );
            }

            this.signals.leaning_forward =
                this._leanCandidateCount >= 6;

            this.signals.lean_confidence =
                Math.min(
                    1.0,
                    0.55 * Math.min(
                        1.0,
                        this._leanCandidateCount / 8
                    ) +
                    0.45 * combinedLeanScore
                );

            if (!this.signals.leaning_forward) {
                this.signals.lean_confidence *= 0.7;
            }
        }

        // Draw landmarks and overlay
        this._drawLandmarks(landmarks, W, H);
        this._drawOverlay(W, H);

        this._frameCount++;
        this._emitSignals();
    }

    _drawLandmarks(landmarks, W, H) {
        const eyeColor = this.signals.squinting ? '#ef4444' : (this.signals.looking_down ? '#f59e0b' : '#10b981');
        const keyPoints = [
            // Eyelids
            { idx: 159, color: eyeColor },
            { idx: 145, color: eyeColor },
            { idx: 386, color: eyeColor },
            { idx: 374, color: eyeColor },
            // Eye corners
            { idx: 33, color: '#00e5ff' },
            { idx: 133, color: '#00e5ff' },
            { idx: 362, color: '#00e5ff' },
            { idx: 263, color: '#00e5ff' },
            // Iris centers (468, 473)
            { idx: 468, color: '#38bdf8' },
            { idx: 473, color: '#38bdf8' },
            // Nose and cheeks
            { idx: 1, color: '#3b82f6' },
            { idx: 234, color: this.signals.leaning_forward ? '#f59e0b' : '#3b82f6' },
            { idx: 454, color: this.signals.leaning_forward ? '#f59e0b' : '#3b82f6' },
        ];

        for (const pt of keyPoints) {
            const lm = landmarks[pt.idx];
            if (!lm) continue;
            const x = (1 - lm.x) * W;
            const y = lm.y * H;
            this.ctx.fillStyle = pt.color;
            this.ctx.beginPath();
            this.ctx.arc(x, y, (pt.idx === 468 || pt.idx === 473) ? 2.5 : 3, 0, Math.PI * 2);
            this.ctx.fill();
        }

        // Face outline
        const jawIndices = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, 10];
        this.ctx.strokeStyle = this.signals.leaning_forward ? '#f59e0b' : 'rgba(59, 130, 246, 0.5)';
        this.ctx.lineWidth = 1;
        this.ctx.beginPath();
        for (let i = 0; i < jawIndices.length; i++) {
            const lm = landmarks[jawIndices[i]];
            if (!lm) continue;
            const x = (1 - lm.x) * W;
            const y = lm.y * H;
            if (i === 0) this.ctx.moveTo(x, y);
            else this.ctx.lineTo(x, y);
        }
        this.ctx.stroke();

        // Proximity bar
        if (this._baselineFaceWidth) {
            const ratio = Math.min(this.signals.proximity, 2.0);
            const barMaxH = H - 35;
            const barH = (ratio / 2.0) * barMaxH;
            const barColor = ratio > 1.5 ? '#ef4444' : ratio > 1.25 ? '#f59e0b' : '#10b981';

            this.ctx.fillStyle = 'rgba(0,0,0,0.5)';
            this.ctx.fillRect(W - 20, 5, 15, barMaxH);
            this.ctx.fillStyle = barColor;
            this.ctx.fillRect(W - 20, 5 + barMaxH - barH, 15, barH);

            this.ctx.strokeStyle = '#f59e0b';
            this.ctx.setLineDash([3, 3]);
            const threshY = 5 + barMaxH - ((1.25 / 2.0) * barMaxH);
            this.ctx.beginPath();
            this.ctx.moveTo(W - 23, threshY);
            this.ctx.lineTo(W - 3, threshY);
            this.ctx.stroke();
            this.ctx.setLineDash([]);

            this.ctx.fillStyle = '#fff';
            this.ctx.font = '9px Arial';
            this.ctx.fillText(ratio.toFixed(1) + 'x', W - 20, barMaxH + 20);
        }
    }

    _drawOverlay(W, H) {
        this.ctx.fillStyle = 'rgba(0,0,0,0.65)';
        this.ctx.fillRect(0, H - 24, W - 25, 24);
        this.ctx.fillStyle = '#fff';
        this.ctx.font = '11px Arial, sans-serif';

        let text;
        if (!this.signals.face_detected) {
            text = '❌ No face — look at camera';
        } else if (!this._baselineFaceWidth || !this._baselineEar) {
            const count = Math.min(this._faceWidthCalibrationBuf.length, this._earCalibrationBuf.length);
            text = `📐 Calibrating... (${count}/20)`;
        } else {
            const parts = [];
            if (this.signals.squinting) {
                parts.push('👁️ SQUINTING');
            } else if (this.signals.looking_down) {
                parts.push('👁️ DOWN');
            } else {
                parts.push(`👁️ ${(this.signals.eye_openness * 100).toFixed(0)}%`);
            }

            if (this.signals.hand_detected) {
                const trPct = Math.round(this.signals.hand_tremor * 100);
                parts.push(`✋ ${trPct}%`);
            }

            if (this.signals.leaning_forward) parts.push('↗️ LEANING');
            else parts.push('✅ Normal');
            text = parts.join(' | ');
        }
        this.ctx.fillText(text, 6, H - 8);
    }

    _drawStatus(msg) {
        if (!this.canvasEl) return;
        const ctx = this.canvasEl.getContext('2d');
        this.canvasEl.width = 320;
        this.canvasEl.height = 240;
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, 320, 240);
        ctx.fillStyle = '#94a3b8';
        ctx.font = '13px Arial';
        ctx.textAlign = 'center';
        ctx.fillText(msg, 160, 125);
        ctx.textAlign = 'start';
    }

    _emitSignals() {
        if (this.onSignalUpdate) {
            this.onSignalUpdate({ ...this.signals });
        }
    }
}
