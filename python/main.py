# ElderCare AI — Smart Elderly Care, Python brain (UNO Q Linux/MPU side).
#
# Orchestrates the system and ties the pillars together:
#   Smart   — AI face detection (OpenCV + MediaPipe) in face_detection.py
#   IoT     — Modulino sensors/actuators over the Bridge in sensors.py
#   Safe    — push notifications + emergency buzzer + SOS/ack buttons
#   Green   — all-digital records in database.py (no paper), reuses the board
#   Creative— voice assistant + face-confirmed pill dispenser + dashboard
#
# Core flow: the camera watches for a face; Pixels fill up as a progress bar;
# once a face is held FACE_HOLD_SECONDS the buzzer beeps and the servo dispenses
# a dose. Buttons cover SOS / acknowledge / confirm-taken. Each concern runs on
# its own daemon thread; App.run() owns the lifecycle.

import threading
import time
from datetime import datetime

from arduino.app_utils import App

import config
import sensors
from analytics import Analytics
from chatbot import Chatbot
from dashboard import Dashboard
from database import Database
from face_detection import FaceDetector
from notifier import notify
from voice import Voice


def _ch_name(ch: int) -> str:
    return {0: "A", 1: "B", 2: "C"}.get(ch, "A")


class CareSystem:
    def __init__(self):
        self.db = Database()
        self.voice = Voice()
        self.analytics = Analytics(self.db)
        self.chatbot = Chatbot()
        # Face first so the dashboard can pull live frames + drive enrollment.
        self.face = FaceDetector(self._on_face_progress, self._on_face_held)
        self.dashboard = Dashboard(self._handle_command,
                                   frame_provider=self.face.latest_jpeg,
                                   on_enroll=self.face.enroll_current,
                                   on_chat=self._handle_chat)
        self._alarm_active = False
        self._pending_channel = 0   # which dispenser channel the next dose uses

    # --- lifecycle -------------------------------------------------------
    def start(self):
        self.db.log_event("info", "info", "ระบบดูแลผู้สูงอายุเริ่มทำงาน")
        self.voice.say(f"ระบบดูแล{config.PERSON_NAME}เริ่มทำงานแล้วค่ะ")
        self.face.start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._sensor_loop, daemon=True).start()
        threading.Thread(target=self._watch_loop, daemon=True).start()

    # --- on-board heartbeat (liveness, the "24/7 no downtime" promise) ---
    def _heartbeat_loop(self):
        state = False
        while True:
            state = not state
            try:
                sensors.set_led(state)
            except Exception as exc:
                print(f"[main] heartbeat bridge error: {exc}")
            time.sleep(0.5)

    # --- face detection callbacks ---------------------------------------
    def _on_face_progress(self, count: int):
        """Mirror the 0..8 hold progress onto the Modulino Pixels bar."""
        try:
            sensors.pixels_progress(count)
        except Exception as exc:
            print(f"[main] pixels bridge error: {exc}")

    def _on_face_held(self, identity, known):
        """Face held FACE_HOLD_SECONDS -> beep + dispense the dose."""
        who = identity if known else config.PERSON_NAME
        # Medication safety: optionally refuse to dispense to a stranger.
        if config.DISPENSE_REQUIRE_KNOWN and not known:
            print("[main] face held but identity unknown -> dispense blocked")
            self.db.log_event("med", "warning", "พบใบหน้าแต่ระบุตัวตนไม่ได้ — ไม่จ่ายยา")
            self.voice.say("ขออภัยค่ะ ระบบยังไม่รู้จักใบหน้านี้ กรุณาลงทะเบียนก่อนนะคะ")
            return
        ch = self._pending_channel
        ch_name = _ch_name(ch)
        print(f"[main] face held ({who}, known={known}) -> buzzer + dispense ch {ch_name}")
        try:
            sensors.buzzer_beep(1800, 250)
            sensors.dispense_pill(ch)
        except Exception as exc:
            print(f"[main] dispense bridge error: {exc}")
        self.analytics.mark_med_taken()  # presence confirms this round's dose
        self.db.log_event("med", "info",
                          f"จ่ายยาช่อง {ch_name} ให้{who} (ยืนยันด้วยใบหน้า {int(config.FACE_HOLD_SECONDS)} วิ)")
        self.voice.say(f"พบ{who}แล้วค่ะ ปัดยาช่อง {ch_name} ลงมาเรียบร้อย ทานยาได้เลยนะคะ")

    def _dispense(self, channel: int, source: str):
        """Manual dispense of one channel (physical button or dashboard)."""
        ch_name = _ch_name(channel)
        print(f"[main] dispense ch {ch_name} ({source})")
        try:
            sensors.buzzer_beep(1600, 150)
            sensors.dispense_pill(channel)
        except Exception as exc:
            print(f"[main] dispense bridge error: {exc}")
        self.db.log_event("med", "info", f"จ่ายยาช่อง {ch_name} ({source})")

    # --- chatbot ---------------------------------------------------------
    def _handle_chat(self, message: str) -> str:
        return self.chatbot.ask(message, self._chat_context())

    def _chat_context(self) -> str:
        v = self.db.latest_vitals() or {}
        risk = self.analytics.assess()
        meds = ", ".join(f"{t} (ช่อง {_ch_name(config.MED_CHANNEL.get(t, 0))})"
                         for t in config.MED_TIMES) or "-"
        return (f"- ผู้สูงอายุ: {config.PERSON_NAME}\n"
                f"- อุณหภูมิห้อง: {v.get('temp_c', '-')}°C, ความชื้น: {v.get('humidity', '-')}%\n"
                f"- คะแนนความเสี่ยงตอนนี้: {risk['score']}/100\n"
                f"- ตารางยา: {meds}")

    # --- IoT sensor polling + buttons ------------------------------------
    def _sensor_loop(self):
        while True:
            try:
                temp = sensors.read_temperature()
                hum = sensors.read_humidity()
                self.db.log_vitals(temp, hum, self.face.present)

                if temp not in (-127.0,) and not (config.TEMP_MIN_C <= temp <= config.TEMP_MAX_C):
                    self.db.log_event("temp", "warning",
                                      f"อุณหภูมิห้องผิดปกติ: {temp:.1f}°C",
                                      {"temp_c": temp})

                # Modulino buttons A/B/C dispense medication channels 0/1/2.
                if sensors.button_a():
                    self._dispense(0, "ปุ่ม A")
                if sensors.button_b():
                    self._dispense(1, "ปุ่ม B")
                if sensors.button_c():
                    self._dispense(2, "ปุ่ม C")

                self._push_dashboard(temp, hum)
            except Exception as exc:
                print(f"[main] sensor loop error: {exc}")
            time.sleep(config.SENSOR_POLL_SECONDS)

    # --- time-based watches: inactivity + medication reminders -----------
    def _watch_loop(self):
        while True:
            try:
                # Inactivity: no face seen for too long (opt-in; no PIR in kit).
                if config.INACTIVITY_ENABLED:
                    msg = self.analytics.check_inactivity()
                    if msg:
                        self.db.log_event("inactivity", "warning", msg)
                        notify("เฝ้าระวังการเคลื่อนไหว", msg, "warning")
                        self.voice.say(msg)

                # Medication schedule: remind by voice; dispensing happens when
                # the person actually shows up to the camera (face hold).
                med = self.analytics.check_medication()
                if med and med["action"] == "remind":
                    slot = med["slot"]
                    self._pending_channel = config.MED_CHANNEL.get(slot, 0)
                    ch_name = _ch_name(self._pending_channel)
                    text = f"ถึงเวลาทานยาช่อง {ch_name} แล้วนะคะ {config.PERSON_NAME} กรุณามาที่กล้องเพื่อรับยา ({slot})"
                    self.voice.say(text)
                    self.db.log_event("med", "info", f"เตือนทานยา {slot} (ช่อง {ch_name})")
                elif med and med["action"] == "missed":
                    text = f"{config.PERSON_NAME}ยังไม่ได้มารับยารอบ {med['slot']}"
                    self.db.log_event("med_missed", "warning", text)
                    notify("แจ้งเตือนการทานยา", text, "warning")
            except Exception as exc:
                print(f"[main] watch loop error: {exc}")
            time.sleep(5)

    # --- emergency handlers ---------------------------------------------
    def _on_sos(self):
        msg = f"{config.PERSON_NAME}กดปุ่มขอความช่วยเหลือ"
        print("[main] SOS pressed")
        self.db.log_event("sos", "critical", msg)
        self._alarm_active = True
        try:
            sensors.buzzer_alarm(True)
        except Exception as exc:
            print(f"[main] alarm bridge error: {exc}")
        notify("SOS — ขอความช่วยเหลือ", f"{msg} กรุณาตรวจสอบทันที", "critical")
        self.voice.say("ได้รับสัญญาณขอความช่วยเหลือแล้วค่ะ กำลังแจ้งผู้ดูแล")

    def _clear_alarm(self):
        self._alarm_active = False
        self.db.ack_all_unacked()   # acknowledge events so the risk score clears
        try:
            sensors.buzzer_alarm(False)
        except Exception as exc:
            print(f"[main] clear alarm error: {exc}")

    # --- dashboard commands + snapshot -----------------------------------
    def _handle_command(self, name: str, payload: dict):
        if name == "ack":
            self._clear_alarm()
            self.voice.say("ผู้ดูแลรับทราบแล้วค่ะ")
        elif name == "sos":
            self._on_sos()
        elif name == "dispense":
            self._dispense(int(payload.get("channel", 0)), "แดชบอร์ด")
        elif name == "med_taken":
            self.analytics.mark_med_taken(payload.get("slot"))
            self.db.log_event("med", "info", "ยืนยันทานยาแล้ว (แดชบอร์ด)")
        elif name == "history":
            return self.db.recent_events(100)

    def _push_dashboard(self, temp: float, hum: float):
        risk = self.analytics.assess()
        self.dashboard.push_status({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "person": config.PERSON_NAME,
            "temp_c": temp,
            "humidity": hum,
            "face_present": self.face.present,
            "identity": self.face.identity,
            "identity_known": self.face.identity_known,
            "recognition_on": self.face.recognition_available,
            "risk_score": risk["score"],
            "risk_level": risk["level"],
            "reasons": risk["reasons"],
            "alarm": self._alarm_active,
            "recent": self.db.recent_events(10),
        })


care = CareSystem()
care.start()

App.run()
