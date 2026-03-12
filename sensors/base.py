"""Base sensor class for Stream Monitor."""

from abc import ABC, abstractmethod
from typing import Any


class BaseSensor(ABC):
    """Abstract base for all sensors.

    Two modes:
      - "snapshot": collect() returns state dict, diff computed by engine
      - "event": collect() returns {"events": [...]} with accumulated events
    """

    mode: str = "snapshot"

    def __init__(self, config: dict):
        self._config = config
        self._parse_interval(config.get("interval", "30s"))

    def _parse_interval(self, interval: str | int | float):
        if isinstance(interval, (int, float)):
            self._interval = float(interval)
            return
        s = str(interval).strip().lower()
        if s.endswith("m"):
            self._interval = float(s[:-1]) * 60
        elif s.endswith("s"):
            self._interval = float(s[:-1])
        else:
            self._interval = float(s)

    @property
    def interval(self) -> float:
        return self._interval

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def collect(self) -> dict[str, Any]:
        """Collect current state or events."""
        ...

    def start(self):
        """Called once when daemon starts. Override for background threads."""
        pass

    def stop(self):
        """Called on shutdown. Override to clean up background threads."""
        pass
