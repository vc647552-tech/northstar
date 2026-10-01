import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from northstar.system import _power_supply_metrics, format_bytes, format_uptime, snapshot


class SystemFormattingTests(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1536), "1.5 KB")
        self.assertEqual(format_bytes(1024**3), "1.0 GB")

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