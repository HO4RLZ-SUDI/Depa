# ElderCare AI — caregiver/resident chatbot (the "Creative" pillar).
#
# Thin client over the z.ai (Zhipu GLM) chat API, which is OpenAI-compatible
# (POST {base}/chat/completions, Bearer auth). Keeps a short rolling history so
# the conversation has context, and lets main inject live status (vitals, risk,
# medication schedule) so the assistant can answer questions about the person.
#
# Network calls are blocking but run on the web server's threadpool (FastAPI
# runs sync route handlers off the event loop), so they don't stall the app.

import threading

import requests

import config


class Chatbot:
    def __init__(self):
        self._lock = threading.Lock()
        self._history: list[dict] = []     # [{"role","content"}, ...]
        self._max_turns = 8                # keep the last N exchanges

    @property
    def enabled(self) -> bool:
        return bool(config.ZAI_API_KEY)

    def ask(self, message: str, context: str | None = None) -> str:
        if not self.enabled:
            return "ระบบแชตยังไม่ได้ตั้งค่า (ต้องตั้ง ZAI_API_KEY) ค่ะ"
        message = (message or "").strip()
        if not message:
            return "พิมพ์ข้อความได้เลยค่ะ"

        system = self._system_prompt(context)
        with self._lock:
            self._history.append({"role": "user", "content": message})
            msgs = [{"role": "system", "content": system}] + self._history[-self._max_turns * 2:]

        try:
            reply = self._call(msgs)
        except Exception as exc:
            print(f"[chat] z.ai error: {exc}")
            return "ขออภัยค่ะ ตอนนี้ตอบไม่ได้ ลองใหม่อีกครั้งนะคะ"

        with self._lock:
            self._history.append({"role": "assistant", "content": reply})
        return reply

    def _call(self, messages: list[dict]) -> str:
        url = f"{config.ZAI_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.ZAI_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": config.ZAI_MODEL,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 512,
        }
        r = requests.post(url, json=body, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()

    def _system_prompt(self, context: str | None) -> str:
        base = (
            f"คุณคือผู้ช่วยอัจฉริยะของระบบดูแลผู้สูงอายุ 'ElderCare AI' คอยดูแล{config.PERSON_NAME} "
            "พูดจาสุภาพ อบอุ่น กระชับ เป็นภาษาไทย ให้คำแนะนำสุขภาพเบื้องต้นและเรื่องยา "
            "และตอบคำถามทั่วไปได้ หากเป็นเหตุฉุกเฉิน (เช่น เจ็บหน้าอก หายใจไม่ออก ล้มแล้วลุกไม่ได้) "
            "ให้แนะนำติดต่อผู้ดูแลหรือโทร 1669 ทันที และเตือนว่าคุณไม่ใช่แพทย์"
        )
        if context:
            base += f"\n\nข้อมูลสถานะปัจจุบันของระบบ:\n{context}"
        return base
