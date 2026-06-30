# ElderCare AI — push notifications to the caregiver (the "Safe" pillar).
#
# Multi-channel and best-effort: ntfy.sh (default, free, real push to phone),
# Telegram bot, and/or a generic JSON webhook. Any configured channel is tried;
# a failing channel never blocks the others or the care loop. All sends run off
# the caller's thread so a slow network never delays an alarm.

import threading

import requests

import config


_PRIORITY = {"info": "default", "warning": "high", "critical": "urgent"}
_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}


def notify(title: str, message: str, severity: str = "info"):
    """Fire a push notification on every configured channel, asynchronously."""
    threading.Thread(
        target=_dispatch, args=(title, message, severity), daemon=True
    ).start()


def _dispatch(title: str, message: str, severity: str):
    sent_any = False
    if config.NTFY_TOPIC:
        sent_any |= _send_ntfy(title, message, severity)
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        sent_any |= _send_telegram(title, message, severity)
    if config.WEBHOOK_URL:
        sent_any |= _send_webhook(title, message, severity)
    if not sent_any:
        # No channel configured (or all failed) — at least surface it in logs.
        print(f"[notify:{severity}] {title} — {message}")


def _send_ntfy(title: str, message: str, severity: str) -> bool:
    try:
        url = f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}"
        headers = {
            "Title": f"{_EMOJI.get(severity, '')} {title}".strip().encode("utf-8"),
            "Priority": _PRIORITY.get(severity, "default"),
            "Tags": severity,
        }
        requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=8)
        return True
    except Exception as exc:
        print(f"[notify] ntfy failed: {exc}")
        return False


def _send_telegram(title: str, message: str, severity: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        text = f"{_EMOJI.get(severity, '')} *{title}*\n{message}"
        requests.post(
            url,
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
        return True
    except Exception as exc:
        print(f"[notify] telegram failed: {exc}")
        return False


def _send_webhook(title: str, message: str, severity: str) -> bool:
    try:
        requests.post(
            config.WEBHOOK_URL,
            json={"title": title, "message": message, "severity": severity},
            timeout=8,
        )
        return True
    except Exception as exc:
        print(f"[notify] webhook failed: {exc}")
        return False
