# ElderCare AI — offline voice assistant (the "Creative" pillar: spoken interaction).
#
# Uses pyttsx3 (espeak-ng backend) so it runs fully on-device with no cloud and
# no API cost. Speech is queued and spoken on a single worker thread, so callers
# (alarm handlers, the scheduler) never block waiting for audio to finish.

import queue
import threading

import config

try:
    import pyttsx3
    _HAVE_TTS = True
except Exception:  # library/audio not present — degrade to console
    _HAVE_TTS = False


class Voice:
    def __init__(self):
        self._q: queue.Queue[str] = queue.Queue()
        self._engine = None
        if config.VOICE_ENABLED and _HAVE_TTS:
            try:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", config.VOICE_RATE)
            except Exception as exc:
                print(f"[voice] init failed, falling back to text: {exc}")
                self._engine = None
        threading.Thread(target=self._worker, daemon=True).start()

    def say(self, text: str):
        """Queue a phrase to be spoken (non-blocking)."""
        self._q.put(text)

    def _worker(self):
        while True:
            text = self._q.get()
            print(f"[voice] 🔊 {text}")
            if self._engine is not None:
                try:
                    self._engine.say(text)
                    self._engine.runAndWait()
                except Exception as exc:
                    print(f"[voice] speak failed: {exc}")
