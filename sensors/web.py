"""Web sensor: monitors web pages via Pinchtab HTTP API with diff mode."""

import json
import logging
import urllib.request
import urllib.error

from .base import BaseSensor

log = logging.getLogger("stream-monitor")


class WebSensor(BaseSensor):

    name = "web"
    mode = "snapshot"

    def __init__(self, config: dict):
        super().__init__(config)
        self._base_url = config.get("pinchtab_url", "http://localhost:9867")
        self._watch_urls = config.get("watch_urls", [])
        self._available = False
        self._tab_ids: dict[str, str] = {}  # url -> tab_id

    def start(self):
        self._available = self._check_pinchtab()
        if self._available:
            log.info(f"[web] Pinchtab connected at {self._base_url}")
        else:
            log.info("[web] Pinchtab not running — sensor will retry each cycle")

    def collect(self) -> dict:
        if not self._available:
            self._available = self._check_pinchtab()
            if not self._available:
                return {"status": "offline", "tabs_count": 0, "tabs": {}}

        state = {"status": "online", "tabs": {}, "tabs_count": 0}

        try:
            tabs = self._get_tabs()
            state["tabs_count"] = len(tabs)

            for tab in tabs:
                tab_id = tab.get("id", "")
                tab_url = tab.get("url", "")
                tab_title = tab.get("title", "")

                # Only monitor watched URLs (or all if none specified)
                if self._watch_urls and not any(w in tab_url for w in self._watch_urls):
                    continue

                snapshot = self._get_snapshot(tab_id, diff=True)
                if snapshot:
                    text_len = len(snapshot.get("text", ""))
                    interactive_count = len(snapshot.get("interactive", []))
                    state["tabs"][tab_id] = {
                        "url": tab_url,
                        "title": tab_title,
                        "text_length": text_len,
                        "interactive_count": interactive_count,
                        "has_changes": bool(snapshot.get("diff", snapshot.get("nodes"))),
                    }
        except Exception as e:
            log.debug(f"[web] Collection error: {e}")
            self._available = False
            return {"status": "error", "tabs_count": 0, "tabs": {}}

        return state

    def _check_pinchtab(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._base_url}/tabs", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _get_tabs(self) -> list[dict]:
        try:
            req = urllib.request.Request(f"{self._base_url}/tabs")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return data if isinstance(data, list) else data.get("tabs", [])
        except Exception as e:
            log.debug(f"[web] Failed to get tabs: {e}")
            return []

    def _get_snapshot(self, tab_id: str, diff: bool = True) -> dict | None:
        try:
            url = f"{self._base_url}/tabs/{tab_id}/snapshot"
            if diff:
                url += "?filter=interactive&format=compact&diff=true"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            log.debug(f"[web] Snapshot failed for tab {tab_id}: {e}")
            return None
