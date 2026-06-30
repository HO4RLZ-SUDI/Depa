# ElderCare AI — Data Analytics: turn raw events/vitals into a single risk picture.
#
# The brain logs everything to the Database; this module reads it back and
# computes a 0–100 risk score plus a status level (0 normal, 1 warning, 2 alert)
# that drives the status LED, the dashboard color, and escalation. It also owns
# the two time-based watches: inactivity and medication adherence.

from datetime import datetime, timedelta

import config


class Analytics:
    def __init__(self, db):
        self._db = db
        # Remember which med slots we've already handled today so we remind /
        # flag each slot exactly once.
        self._med_reminded: set[str] = set()
        self._med_missed: set[str] = set()
        self._taken: set[str] = set()
        self._day_marker = datetime.now().date()

    # Weight + reason per event kind; each kind contributes once (deduped).
    _RISK = {
        "sos":        (70, "กดปุ่มขอความช่วยเหลือ (SOS)"),
        "fall":       (60, "ตรวจพบการล้ม"),
        "inactivity": (30, "ไม่มีการเคลื่อนไหวเป็นเวลานาน"),
        "med_missed": (20, "ขาดการทานยาตามเวลา"),
        "temp":       (15, "อุณหภูมิห้องผิดปกติ"),
    }

    # --- aggregate risk --------------------------------------------------
    def assess(self) -> dict:
        """Risk from UN-acknowledged events only — ack clears it."""
        now = datetime.now()
        # Count each risk kind once, so repeated presses don't inflate the score.
        kinds = {ev["kind"] for ev in
                 self._db.events_since(now - timedelta(hours=6), unacked_only=True)}

        score = 0
        reasons: list[str] = []
        for kind in kinds:
            if kind in self._RISK:
                weight, reason = self._RISK[kind]
                score += weight
                reasons.append(reason)

        score = min(score, 100)
        if score >= 60:
            level = 2
        elif score >= 25:
            level = 1
        else:
            level = 0
        return {"score": score, "level": level, "reasons": reasons}

    # --- inactivity watch ------------------------------------------------
    def check_inactivity(self) -> str | None:
        """Return a message if no motion for too long, else None."""
        last = self._db.last_motion_time()
        if last is None:
            return None
        idle = (datetime.now() - last).total_seconds()
        if idle >= config.INACTIVITY_ALERT_SECONDS:
            mins = int(idle // 60)
            return f"ไม่พบการเคลื่อนไหวของ{config.PERSON_NAME}มา {mins} นาที"
        return None

    # --- medication schedule --------------------------------------------
    def check_medication(self) -> dict | None:
        """
        Drive the medication schedule. Returns one of:
          {"action": "remind", "slot": "08:00"}  -> time to take a dose
          {"action": "missed", "slot": "08:00"}  -> grace window elapsed unacked
          None                                    -> nothing to do right now
        Caller marks a dose taken via mark_med_taken(slot).
        """
        now = datetime.now()
        self._roll_day(now)

        for slot in config.MED_TIMES:
            slot_dt = self._slot_datetime(slot, now)
            if slot in self._med_missed:
                continue
            # Reminder window opens at the scheduled time.
            if now >= slot_dt and slot not in self._med_reminded:
                self._med_reminded.add(slot)
                return {"action": "remind", "slot": slot}
            # Missed if the grace window elapsed and it was reminded but not taken.
            grace_end = slot_dt + timedelta(minutes=config.MED_REMIND_GRACE_MINUTES)
            if (slot in self._med_reminded and slot not in self._med_taken_today()
                    and now >= grace_end):
                self._med_missed.add(slot)
                return {"action": "missed", "slot": slot}
        return None

    def mark_med_taken(self, slot: str | None = None):
        # slot=None (e.g. the confirm button) clears every slot reminded today.
        if slot is None:
            self._taken |= set(self._med_reminded)
        else:
            self._taken.add(slot)

    # --- internals -------------------------------------------------------
    def _med_taken_today(self) -> set[str]:
        return self._taken

    def _slot_datetime(self, slot: str, now: datetime) -> datetime:
        hh, mm = (int(x) for x in slot.split(":"))
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    def _roll_day(self, now: datetime):
        if now.date() != self._day_marker:
            self._day_marker = now.date()
            self._med_reminded.clear()
            self._med_missed.clear()
            self._taken.clear()
