# ElderCare AI — on-device face recognition / identity (the "Smart" + "Safe" pillars).
#
# Lightweight LBPH recognizer (OpenCV contrib). Enrollment images live under
# faces/<PersonName>/*.jpg and are trained at startup; new samples can be added
# at runtime from the dashboard. Everything stays on the board — no face data
# leaves the device, which keeps the privacy/ethics promise.
#
# Degrades gracefully: if cv2.face (opencv-contrib) isn't present, detection +
# video still work, identity just reports "unknown".

import os
import threading
import time

import config

try:
    import cv2
    import numpy as np
    _HAVE_CV = True
except Exception:
    _HAVE_CV = False

FACE_SIZE = (200, 200)
_EXT = (".jpg", ".jpeg", ".png")


class FaceDB:
    def __init__(self, faces_dir: str | None = None):
        self.dir = faces_dir or config.FACES_DIR
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.Lock()
        self._labels: dict[int, str] = {}   # label id -> person name
        self._trained = False
        self._recognizer = None
        self._available = _HAVE_CV and hasattr(cv2, "face")
        if not self._available:
            print("[face_db] cv2.face unavailable (need opencv-contrib) — recognition off.")
        else:
            self.train()

    @property
    def available(self) -> bool:
        return self._available

    def train(self):
        """(Re)build the recognizer from every image under faces/<name>/."""
        if not self._available:
            return
        images, labels, names = [], [], {}
        next_id = 0
        for person in sorted(os.listdir(self.dir)):
            pdir = os.path.join(self.dir, person)
            if not os.path.isdir(pdir):
                continue
            names[next_id] = person
            for f in os.listdir(pdir):
                if not f.lower().endswith(_EXT):
                    continue
                img = cv2.imread(os.path.join(pdir, f), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                images.append(cv2.resize(img, FACE_SIZE))
                labels.append(next_id)
            next_id += 1

        with self._lock:
            if images:
                rec = cv2.face.LBPHFaceRecognizer_create()
                rec.train(images, np.array(labels))
                self._recognizer = rec
                self._labels = names
                self._trained = True
            else:
                self._recognizer = None
                self._labels = {}
                self._trained = False
        print(f"[face_db] trained on {len(images)} images / {len(names)} people")

    def identify(self, gray_face) -> tuple[str | None, float]:
        """Return (name, confidence%) — name is None when not confidently known."""
        if not self._available or not self._trained:
            return (None, 0.0)
        face = cv2.resize(gray_face, FACE_SIZE)
        with self._lock:
            label, dist = self._recognizer.predict(face)  # lower dist = better
        conf = max(0.0, min(100.0, 100.0 - dist))
        if dist <= config.FACE_RECOG_THRESHOLD:
            return (self._labels.get(label), conf)
        return (None, conf)

    def enroll(self, name: str, gray_face) -> int:
        """Save one sample for `name`, retrain, return total sample count."""
        if not self._available or gray_face is None:
            return 0
        pdir = os.path.join(self.dir, name)
        os.makedirs(pdir, exist_ok=True)
        fn = os.path.join(pdir, f"{int(time.time() * 1000)}.jpg")
        cv2.imwrite(fn, cv2.resize(gray_face, FACE_SIZE))
        self.train()
        return self.sample_count(name)

    def sample_count(self, name: str) -> int:
        pdir = os.path.join(self.dir, name)
        if not os.path.isdir(pdir):
            return 0
        return len([f for f in os.listdir(pdir) if f.lower().endswith(_EXT)])
