# ElderCare AI — AI face detection + identity + live video (the "Smart" pillar).
#
# One capture loop does it all:
#   1. MediaPipe Face Detection locates the face in each frame.
#   2. The face crop is passed to FaceDB (LBPH) to identify WHO it is.
#   3. A 0..8 hold progress is reported; once a face is held FACE_HOLD_SECONDS
#      the trigger callback fires (buzzer + pill dispense on the Python side).
#   4. Each frame is annotated (bounding box + ID/UNKNOWN + progress bar) and
#      JPEG-encoded to base64 so the dashboard can show a live video feed.
#
# Runs in its own thread; never touches hardware/network directly.

import base64
import os
import threading
import time

import config
from face_db import FaceDB

# Detection uses the Haar cascade that ships inside base OpenCV — no mediapipe,
# no extra wheels, so it works with the cv2 the Arduino runtime already provides.
try:
    import cv2
    _HAVE_CV = True
except Exception:
    _HAVE_CV = False


def _load_cascade():
    """Locate the frontal-face Haar cascade (bundled with opencv, or local)."""
    candidates = []
    env = os.getenv("CARE_CASCADE_PATH")
    if env:
        candidates.append(env)
    try:
        candidates.append(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    except Exception:
        pass
    candidates.append(os.path.join(os.path.dirname(__file__),
                                   "haarcascade_frontalface_default.xml"))
    for path in candidates:
        if path and os.path.exists(path):
            clf = cv2.CascadeClassifier(path)
            if not clf.empty():
                print(f"[face] cascade loaded: {path}")
                return clf
    print("[face] no Haar cascade found — detection disabled.")
    return None


class FaceDetector:
    def __init__(self, on_progress, on_trigger):
        """
        on_progress(count: int)            -> 0..8 as the hold fills up.
        on_trigger(identity, known: bool)  -> once per arming after the hold.
        """
        self._on_progress = on_progress
        self._on_trigger = on_trigger
        self._running = False

        self._present = False
        self._box = None                  # last detected face box (x, y, w, h)
        self._identity: str | None = None
        self._identity_known = False
        self._confidence = 0.0

        self._face_start: float | None = None
        self._absent_since: float | None = None
        self._armed = True
        self._last_count = -1
        self._last_gray_crop = None

        self._facedb = FaceDB()
        self._jpeg_lock = threading.Lock()
        self._jpeg_bytes: bytes | None = None    # latest annotated frame (raw JPEG)

    # --- public accessors ------------------------------------------------
    def start(self):
        if not _HAVE_CV:
            print("[face] OpenCV/MediaPipe not available — face detection disabled.")
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    @property
    def present(self) -> bool:
        return self._present

    @property
    def identity(self) -> str | None:
        return self._identity

    @property
    def identity_known(self) -> bool:
        return self._identity_known

    @property
    def recognition_available(self) -> bool:
        return self._facedb.available

    def latest_jpeg(self) -> bytes | None:
        """Latest annotated frame as raw JPEG bytes (for the MJPEG stream)."""
        with self._jpeg_lock:
            return self._jpeg_bytes

    def latest_frame(self) -> str | None:
        """Same frame as a base64 data URL (fallback for /api/frame)."""
        data = self.latest_jpeg()
        if not data:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")

    def enroll_current(self, name: str) -> int:
        """Enroll the most recent face crop under `name`; return sample count."""
        return self._facedb.enroll(name, self._last_gray_crop)

    # --- capture loop ----------------------------------------------------
    def _loop(self):
        # The App Lab Python container reaches the camera through the Arduino
        # camera peripheral, NOT raw cv2.VideoCapture (which can't see the
        # device). The peripheral also throttles to `fps`, so no manual pacing.
        from arduino.app_peripherals.camera import Camera

        fps = int(max(1, config.STREAM_MAX_FPS))
        kwargs = {"codec": config.CAMERA_CODEC} if config.CAMERA_CODEC else {}
        try:
            cam = Camera(config.CAMERA_INDEX,
                         resolution=(config.FRAME_WIDTH, config.FRAME_HEIGHT),
                         fps=fps, **kwargs)
            cam.start()
        except Exception as exc:
            print(f"[face] camera open failed: {exc}")
            return

        cascade = _load_cascade()
        every = max(1, config.DETECT_EVERY_N_FRAMES)
        frame_i = 0
        try:
            while self._running:
                try:
                    frame = cam.capture()          # BGR np.ndarray or None
                except Exception as exc:
                    print(f"[face] capture error: {exc}")
                    time.sleep(0.2)
                    continue
                if frame is None:
                    time.sleep(0.05)
                    continue
                # Detect only every Nth frame (the expensive part); stream every
                # frame so the video stays smooth.
                if frame_i % every == 0:
                    self._detect(frame, cascade)
                frame_i += 1
                self._evaluate(self._present)
                self._annotate_and_store(frame, self._box, self._identity_known)
        finally:
            cam.stop()

    def _detect(self, frame, cascade):
        """Run the Haar detector (downscaled) + recognition; update state."""
        if cascade is None:
            self._present = False
            self._box = None
            return
        h, w = frame.shape[:2]
        gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Downscale for detection — Haar cost scales with pixel count.
        scale = config.DETECT_WIDTH / float(w) if w > config.DETECT_WIDTH else 1.0
        small = (cv2.resize(gray_full, (int(w * scale), int(h * scale)))
                 if scale < 1.0 else gray_full)
        faces = cascade.detectMultiScale(small, scaleFactor=1.1,
                                         minNeighbors=5, minSize=(48, 48))

        present = len(faces) > 0
        box = None
        name, known = None, False
        if present:
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            inv = 1.0 / scale
            x, y = int(fx * inv), int(fy * inv)
            bw, bh = int(fw * inv), int(fh * inv)
            box = (x, y, bw, bh)
            gray = gray_full[y:y + bh, x:x + bw]
            if gray.size:
                self._last_gray_crop = gray
                if config.FACE_RECOGNITION_ENABLED:
                    n, conf = self._facedb.identify(gray)
                    self._confidence = conf
                    if n:
                        name, known = n, True

        self._present = present
        self._box = box
        self._identity = name if known else None
        self._identity_known = known

    # --- hold logic (5 s) ------------------------------------------------
    def _evaluate(self, present: bool):
        now = time.time()
        if present:
            self._absent_since = None
            if self._face_start is None:
                self._face_start = now
            elapsed = now - self._face_start
            hold = config.FACE_HOLD_SECONDS
            count = int(min(elapsed / hold, 1.0) * 8)
            self._emit(max(0, min(8, count)))
            if elapsed >= hold and self._armed:
                self._armed = False
                self._emit(8)
                try:
                    self._on_trigger(self._identity, self._identity_known)
                except Exception as exc:
                    print(f"[face] trigger callback error: {exc}")
        else:
            self._face_start = None
            self._emit(0)
            if self._absent_since is None:
                self._absent_since = now
            elif (now - self._absent_since) >= config.FACE_REARM_SECONDS:
                self._armed = True

    def _emit(self, count: int):
        if count != self._last_count:
            self._last_count = count
            try:
                self._on_progress(count)
            except Exception as exc:
                print(f"[face] progress callback error: {exc}")

    # --- drawing + JPEG encode ------------------------------------------
    def _annotate_and_store(self, frame, box, known):
        h, w = frame.shape[:2]
        if box:
            x, y, bw, bh = box
            # green = recognized resident, orange = face but unknown.
            color = (0, 200, 0) if known else (0, 140, 255)
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            # ASCII-only tag (cv2 can't draw Thai); the name shows in the web UI.
            tag = f"ID {int(self._confidence)}%" if known else "UNKNOWN"
            cv2.putText(frame, tag, (x, max(12, y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # Hold progress bar along the bottom edge.
        count = max(0, self._last_count)
        if count > 0:
            bar_w = int(w * count / 8)
            cv2.rectangle(frame, (0, h - 8), (bar_w, h), (255, 160, 0), -1)

        ok, buf = cv2.imencode(".jpg", frame,
                               [cv2.IMWRITE_JPEG_QUALITY, config.STREAM_JPEG_QUALITY])
        if ok:
            with self._jpeg_lock:
                self._jpeg_bytes = buf.tobytes()
