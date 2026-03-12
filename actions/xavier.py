"""Xavier integration: record actions to shared memory."""

import logging
import subprocess
import platform

log = logging.getLogger("stream-monitor")

XAVIER_DIR = r"C:\Users\Shalafi\Downloads\claude windows help"


def xavier_record(description: str, category: str = "other", agent: str = "ironman"):
    """Record an action in Xavier memory."""
    # Adapt path for Linux
    xavier_dir = XAVIER_DIR
    if platform.system() != "Windows":
        xavier_dir = "."  # Assume cwd or configure via env

    try:
        result = subprocess.run(
            ["python", "-m", "xavier", "record", description, "-c", category, "--agent", agent],
            cwd=xavier_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            log.info(f"Xavier recorded: {description[:80]}")
        else:
            log.warning(f"Xavier record failed: {result.stderr[:200]}")
    except Exception as e:
        log.warning(f"Xavier record error: {e}")
