"""Small, resilient system metrics helpers used by the dashboard."""

from __future__ import annotations

from pathlib import Path
import time

import psutil


def _read_number(path: Path, scale: float = 1.0) -> float | None:
    try:
        return int(path.read_text().strip()) / scale
    except (OSError, ValueError):
        return None


def _power_supply_metrics(root: Path | None = None) -> tuple[float | None, str | None]:
    """Return battery charge and reported supply draw where exposed by sysfs."""
    root = root or Path("/sys/class/power_supply")
    if not root.exists():
        return None, None

    battery_percent = None
    battery_power_watts = None
    external_power_watts = None
    battery_status = ""
    for supply in root.iterdir():
        try:
            kind = (supply / "type").read_text().strip()
        except OSError:
            continue
        if kind == "Battery":
            if battery_percent is None:
                battery_percent = _read_number(supply / "capacity")
            try:
                battery_status = (supply / "status").read_text().strip()
            except OSError:
                pass
            microwatts = _read_number(supply / "power_now", 1_000_000)
            if microwatts is not None:
                battery_power_watts = abs(microwatts)
        else:
            microwatts = _read_number(supply / "power_now", 1_000_000)
            if microwatts is not None:
                external_power_watts = abs(microwatts)
    power_watts = (
        battery_power_watts
        if battery_status == "Discharging" and battery_power_watts is not None
        else external_power_watts if external_power_watts is not None else battery_power_watts
    )
    power_label = f"{power_watts:.1f} W" if power_watts is not None else None
    return battery_percent, power_label


def snapshot() -> dict[str, object]:
    """Collect a point-in-time view; unavailable sensors are represented as None."""
    memory = psutil.virtual_memory()
    root = psutil.disk_usage(str(Path.home()))
    battery = psutil.sensors_battery()
    sysfs_battery, sysfs_power = _power_supply_metrics()

    temperatures = []
    try:
        for readings in psutil.sensors_temperatures(fahrenheit=False).values():
            temperatures.extend(item.current for item in readings if item.current > 0)
    except (AttributeError, OSError):
        pass

    return {
        "cpu": psutil.cpu_percent(interval=None),
        "memory": memory.percent,
        "memory_used": memory.used,
        "memory_total": memory.total,
        "disk": root.percent,
        "disk_used": root.used,
        "disk_total": root.total,
        "battery": battery.percent if battery else sysfs_battery,
        "charging": battery.power_plugged if battery else None,
        "power": sysfs_power,
        "temperature": max(temperatures) if temperatures else None,
        "processes": len(psutil.pids()),
        "uptime": max(0, int(time.time() - psutil.boot_time())),
    }


def format_bytes(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_uptime(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"