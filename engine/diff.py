"""Diff engine: computes meaningful deltas between two state snapshots."""

from typing import Any

# Default thresholds — ignore changes smaller than these
DEFAULT_THRESHOLDS = {
    "cpu.percent": 5.0,
    "ram.percent": 2.0,
    "ram.used_gb": 0.5,
    "ram.free_gb": 0.5,
    "disk.*.percent": 1.0,
    "disk.*.free_gb": 1.0,
}


class DiffEngine:

    def __init__(self, thresholds: dict | None = None):
        self._thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def compute(self, prev: dict, curr: dict) -> dict:
        """Compare two state dicts. Returns only meaningful changes."""
        delta = {}
        self._diff_recursive(prev, curr, delta, path="")
        return delta

    def _diff_recursive(self, prev: dict, curr: dict, delta: dict, path: str):
        all_keys = set(list(prev.keys()) + list(curr.keys()))
        for key in all_keys:
            full_path = f"{path}.{key}" if path else key
            old = prev.get(key)
            new = curr.get(key)

            if old is None and new is not None:
                delta[full_path] = {"type": "added", "value": new}
            elif old is not None and new is None:
                delta[full_path] = {"type": "removed", "value": old}
            elif isinstance(new, dict) and isinstance(old, dict):
                self._diff_recursive(old, new, delta, full_path)
            elif isinstance(new, list) and isinstance(old, list):
                if new != old:
                    delta[full_path] = {"type": "changed", "old": old, "new": new}
            elif isinstance(new, (int, float)) and isinstance(old, (int, float)):
                diff = new - old
                threshold = self._get_threshold(full_path)
                if abs(diff) >= threshold:
                    delta[full_path] = {
                        "type": "changed",
                        "old": old,
                        "new": new,
                        "diff": round(diff, 2),
                    }
            elif new != old:
                delta[full_path] = {"type": "changed", "old": old, "new": new}

    def _get_threshold(self, path: str) -> float:
        # Exact match first
        if path in self._thresholds:
            return self._thresholds[path]
        # Wildcard match: disk.*.percent matches disk.C:.percent
        parts = path.split(".")
        for pattern, value in self._thresholds.items():
            pparts = pattern.split(".")
            if len(pparts) == len(parts) and self._wildcard_match(pparts, parts):
                return value
        return 0.01  # Default: report nearly everything

    @staticmethod
    def _wildcard_match(pattern_parts: list, path_parts: list) -> bool:
        for pp, tp in zip(pattern_parts, path_parts):
            if pp != "*" and pp != tp:
                return False
        return True
