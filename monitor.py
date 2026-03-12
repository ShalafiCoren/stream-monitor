"""Stream Monitor — Real-time system monitoring daemon.

Usage:
    python monitor.py                 # Run with default config
    python monitor.py --config x.yaml # Custom config
    python monitor.py --once          # Single pass (no loop)
    python monitor.py --debug         # Verbose logging
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

import yaml

from sensors.system import SystemSensor
from sensors.filesystem import FilesystemSensor
from sensors.web import WebSensor
from engine.diff import DiffEngine
from engine.rules import RuleEngine
from actions.notify import notify, email_alert
from actions.xavier import xavier_record
from actions.execute import restart_service, suggest_cleanup, enrich_message, get_top_processes

log = logging.getLogger("stream-monitor")


class StreamMonitor:

    def __init__(self, config_path: str):
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self._setup_logging()
        self.sensors = self._init_sensors()
        self.diff_engine = DiffEngine(self.config.get("thresholds"))
        self.rule_engine = RuleEngine(self.config.get("rules", []))
        self.previous_states: dict[str, dict] = {}
        self.running = True
        self.stats = {"cycles": 0, "alerts": 0, "records": 0}

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _setup_logging(self):
        log_cfg = self.config.get("logging", {})
        level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
        )

        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        log.addHandler(console)

        # File handler
        log_file = log_cfg.get("file")
        if log_file:
            log_path = Path(__file__).parent / log_file
            from logging.handlers import RotatingFileHandler
            max_bytes = log_cfg.get("max_mb", 10) * 1024 * 1024
            fh = RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=3, encoding="utf-8")
            fh.setFormatter(formatter)
            log.addHandler(fh)

        log.setLevel(level)

    def _init_sensors(self) -> dict:
        sensors = {}
        sc = self.config.get("sensors", {})
        if "system" in sc:
            sensors["system"] = SystemSensor(sc["system"])
            log.info(f"System sensor: interval={sc['system'].get('interval', '30s')}")
        if "filesystem" in sc:
            sensors["filesystem"] = FilesystemSensor(sc["filesystem"])
            log.info(f"Filesystem sensor: interval={sc['filesystem'].get('interval', '10s')}")
        if "web" in sc:
            sensors["web"] = WebSensor(sc["web"])
            log.info(f"Web sensor: interval={sc['web'].get('interval', '30s')}")
        # Start all sensors (for those with background threads)
        for sensor in sensors.values():
            sensor.start()
        return sensors

    def run_once(self):
        """Single collection pass — useful for testing."""
        log.info("=== Single pass ===")
        for name, sensor in self.sensors.items():
            state = sensor.collect()
            log.info(f"[{name}] State collected:")
            self._print_state(state)

            prev = self.previous_states.get(name)
            if prev:
                delta = self.diff_engine.compute(prev, state)
                if delta:
                    log.info(f"[{name}] Delta ({len(delta)} changes):")
                    for path, change in delta.items():
                        log.info(f"  {path}: {change}")
                    triggered = self.rule_engine.evaluate(state, delta)
                    for rule, message in triggered:
                        log.warning(f"  RULE '{rule['name']}': {message}")
                else:
                    log.info(f"[{name}] No significant changes")
            else:
                log.info(f"[{name}] First pass — baseline captured")
                # Still evaluate rules on first pass (absolute conditions)
                triggered = self.rule_engine.evaluate(state, {})
                for rule, message in triggered:
                    log.warning(f"  RULE '{rule['name']}': {message}")

            self.previous_states[name] = state

    def run(self):
        """Main daemon loop."""
        log.info("Stream Monitor started")
        log.info(f"Sensors: {list(self.sensors.keys())}")
        log.info(f"Rules: {len(self.config.get('rules', []))}")

        timers: dict[str, float] = {name: 0 for name in self.sensors}

        # First pass immediately
        self._cycle(timers, force=True)

        while self.running:
            self._cycle(timers)
            time.sleep(1)

        log.info(f"Shutdown. Stats: {self.stats}")

    def _cycle(self, timers: dict[str, float], force: bool = False):
        now = time.time()
        for name, sensor in self.sensors.items():
            if not force and (now - timers[name]) < sensor.interval:
                continue

            timers[name] = now
            self.stats["cycles"] += 1

            try:
                state = sensor.collect()
            except Exception as e:
                log.error(f"[{name}] Collection failed: {e}")
                continue

            if sensor.mode == "event":
                # Event sensors: evaluate rules on each collection with events
                events = state.get("events", [])
                if events:
                    log.debug(f"[{name}] {len(events)} events collected")
                    # Evaluate rules against the summary state
                    triggered = self.rule_engine.evaluate(state, {"events": True})
                    self._handle_triggers(triggered, state)
                    # Log individual events at debug level
                    for evt in events[:10]:  # Cap log output
                        log.debug(f"  [{name}] {evt['type']}: {evt.get('filename', evt.get('path', ''))}")
            else:
                # Snapshot sensors: diff against previous state
                prev = self.previous_states.get(name)
                if prev:
                    delta = self.diff_engine.compute(prev, state)
                    if delta:
                        log.debug(f"[{name}] {len(delta)} changes detected")
                        triggered = self.rule_engine.evaluate(state, delta)
                        self._handle_triggers(triggered, state)
                else:
                    # First pass: evaluate absolute rules
                    triggered = self.rule_engine.evaluate(state, {})
                    self._handle_triggers(triggered, state)

            self.previous_states[name] = state

    def _handle_triggers(self, triggered: list, state: dict):
        for rule, message in triggered:
            # Enrich message with context if configured
            if rule.get("enrich_processes") or rule.get("enrich_events"):
                message = enrich_message(message, state, rule)

            actions = rule.get("action", "alert")
            if isinstance(actions, str):
                actions = [actions]

            for action in actions:
                if action == "alert":
                    notify(message, title=f"Stream Monitor: {rule['name']}")
                    self.stats["alerts"] += 1

                elif action == "record":
                    category = rule.get("category", "other")
                    xavier_record(
                        f"[Stream Monitor] {message}",
                        category=category,
                    )
                    self.stats["records"] += 1

                elif action == "restart":
                    svc = rule.get("service")
                    if svc:
                        ok = restart_service(svc)
                        status = "OK" if ok else "FAILED"
                        notify(
                            f"Service '{svc}' restart: {status}",
                            title=f"Stream Monitor: auto-restart",
                        )

                elif action == "suggest_cleanup":
                    suggestions = suggest_cleanup()
                    notify(suggestions, title="Stream Monitor: cleanup suggestions")

                elif action == "top_processes":
                    report = get_top_processes(5)
                    notify(f"Top procesos por RAM:\n{report}", title="Stream Monitor: processes")

                elif action == "email":
                    email_cfg = self.config.get("email")
                    email_alert(message, title=f"Stream Monitor: {rule['name']}", config=email_cfg)

    def _print_state(self, state: dict, indent: int = 2):
        for key, val in state.items():
            prefix = " " * indent
            if isinstance(val, dict):
                log.info(f"{prefix}{key}:")
                self._print_state(val, indent + 2)
            elif isinstance(val, list):
                log.info(f"{prefix}{key}: [{len(val)} items]")
            else:
                log.info(f"{prefix}{key}: {val}")

    def _shutdown(self, signum, frame):
        log.info("Shutting down...")
        self.running = False
        for sensor in self.sensors.values():
            sensor.stop()


def main():
    parser = argparse.ArgumentParser(description="Stream Monitor — real-time system monitoring")
    parser.add_argument("--config", default=str(Path(__file__).parent / "config.yaml"))
    parser.add_argument("--once", action="store_true", help="Single pass, no loop")
    parser.add_argument("--debug", action="store_true", help="Debug logging")
    args = parser.parse_args()

    if args.debug:
        # Temporarily override before config loads
        logging.basicConfig(level=logging.DEBUG)

    monitor = StreamMonitor(args.config)

    if args.debug:
        log.setLevel(logging.DEBUG)

    if args.once:
        monitor.run_once()
    else:
        monitor.run()


if __name__ == "__main__":
    main()
