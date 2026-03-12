"""Rule engine: evaluates YAML rules against current state."""

import operator
import time
from typing import Any

OPS = {
    ">=": operator.ge,
    "<=": operator.le,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
}


def resolve_field(path: str, state: dict) -> Any:
    """Navigate nested dict by dot path: 'ram.percent' -> state['ram']['percent']."""
    current = state
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def evaluate_condition(condition: str, state: dict) -> bool:
    """Evaluate a simple condition like 'ram.percent > 90'."""
    if " and " in condition:
        return all(evaluate_condition(c.strip(), state) for c in condition.split(" and "))
    if " or " in condition:
        return any(evaluate_condition(c.strip(), state) for c in condition.split(" or "))

    # Find operator
    for op_str in sorted(OPS, key=len, reverse=True):
        if op_str in condition:
            field_str, value_str = condition.split(op_str, 1)
            field_str = field_str.strip()
            value_str = value_str.strip()

            actual = resolve_field(field_str, state)
            if actual is None:
                return False

            # Parse value to match type
            value_str_clean = value_str.strip("'\"")
            try:
                target = float(value_str_clean)
            except ValueError:
                target = value_str_clean

            try:
                return OPS[op_str](actual, target)
            except TypeError:
                return False
    return False


def format_message(template: str, state: dict) -> str:
    """Format message template with state values: '{ram.percent}' -> '92.3'."""
    import re
    def replacer(m):
        val = resolve_field(m.group(1), state)
        return str(val) if val is not None else m.group(0)
    return re.sub(r"\{([^}]+)\}", replacer, template)


class RuleEngine:

    def __init__(self, rules: list[dict]):
        self._rules = rules
        self._cooldowns: dict[str, float] = {}  # rule_name -> last_fired_time
        self._parse_cooldowns()

    def _parse_cooldowns(self):
        for rule in self._rules:
            cd = rule.get("cooldown", "0s")
            if isinstance(cd, (int, float)):
                rule["_cooldown_secs"] = float(cd)
            else:
                s = str(cd).strip().lower()
                if s.endswith("h"):
                    rule["_cooldown_secs"] = float(s[:-1]) * 3600
                elif s.endswith("m"):
                    rule["_cooldown_secs"] = float(s[:-1]) * 60
                elif s.endswith("s"):
                    rule["_cooldown_secs"] = float(s[:-1])
                else:
                    rule["_cooldown_secs"] = 0

    def evaluate(self, state: dict, delta: dict) -> list[tuple[dict, str]]:
        """Evaluate all rules. Returns list of (rule, formatted_message) for triggered rules."""
        triggered = []
        now = time.time()

        for rule in self._rules:
            name = rule.get("name", "unnamed")
            condition = rule.get("condition", "")
            if not condition:
                continue

            # Check cooldown
            cooldown = rule.get("_cooldown_secs", 0)
            last_fired = self._cooldowns.get(name, 0)
            if cooldown and (now - last_fired) < cooldown:
                continue

            if evaluate_condition(condition, state):
                msg_tpl = rule.get("message", f"Rule '{name}' triggered")
                message = format_message(msg_tpl, state)
                triggered.append((rule, message))
                self._cooldowns[name] = now

        return triggered
