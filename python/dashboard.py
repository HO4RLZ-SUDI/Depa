# ElderCare AI — caregiver dashboard via the arduino:web_ui Brick.
#
# The web_ui brick serves assets/index.html at http://<board-ip>:7000/ and lets
# Python publish data through REST endpoints registered with expose_api(...).
# The browser polls GET /api/state once a second and renders it; caregiver
# actions are simple GET endpoints the page calls with fetch().
#
# We keep the latest snapshot in memory (updated by main via push_status) and
# hand it back on demand — no WebSocket, no push, which is the pattern the
# brick supports most reliably.
#
# Access control note ("Safe" pillar): this is served on the device LAN; put it
# behind the board's auth / a reverse proxy before exposing it beyond the LAN.

import base64
import time

import config

try:
    from arduino.app_bricks.web_ui import WebUI
    _HAVE_WEBUI = True
except Exception:
    _HAVE_WEBUI = False


class Dashboard:
    def __init__(self, on_command, frame_provider=None, on_enroll=None, on_chat=None):
        """
        on_command(name, payload)   handles caregiver actions.
        frame_provider() -> bytes   latest annotated JPEG bytes (live video).
        on_enroll(name) -> int      enroll the current face, return sample count.
        on_chat(message) -> str     chatbot reply for a user message.
        """
        self._on_command = on_command
        self._frame_provider = frame_provider
        self._on_enroll = on_enroll
        self._on_chat = on_chat
        self._snapshot: dict = {"status": "starting"}
        self._ui = None
        if _HAVE_WEBUI:
            self._ui = WebUI()
            # Live data the browser polls.
            self._ui.expose_api("GET", "/api/state", self._api_state)
            self._ui.expose_api("GET", "/api/history", self._api_history)
            # Live video: MJPEG stream (one connection, high fps) + base64
            # single-frame fallback for clients that can't do multipart.
            self._ui.expose_api("GET", "/video", self._video)
            self._ui.expose_api("GET", "/api/frame", self._api_frame)
            # Caregiver -> device actions. The brick is FastAPI, so typed query
            # params (name, q) are injected automatically.
            self._ui.expose_api("GET", "/api/ack", self._api_ack)
            self._ui.expose_api("GET", "/api/sos", self._api_sos)
            self._ui.expose_api("GET", "/api/dispense_a", self._api_dispense_a)
            self._ui.expose_api("GET", "/api/dispense_b", self._api_dispense_b)
            self._ui.expose_api("GET", "/api/dispense_c", self._api_dispense_c)
            self._ui.expose_api("GET", "/api/med_taken", self._api_med_taken)
            self._ui.expose_api("GET", "/api/enroll", self._api_enroll)
            self._ui.expose_api("GET", "/api/chat", self._api_chat)
        else:
            print("[dashboard] web_ui brick not available — running headless.")

    def push_status(self, snapshot: dict):
        """Store the latest snapshot; served on the next /api/state poll."""
        self._snapshot = snapshot

    # --- REST handlers (signature must be (_req=None) for the brick) ------
    def _api_state(self, _req=None):
        return self._snapshot

    def _video(self, _req=None):
        """MJPEG multipart stream — the smooth, high-fps video path."""
        from fastapi.responses import StreamingResponse

        provider = self._frame_provider
        period = 1.0 / max(1.0, config.STREAM_MAX_FPS)

        def gen():
            while True:
                buf = provider() if provider else None
                if buf:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                           + buf + b"\r\n")
                time.sleep(period)

        return StreamingResponse(gen(),
                                 media_type="multipart/x-mixed-replace; boundary=frame")

    def _api_frame(self, _req=None):
        buf = self._frame_provider() if self._frame_provider else None
        jpg = ("data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")) if buf else ""
        return {"jpg": jpg}

    def _api_history(self, _req=None):
        return {"events": self._on_command("history", {}) or []}

    def _api_enroll(self, name: str = ""):
        # FastAPI injects ?name=... ; fall back to the configured resident.
        name = (name or "").strip() or config.PERSON_NAME
        samples = self._on_enroll(name) if self._on_enroll else 0
        return {"ok": True, "name": name, "samples": samples}

    def _api_chat(self, q: str = ""):
        reply = self._on_chat(q) if self._on_chat else "ระบบแชตปิดอยู่ค่ะ"
        return {"reply": reply}

    def _api_ack(self, _req=None):
        self._on_command("ack", {})
        return {"ok": True}

    def _api_sos(self, _req=None):
        self._on_command("sos", {})
        return {"ok": True}

    def _api_dispense_a(self, _req=None):
        self._on_command("dispense", {"channel": 0})
        return {"ok": True, "channel": "A"}

    def _api_dispense_b(self, _req=None):
        self._on_command("dispense", {"channel": 1})
        return {"ok": True, "channel": "B"}

    def _api_dispense_c(self, _req=None):
        self._on_command("dispense", {"channel": 2})
        return {"ok": True, "channel": "C"}

    def _api_med_taken(self, _req=None):
        self._on_command("med_taken", {})
        return {"ok": True}
