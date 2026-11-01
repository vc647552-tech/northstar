import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from northstar.system import (
    _gpu_metrics,
    _network_metrics,
    _power_supply_metrics,
    format_bytes,
    format_rate,
    format_uptime,
    snapshot,
)


class SystemFormattingTests(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1536), "1.5 KB")
        self.assertEqual(format_bytes(1024**3), "1.0 GB")
        self.assertEqual(format_rate(1536), "1.5 KB/s")

    def test_format_uptime(self):
        self.assertEqual(format_uptime(59), "0m")
        self.assertEqual(format_uptime(3661), "1h 1m")
        self.assertEqual(format_uptime(90061), "1d 1h 1m")

    def test_snapshot_has_required_metrics(self):
        values = snapshot()
        self.assertTrue(0 <= values["cpu"] <= 100)
        self.assertTrue(0 <= values["memory"] <= 100)
        self.assertGreater(values["memory_total"], 0)
        self.assertGreaterEqual(values["processes"], 1)
        self.assertGreaterEqual(values["uptime"], 0)
        self.assertTrue(values["battery"] is None or 0 <= values["battery"] <= 100)
        self.assertIn("gpu_name", values)
        self.assertIn("gpu_utilization", values)
        self.assertGreaterEqual(values["network_download"], 0)
        self.assertGreaterEqual(values["network_upload"], 0)
        self.assertIn("disk_total", values)

    def test_gpu_metrics_read_sysfs_telemetry(self):
        with TemporaryDirectory() as directory:
            device = Path(directory) / "card0" / "device"
            device.mkdir(parents=True)
            (device / "vendor").write_text("0x1002\n")
            (device / "device").write_text("0x744c\n")
            (device / "product_name").write_text("AMD Radeon Test\n")
            (device / "gpu_busy_percent").write_text("43\n")
            (device / "mem_info_vram_used").write_text(str(1024**3))
            (device / "mem_info_vram_total").write_text(str(8 * 1024**3))

            values = _gpu_metrics(Path(directory))

        self.assertEqual(values["gpu_name"], "AMD Radeon Test")
        self.assertEqual(values["gpu_utilization"], 43)
        self.assertEqual(values["gpu_memory_used"], 1024**3)
        self.assertEqual(values["gpu_memory_total"], 8 * 1024**3)

    def test_network_metrics_calculate_per_second_rates(self):
        samples = [
            {"eth0": SimpleNamespace(bytes_recv=1000, bytes_sent=500)},
            {"eth0": SimpleNamespace(bytes_recv=1200, bytes_sent=560)},
        ]
        with (
            patch("northstar.system._network_previous", None),
            patch("northstar.system.psutil.net_io_counters", side_effect=samples),
            patch("northstar.system.psutil.net_if_stats", return_value={"eth0": SimpleNamespace(isup=True)}),
            patch("northstar.system.time.monotonic", side_effect=(10.0, 12.0)),
        ):
            _network_metrics()
            values = _network_metrics()

        self.assertEqual(values["network_download"], 100)
        self.assertEqual(values["network_upload"], 30)
        self.assertTrue(values["network_connected"])
        self.assertEqual(values["network_interfaces"], "eth0")

    def test_battery_power_is_used_during_discharge(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            battery = root / "BAT0"
            adapter = root / "AC"
            battery.mkdir()
            adapter.mkdir()
            (battery / "type").write_text("Battery\n")
            (battery / "capacity").write_text("71\n")
            (battery / "status").write_text("Discharging\n")
            (battery / "power_now").write_text("8500000\n")
            (adapter / "type").write_text("Mains\n")
            (adapter / "power_now").write_text("12000000\n")

            self.assertEqual(_power_supply_metrics(root), (71, "8.5 W"))


if __name__ == "__main__":
    unittest.main()