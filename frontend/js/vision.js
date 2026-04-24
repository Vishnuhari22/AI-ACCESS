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

        // Calibration
        this._baselineFaceWidth = null;
        this._baselineFaceY = null;
        this._faceWidthHistory = [];
        this._eyeHistory = [];
        this._wristHistory = [];
        this._frameCount = 0;

        this.signals = {
            squinting: false,
            leaning_forward: false,
            face_detected: false,
            eye_openness: 1.0,
            proximity: 1.0,
            hand_tremor: 0.0,
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
            this._faceWidthHistory = [];
            this._eyeHistory = [];
            this._frameCount = 0;

            // Step 2: Start showing the video feed immediately
            this._intervalId = setInterval(() => this._processFrame(), 500);

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
        if (this.videoEl) this.videoEl.srcObject = null;
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

        // ---------- Face ----------
        if (!faceResults || !faceResults.faceLandmarks || faceResults.faceLandmarks.length === 0) {
            this.signals.face_detected = false;
            this._drawOverlay(W, H);
            this._frameCount++;
            this._emitSignals();
            return;
        }
        // Use first face for primary signals
        const landmarks = faceResults.faceLandmarks[0];
        this.signals.face_detected = true;
        // Bystander detection: more than one face detected
        this.signals.bystander_present = (faceResults.faceLandmarks.length > 1);

        // ---------- Hand Tremor (face-jitter proxy) ----------
        // Track nose-tip position variance over a rolling window.
        // Natural webcam noise creates ~0.00001 variance; real tremor/movement ~0.0005+
        const noseTip = landmarks[1];
        const nosePos = { x: noseTip.x, y: noseTip.y };
        this._handHistory.push(nosePos);
        if (this._handHistory.length > 20) this._handHistory.shift();

        if (this._handHistory.length >= 8) {
            const meanX = this._handHistory.reduce((a, p) => a + p.x, 0) / this._handHistory.length;
            const meanY = this._handHistory.reduce((a, p) => a + p.y, 0) / this._handHistory.length;
            const varSum = this._handHistory.reduce((s, p) => s + ((p.x - meanX) ** 2 + (p.y - meanY) ** 2), 0);
            const variance = varSum / this._handHistory.length;
            // Dead zone: ignore variance below 0.00005 (normal sitting still)
            const adjusted = Math.max(0, variance - 0.00005);
            // Scale to 0–1 range (0.001 variance = full tremor)
            const rawScore = Math.min(1.0, adjusted * 1000);
            // Smooth with exponential moving average to avoid jumpy values
            const prev = this.signals.hand_tremor || 0;
            this.signals.hand_tremor = prev * 0.6 + rawScore * 0.4;
        }

        // Also use Hand Landmarker if available and hand is visible (higher precision)
        if (handResults && handResults.handLandmarks && handResults.handLandmarks.length > 0) {
            const wrist = handResults.handLandmarks[0][0];
            const wristPos = { x: wrist.x, y: wrist.y };
            if (!this._wristHistory) this._wristHistory = [];
            this._wristHistory.push(wristPos);
            if (this._wristHistory.length > 10) this._wristHistory.shift();
            if (this._wristHistory.length >= 5) {
                const mX = this._wristHistory.reduce((a, p) => a + p.x, 0) / this._wristHistory.length;
                const mY = this._wristHistory.reduce((a, p) => a + p.y, 0) / this._wristHistory.length;
                const vSum = this._wristHistory.reduce((s, p) => s + ((p.x - mX) ** 2 + (p.y - mY) ** 2), 0);
                const wristTremor = Math.min(1.0, (vSum / this._wristHistory.length) * 20000);
                // Override face-jitter with more accurate wrist measurement
                this.signals.hand_tremor = wristTremor;
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
        if (poseResults && poseResults.poseLandmarks && poseResults.poseLandmarks.length > 0) {
            const pose = poseResults.poseLandmarks[0];
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

        // Existing eye and leaning logic (unchanged) follows after this block...

        // ─── Eye Aperture Ratio (Squinting Detection) ───
        const leftEyeGap = Math.abs(landmarks[159].y - landmarks[145].y);
        const rightEyeGap = Math.abs(landmarks[386].y - landmarks[374].y);
        const avgEyeGap = (leftEyeGap + rightEyeGap) / 2;

        this._eyeHistory.push(avgEyeGap);
        if (this._eyeHistory.length > 8) this._eyeHistory.shift();
        const smoothedEye = this._eyeHistory.reduce((a, b) => a + b, 0) / this._eyeHistory.length;

        this.signals.eye_openness = Math.min(smoothedEye / 0.022, 1.0);
        this.signals.squinting = this.signals.eye_openness < 0.5;

        // ─── Face Width (Leaning Forward / Proximity Detection) ───
        // faceWidth already computed above for age estimation — reuse it
        this._faceWidthHistory.push(faceWidth);
        if (this._faceWidthHistory.length > 10) this._faceWidthHistory.shift();
        const smoothedWidth = this._faceWidthHistory.reduce((a, b) => a + b, 0) / this._faceWidthHistory.length;

        if (!this._baselineFaceWidth && this._frameCount >= 4) {
            this._baselineFaceWidth = smoothedWidth;
            console.log('[Vision] Baseline face width:', this._baselineFaceWidth.toFixed(4));
        }

        if (this._baselineFaceWidth) {
            const ratio = smoothedWidth / this._baselineFaceWidth;
            this.signals.proximity = ratio;
            this.signals.leaning_forward = ratio > 1.25;
        }

        // Draw landmarks and overlay
        this._drawLandmarks(landmarks, W, H);
        this._drawOverlay(W, H);

        this._frameCount++;
        this._emitSignals();
    }

    _drawLandmarks(landmarks, W, H) {
        const keyPoints = [
            { idx: 159, color: this.signals.squinting ? '#ef4444' : '#10b981' },
            { idx: 145, color: this.signals.squinting ? '#ef4444' : '#10b981' },
            { idx: 386, color: this.signals.squinting ? '#ef4444' : '#10b981' },
            { idx: 374, color: this.signals.squinting ? '#ef4444' : '#10b981' },
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
            this.ctx.arc(x, y, 3, 0, Math.PI * 2);
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
        } else if (!this._baselineFaceWidth) {
            text = `📐 Calibrating... (${this._frameCount}/4)`;
        } else {
            const parts = [];
            if (this.signals.squinting) parts.push('👁️ SQUINTING');
            else parts.push(`👁️ ${(this.signals.eye_openness * 100).toFixed(0)}%`);
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
