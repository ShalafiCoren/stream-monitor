"""System sensor: CPU, RAM, disk, processes, services via psutil."""

import platform
import psutil
from .base import BaseSensor


class SystemSensor(BaseSensor):

    name = "system"

    def __init__(self, config: dict):
        super().__init__(config)
        self._metrics = config.get("metrics", ["cpu", "ram", "disk", "processes"])
        self._watched_services = config.get("watched_services", [])
        self._top_n = config.get("top_processes", 5)
        self._disk_paths = config.get("disk_paths", self._auto_disk_paths())

    def _auto_disk_paths(self) -> dict[str, str]:
        if platform.system() == "Windows":
            paths = {}
            for p in psutil.disk_partitions(all=False):
                if p.fstype and "cdrom" not in p.opts.lower():
                    label = p.mountpoint.rstrip("\\").rstrip("/") or p.device
                    paths[label] = p.mountpoint
            return paths
        return {"/": "/", "/home": "/home"}

    def collect(self) -> dict:
        state = {}
        if "cpu" in self._metrics:
            state["cpu"] = self._collect_cpu()
        if "ram" in self._metrics:
            state["ram"] = self._collect_ram()
        if "disk" in self._metrics:
            state["disk"] = self._collect_disk()
        if "processes" in self._metrics:
            state["processes"] = self._collect_top_processes()
        if "services" in self._metrics and self._watched_services:
            state["services"] = self._collect_services()
        return state

    def _collect_cpu(self) -> dict:
        return {
            "percent": psutil.cpu_percent(interval=1),
            "freq_mhz": round(psutil.cpu_freq().current) if psutil.cpu_freq() else 0,
        }

    def _collect_ram(self) -> dict:
        mem = psutil.virtual_memory()
        return {
            "percent": mem.percent,
            "used_gb": round(mem.used / (1024**3), 1),
            "free_gb": round(mem.available / (1024**3), 1),
            "total_gb": round(mem.total / (1024**3), 1),
        }

    def _collect_disk(self) -> dict:
        disks = {}
        for label, path in self._disk_paths.items():
            try:
                usage = psutil.disk_usage(path)
                disks[label] = {
                    "percent": usage.percent,
                    "free_gb": round(usage.free / (1024**3), 1),
                    "total_gb": round(usage.total / (1024**3), 1),
                }
            except (PermissionError, FileNotFoundError):
                pass
        return disks

    def _collect_top_processes(self) -> list[dict]:
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
            try:
                info = p.info
                if info["memory_percent"] and info["memory_percent"] > 0.1:
                    procs.append({
                        "pid": info["pid"],
                        "name": info["name"],
                        "ram_pct": round(info["memory_percent"], 1),
                        "cpu_pct": round(info["cpu_percent"] or 0, 1),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x["ram_pct"], reverse=True)
        return procs[:self._top_n]

    def _collect_services(self) -> dict:
        services = {}
        if platform.system() == "Windows":
            for svc_name in self._watched_services:
                try:
                    svc = psutil.win_service_get(svc_name)
                    info = svc.as_dict()
                    services[svc_name] = {
                        "status": info["status"],
                        "pid": info.get("pid", 0),
                        "display": info.get("display_name", svc_name),
                    }
                except (psutil.NoSuchProcess, Exception):
                    services[svc_name] = {"status": "not_found", "pid": 0, "display": svc_name}
        else:
            # Linux: check systemd services
            import subprocess
            for svc_name in self._watched_services:
                try:
                    result = subprocess.run(
                        ["systemctl", "is-active", svc_name],
                        capture_output=True, text=True, timeout=5,
                    )
                    services[svc_name] = {
                        "status": result.stdout.strip() or "unknown",
                        "pid": 0,
                        "display": svc_name,
                    }
                except Exception:
                    services[svc_name] = {"status": "unknown", "pid": 0, "display": svc_name}
        return services
