# ElderCare AI — central configuration for the elderly-care brain (MPU side).
#
# Everything tunable lives here. Secrets/endpoints are read from the
# environment so they never get committed; sensible defaults keep the app
# runnable on a bare board for a demo.

import os


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# --- Person / deployment identity ---------------------------------------
PERSON_NAME = os.getenv("CARE_PERSON_NAME", "คุณยาย")          # spoken/displayed name
CAREGIVER_NAME = os.getenv("CARE_CAREGIVER_NAME", "ผู้ดูแล")

# --- Camera / fall detection --------------------------------------------
# Camera source for the Arduino camera peripheral: an int index ("0") or a
# typed string ("usb:0", "csi:0", "/dev/video0", "rtsp://..."). Kept as int
# when purely numeric, else passed through as a string.
_cam = os.getenv("CARE_CAMERA_INDEX", "0")
CAMERA_INDEX = int(_cam) if _cam.isdigit() else _cam
# V4L codec hint: "MJPG" lets most USB webcams deliver much higher fps at
# 640x480 than raw "YUYV". Empty = let the driver auto-pick. If a camera
# rejects MJPG, set CARE_CAMERA_CODEC="" to fall back.
CAMERA_CODEC = os.getenv("CARE_CAMERA_CODEC", "MJPG")
FRAME_WIDTH = int(os.getenv("CARE_FRAME_WIDTH", "640"))
FRAME_HEIGHT = int(os.getenv("CARE_FRAME_HEIGHT", "480"))
# --- Face-presence dispenser (active vision path) -----------------------
# Face must stay in frame this long to trigger buzzer + pill dispense.
FACE_HOLD_SECONDS = float(os.getenv("CARE_FACE_HOLD_SECONDS", "4.0"))
FACE_MIN_CONFIDENCE = float(os.getenv("CARE_FACE_MIN_CONFIDENCE", "0.6"))
# After triggering, the face must leave for this long before it can re-fire.
FACE_REARM_SECONDS = float(os.getenv("CARE_FACE_REARM_SECONDS", "1.5"))

# --- Face recognition / identity (LBPH, opencv-contrib) ------------------
FACE_RECOGNITION_ENABLED = _env_bool("CARE_FACE_RECOGNITION", True)
FACES_DIR = os.getenv("CARE_FACES_DIR", os.path.join(os.path.dirname(__file__), "faces"))
# LBPH distance threshold: lower = stricter match (typical 60–80).
FACE_RECOG_THRESHOLD = float(os.getenv("CARE_FACE_RECOG_THRESHOLD", "70"))
# Only dispense to a recognized person (medication safety). Off by default.
DISPENSE_REQUIRE_KNOWN = _env_bool("CARE_DISPENSE_REQUIRE_KNOWN", False)

# --- Live video stream to the dashboard (MJPEG) -------------------------
STREAM_JPEG_QUALITY = int(os.getenv("CARE_STREAM_QUALITY", "50"))   # 1–100 (lower = faster)
STREAM_MAX_FPS = float(os.getenv("CARE_STREAM_MAX_FPS", "30"))
# Detection is the CPU bottleneck, so decouple it from streaming: only run the
# Haar detector every Nth frame, on a downscaled copy. Frames in between reuse
# the last box, so the video stays smooth while detection runs slower.
DETECT_EVERY_N_FRAMES = int(os.getenv("CARE_DETECT_EVERY", "5"))
DETECT_WIDTH = int(os.getenv("CARE_DETECT_WIDTH", "320"))           # downscaled width for Haar

# --- Fall detection (parked: pose model, see fall_detection.py) ----------
FALL_CONFIRM_SECONDS = float(os.getenv("CARE_FALL_CONFIRM_SECONDS", "2.5"))
FALL_COOLDOWN_SECONDS = float(os.getenv("CARE_FALL_COOLDOWN_SECONDS", "30"))

# --- Vitals / environment thresholds ------------------------------------
TEMP_MIN_C = float(os.getenv("CARE_TEMP_MIN_C", "16"))
TEMP_MAX_C = float(os.getenv("CARE_TEMP_MAX_C", "34"))
# Inactivity watch. The Modulino kit has no PIR, so "activity" here means the
# face was seen by the camera — only meaningful if the unit faces where the
# person usually is. Off by default to avoid false alarms.
INACTIVITY_ENABLED = _env_bool("CARE_INACTIVITY_ENABLED", False)
INACTIVITY_ALERT_SECONDS = float(os.getenv("CARE_INACTIVITY_SECONDS", str(3 * 3600)))

# --- Medication schedule (24h "HH:MM", local time) ----------------------
# Comma-separated. Append "@A"/"@B"/"@C" (or "@0"/"@1"/"@2") to pick the
# dispenser channel/servo for that dose, e.g. "08:00@A,18:00@B". Default = A.
def _chan_to_int(c: str) -> int:
    return {"a": 0, "0": 0, "b": 1, "1": 1, "c": 2, "2": 2}.get(c.strip().lower(), 0)


MED_TIMES: list[str] = []
MED_CHANNEL: dict[str, int] = {}
for _item in os.getenv("CARE_MED_TIMES", "08:00@A,18:00@B").split(","):
    _item = _item.strip()
    if not _item:
        continue
    _t, _, _ch = _item.partition("@")
    _t = _t.strip()
    MED_TIMES.append(_t)
    MED_CHANNEL[_t] = _chan_to_int(_ch) if _ch else 0

MED_REMIND_GRACE_MINUTES = int(os.getenv("CARE_MED_GRACE_MIN", "30"))

# --- Notifications -------------------------------------------------------
# Default channel is ntfy.sh (free, no account). Set CARE_NTFY_TOPIC to a
# private random topic and subscribe on the caregiver's phone app.
NTFY_TOPIC = os.getenv("CARE_NTFY_TOPIC", "")
NTFY_SERVER = os.getenv("CARE_NTFY_SERVER", "https://ntfy.sh")
# Optional Telegram bot fallback.
TELEGRAM_BOT_TOKEN = os.getenv("CARE_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("CARE_TELEGRAM_CHAT_ID", "")
# Optional generic webhook (POST JSON) — e.g. LINE Notify proxy, n8n, IFTTT.
WEBHOOK_URL = os.getenv("CARE_WEBHOOK_URL", "")

# --- Cloud database sync -------------------------------------------------
# Local SQLite is always written. If a REST endpoint is set, events are also
# mirrored to the cloud (Firebase REST, Supabase, or your own API).
CLOUD_SYNC_URL = os.getenv("CARE_CLOUD_URL", "")        # e.g. https://xxx.firebaseio.com/events.json
CLOUD_SYNC_TOKEN = os.getenv("CARE_CLOUD_TOKEN", "")     # bearer/auth token if needed
DB_PATH = os.getenv("CARE_DB_PATH", "care_data.sqlite3")

# --- Voice assistant -----------------------------------------------------
VOICE_ENABLED = _env_bool("CARE_VOICE_ENABLED", True)
VOICE_RATE = int(os.getenv("CARE_VOICE_RATE", "165"))    # words per minute

# --- Chatbot (z.ai / Zhipu GLM, OpenAI-compatible) ----------------------
# Set your key: export ZAI_API_KEY="...". Chat is enabled only when a key
# is present. GLM endpoint is OpenAI-compatible (/chat/completions).
ZAI_API_KEY = os.getenv("ZAI_API_KEY", "") or os.getenv("CARE_ZAI_KEY", "")
ZAI_BASE_URL = os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
ZAI_MODEL = os.getenv("ZAI_MODEL", "glm-4.5-flash")

# --- Sensor polling ------------------------------------------------------
SENSOR_POLL_SECONDS = float(os.getenv("CARE_SENSOR_POLL_SECONDS", "2.0"))
