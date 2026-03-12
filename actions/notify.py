"""Notification actions: Windows toast, email, console, log."""

import json
import logging
import platform
import urllib.request
import urllib.error

log = logging.getLogger("stream-monitor")

_notifier = None


def _get_notifier():
    global _notifier
    if _notifier is not None:
        return _notifier
    if platform.system() == "Windows":
        try:
            from winotify import Notification
            _notifier = "winotify"
            return _notifier
        except ImportError:
            pass
    _notifier = "console"
    return _notifier


def notify(message: str, title: str = "Stream Monitor", level: str = "info"):
    """Send notification via best available backend."""
    backend = _get_notifier()

    # Always log
    log.info(f"[{title}] {message}")

    if backend == "winotify":
        try:
            from winotify import Notification, audio
            # Truncate for toast (Windows limits)
            toast_msg = message[:250] if len(message) > 250 else message
            toast = Notification(
                app_id="Stream Monitor",
                title=title,
                msg=toast_msg,
                duration="short",
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except Exception as e:
            log.warning(f"Toast failed: {e}")
            print(f"  [{title}] {message}")
    else:
        print(f"  [{title}] {message}")


def email_alert(message: str, title: str = "Stream Monitor Alert", config: dict | None = None):
    """Send email alert via Xavier email bot API or direct SMTP.

    For jarvis (Linux): calls the local email bot API.
    Fallback: logs the alert.
    """
    if not config:
        log.debug("Email alert skipped: no email config")
        return

    api_url = config.get("api_url")
    if api_url:
        try:
            payload = json.dumps({
                "to": config.get("to", ""),
                "subject": title,
                "body": message,
            }).encode("utf-8")
            req = urllib.request.Request(
                api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    log.info(f"Email alert sent: {title}")
                else:
                    log.warning(f"Email alert failed: HTTP {resp.status}")
        except Exception as e:
            log.warning(f"Email alert failed: {e}")
    else:
        log.debug(f"Email alert (no API): [{title}] {message}")
