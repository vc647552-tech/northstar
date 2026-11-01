"""Small, resilient system metrics helpers used by the dashboard."""

from __future__ import annotations

from pathlib import Path
import time

import psutil

_network_previous: tuple[float, dict[str, tuple[int, int]]] | None = None


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


def _gpu_metrics(root: Path | None = None) -> dict[str, object]:
    root = root or Path("/sys/class/drm")
    vendor_names = {
        "0x1002": "AMD",
        "0x10de": "NVIDIA",
        "0x8086": "Intel",
        "0x106b": "Apple",
    }
    names = []
    utilizations = []
    memory_used = 0
    memory_total = 0
    for card in sorted(root.glob("card[0-9]*")):
        device = card / "device"
        try:
            vendor_id = (device / "vendor").read_text().strip().lower()
        except OSError:
            continue
        vendor_name = vendor_names.get(vendor_id, "GPU")
        try:
            product_name = (device / "product_name").read_text().strip()
        except OSError:
            product_name = ""
        try:
            device_id = (device / "device").read_text().strip()
        except OSError:
            device_id = ""
        name = product_name or f"{vendor_name} GPU"
        if device_id and not product_name:
            name = f"{name} ({device_id})"
        names.append(name)

        utilization = _read_number(device / "gpu_busy_percent")
        if utilization is not None and 0 <= utilization <= 100:
            utilizations.append(utilization)
        used = _read_number(device / "mem_info_vram_used")
        total = _read_number(device / "mem_info_vram_total")
        if used is not None:
            memory_used += int(used)
        if total is not None:
            memory_total += int(total)

    return {
        "gpu_name": ", ".join(names) or None,
        "gpu_utilization": sum(utilizations) / len(utilizations) if utilizations else None,
        "gpu_memory_used": memory_used if memory_total else None,
        "gpu_memory_total": memory_total if memory_total else None,
    }


def _network_metrics() -> dict[str, object]:
    global _network_previous
    counters = psutil.net_io_counters(pernic=True) or {}
    stats = psutil.net_if_stats()
    active = {
        name: (counter.bytes_recv, counter.bytes_sent)
        for name, counter in counters.items()
        if name != "lo" and name in stats and stats[name].isup
    }
    now = time.monotonic()
    download_rate = 0.0
    upload_rate = 0.0
    if _network_previous is not None:
        previous_time, previous = _network_previous
        elapsed = now - previous_time
        if elapsed > 0:
            download_rate = sum(
                max(0, received - previous.get(name, (received, sent))[0])
                for name, (received, sent) in active.items()
            ) / elapsed
            upload_rate = sum(
                max(0, sent - previous.get(name, (received, sent))[1])
                for name, (received, sent) in active.items()
            ) / elapsed
    _network_previous = (now, active)
    return {
        "network_download": download_rate,
        "network_upload": upload_rate,
        "network_connected": bool(active),
        "network_interfaces": ", ".join(sorted(active)) or None,
    }


def snapshot() -> dict[str, object]:
    """Collect a point-in-time view; unavailable sensors are represented as None."""
    memory = psutil.virtual_memory()
    root = psutil.disk_usage(str(Path.home()))
    battery = psutil.sensors_battery()
    sysfs_battery, sysfs_power = _power_supply_metrics()
    frequency = psutil.cpu_freq()

    temperatures = []
    try:
        for readings in psutil.sensors_temperatures(fahrenheit=False).values():
            temperatures.extend(item.current for item in readings if item.current > 0)
    except (AttributeError, OSError):
        pass

    values = {
        "cpu": psutil.cpu_percent(interval=None),
        "cpu_cores": psutil.cpu_count(logical=True),
        "cpu_frequency": frequency.current if frequency else None,
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
    values.update(_gpu_metrics())
    values.update(_network_metrics())
    return values


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


def format_rate(bytes_per_second: float) -> str:
    return f"{format_bytes(int(bytes_per_second))}/s"