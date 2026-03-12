"""Filesystem sensor: watches directories for file changes via watchdog."""

import logging
import os
import threading
from collections import deque
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .base import BaseSensor

log = logging.getLogger("stream-monitor")


class _EventCollector(FileSystemEventHandler):
    """Collects filesystem events into a thread-safe deque."""

    def __init__(self, max_events: int = 500):
        self._events: deque[dict] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def _record(self, event: FileSystemEvent, event_type: str):
        try:
            path = Path(event.src_path)
            size_mb = 0.0
            if event_type != "deleted" and path.exists() and path.is_file():
                try:
                    size_mb = round(path.stat().st_size / (1024 * 1024), 1)
                except OSError:
                    pass

            entry = {
                "type": event_type,
                "path": str(path),
                "filename": path.name,
                "dir": str(path.parent),
                "is_dir": event.is_directory,
                "size_mb": size_mb,
            }
            with self._lock:
                self._events.append(entry)
        except Exception:
            pass

    def on_created(self, event):
        self._record(event, "created")

    def on_deleted(self, event):
        self._record(event, "deleted")

    def on_modified(self, event):
        # Skip directory modified events (too noisy)
        if not event.is_directory:
            self._record(event, "modified")

    def on_moved(self, event):
        self._record(event, "moved")

    def drain(self) -> list[dict]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events


class FilesystemSensor(BaseSensor):

    name = "filesystem"
    mode = "event"

    def __init__(self, config: dict):
        super().__init__(config)
        self._paths = config.get("paths", [])
        self._ignore_patterns = config.get("ignore_patterns", [
            ".tmp", ".crdownload", "~$", ".swp", "Thumbs.db", "desktop.ini",
        ])
        self._collector = _EventCollector(max_events=config.get("max_events", 500))
        self._observer: Observer | None = None

    def start(self):
        if not self._paths:
            log.warning("[filesystem] No paths configured, sensor disabled")
            return

        self._observer = Observer()
        for path_str in self._paths:
            path = Path(path_str)
            if path.exists():
                recursive = True
                self._observer.schedule(self._collector, str(path), recursive=recursive)
                log.info(f"[filesystem] Watching: {path}")
            else:
                log.warning(f"[filesystem] Path not found, skipping: {path}")

        self._observer.daemon = True
        self._observer.start()

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)

    def collect(self) -> dict:
        events = self._collector.drain()

        # Filter out noisy/temp files
        filtered = [e for e in events if not self._is_ignored(e["filename"])]

        # Summarize
        summary = {
            "events_count": len(filtered),
            "created": sum(1 for e in filtered if e["type"] == "created"),
            "modified": sum(1 for e in filtered if e["type"] == "modified"),
            "deleted": sum(1 for e in filtered if e["type"] == "deleted"),
            "moved": sum(1 for e in filtered if e["type"] == "moved"),
            "events": filtered,
        }

        # Track largest new file
        created_files = [e for e in filtered if e["type"] == "created" and not e["is_dir"]]
        if created_files:
            largest = max(created_files, key=lambda e: e["size_mb"])
            summary["largest_new_file"] = largest["filename"]
            summary["largest_new_size_mb"] = largest["size_mb"]

        return summary

    def _is_ignored(self, filename: str) -> bool:
        lower = filename.lower()
        return any(pat.lower() in lower for pat in self._ignore_patterns)
