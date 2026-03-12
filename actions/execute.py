"""Auto-actions: restart services, cleanup suggestions, process reports."""

import logging
import os
import platform
import subprocess
from pathlib import Path

log = logging.getLogger("stream-monitor")


def restart_service(service_name: str) -> bool:
    """Restart a system service. Returns True on success."""
    log.info(f"AUTO-ACTION: Restarting service '{service_name}'")
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Restart-Service -Name '{service_name}' -Force; "
                 f"(Get-Service -Name '{service_name}').Status"],
                capture_output=True, text=True, timeout=30,
            )
            status = result.stdout.strip().split("\n")[-1]
            ok = status.lower() == "running"
        else:
            subprocess.run(
                ["sudo", "systemctl", "restart", service_name],
                capture_output=True, timeout=30,
            )
            result = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True, text=True, timeout=5,
            )
            ok = result.stdout.strip() == "active"

        if ok:
            log.info(f"Service '{service_name}' restarted successfully")
        else:
            log.error(f"Service '{service_name}' restart failed — not running after restart")
        return ok
    except Exception as e:
        log.error(f"Failed to restart '{service_name}': {e}")
        return False


def get_top_processes(n: int = 5) -> str:
    """Get top N processes by RAM usage as formatted string."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
            try:
                info = p.info
                if info["memory_percent"] and info["memory_percent"] > 0.5:
                    procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x["memory_percent"], reverse=True)
        lines = []
        for p in procs[:n]:
            lines.append(f"  {p['name']}: RAM {p['memory_percent']:.1f}% | CPU {p.get('cpu_percent', 0):.0f}%")
        return "\n".join(lines) if lines else "  (no processes found)"
    except Exception as e:
        return f"  (error: {e})"


def suggest_cleanup() -> str:
    """Scan common temp/cache locations and suggest cleanup targets. Does NOT delete anything."""
    targets = []
    temp_dirs = []

    if platform.system() == "Windows":
        temp_dirs = [
            (os.environ.get("TEMP", ""), "User Temp"),
            ("C:\\Windows\\Temp", "Windows Temp"),
            (str(Path.home() / "AppData/Local/Temp"), "AppData Temp"),
            (str(Path.home() / ".cache"), "User Cache"),
        ]
    else:
        temp_dirs = [
            ("/tmp", "System Temp"),
            (str(Path.home() / ".cache"), "User Cache"),
            ("/var/log", "System Logs"),
        ]

    for dir_path, label in temp_dirs:
        if not dir_path or not os.path.exists(dir_path):
            continue
        try:
            total_size = 0
            file_count = 0
            for root, dirs, files in os.walk(dir_path):
                for f in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, f))
                        file_count += 1
                    except OSError:
                        pass
                # Don't go too deep
                if root.count(os.sep) - dir_path.count(os.sep) > 2:
                    dirs.clear()
            size_mb = total_size / (1024 * 1024)
            if size_mb > 50:  # Only report if >50MB
                targets.append(f"  {label} ({dir_path}): {size_mb:.0f} MB en {file_count} archivos")
        except (PermissionError, OSError):
            pass

    if targets:
        return "Candidatos para limpieza:\n" + "\n".join(targets)
    return "No se encontraron candidatos significativos para limpieza"


def enrich_message(message: str, state: dict, rule: dict) -> str:
    """Add context to alert messages based on rule type and current state."""
    enrichments = []

    # If system state has processes, add top consumers
    processes = state.get("processes")
    if processes and rule.get("enrich_processes", False):
        top3 = processes[:3] if isinstance(processes, list) else []
        if top3:
            proc_lines = [f"  {p['name']}: RAM {p['ram_pct']}%" for p in top3]
            enrichments.append("Top procesos:\n" + "\n".join(proc_lines))

    # If filesystem events, add recent files
    events = state.get("events")
    if events and isinstance(events, list):
        recent = events[:5]
        if recent:
            evt_lines = [f"  {e['type']}: {e['filename']} ({e.get('size_mb', 0)} MB)" for e in recent]
            enrichments.append("Ultimos eventos:\n" + "\n".join(evt_lines))

    if enrichments:
        return message + "\n" + "\n".join(enrichments)
    return message
