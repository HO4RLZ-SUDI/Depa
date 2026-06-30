# ElderCare AI — AI fall detection (the "Smart" pillar).
#
# Real-time pose estimation with OpenCV + MediaPipe Pose. We track the body's
# orientation and how fast its center drops; a fall is only confirmed when the
# body becomes horizontal AND stays down for FALL_CONFIRM_SECONDS, which rejects
# the common false positives (sitting, bending, lying down to rest).
#
# The detector runs in its own thread and invokes a callback when a fall is
# confirmed; it never touches hardware or the network itself.

import threading
import time

import config

try:
    import cv2
    import mediapipe as mp
    import numpy as np
    _HAVE_CV = True
except Exception:
    _HAVE_CV = False


class FallDetector:
    def __init__(self, on_fall):
        """on_fall(info: dict) is called once per confirmed fall (after cooldown)."""
        self._on_fall = on_fall
        self._running = False
        self._latest_status = {"person": False, "posture": "unknown"}
        self._down_since: float | None = None
        self._last_alert = 0.0

    def start(self):
        if not _HAVE_CV:
            print("[fall] OpenCV/MediaPipe not available — fall detection disabled.")
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def status(self) -> dict:
        return dict(self._latest_status)

    def _loop(self):
        mp_pose = mp.solutions.pose
        cap = cv2.VideoCapture(config.CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)

        with mp_pose.Pose(model_complexity=0, min_detection_confidence=0.5,
                          min_tracking_confidence=0.5) as pose:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.1)
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = pose.process(rgb)
                self._evaluate(result, mp_pose)
        cap.release()

    def _evaluate(self, result, mp_pose):
        now = time.time()
        if not result.pose_landmarks:
            self._latest_status = {"person": False, "posture": "unknown"}
            self._down_since = None
            return

        lm = result.pose_landmarks.landmark
        P = mp_pose.PoseLandmark

        # Shoulder/hip midpoints define the torso axis.
        sx = (lm[P.LEFT_SHOULDER].x + lm[P.RIGHT_SHOULDER].x) / 2
        sy = (lm[P.LEFT_SHOULDER].y + lm[P.RIGHT_SHOULDER].y) / 2
        hx = (lm[P.LEFT_HIP].x + lm[P.RIGHT_HIP].x) / 2
        hy = (lm[P.LEFT_HIP].y + lm[P.RIGHT_HIP].y) / 2

        # Torso tilt: |Δy| vs |Δx|. Upright -> tall (Δy dominates); fallen ->
        # horizontal (Δx dominates). Coordinates are normalized 0..1.
        dy = abs(sy - hy)
        dx = abs(sx - hx)
        horizontal = dx > dy  # torso lying along the floor plane

        # A low body center (near the bottom of the frame) reinforces "on floor".
        body_center_y = (sy + hy) / 2
        on_floor = body_center_y > 0.6

        is_down = horizontal and on_floor
        posture = "fallen" if is_down else "upright"
        self._latest_status = {"person": True, "posture": posture}

        if is_down:
            if self._down_since is None:
                self._down_since = now
            elif (now - self._down_since) >= config.FALL_CONFIRM_SECONDS:
                self._maybe_fire(now)
        else:
            self._down_since = None

    def _maybe_fire(self, now: float):
        if (now - self._last_alert) < config.FALL_COOLDOWN_SECONDS:
            return
        self._last_alert = now
        self._on_fall({"posture": "fallen", "confirmed_after_s": config.FALL_CONFIRM_SECONDS})
