import copy
import io
import subprocess
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from unittest.mock import patch
from test_selection_atlas import mixed
from test_core import neighbor
from etherlink.recovery import recover, missing_up, restart_one
from etherlink.atlas import node_diagram
from etherlink.__main__ import main


class RecoveryTests(unittest.TestCase):
    def test_down_and_virtual_and_vf_not_candidates(self):
        node = mixed()["nodes"][0]
        for port in node["ports"]:
            port["operstate"] = "down"
        self.assertEqual(missing_up(node), [])
        for port in node["ports"]:
            port.update(operstate="up", physical=False)
        self.assertEqual(missing_up(node), [])
        for port in node["ports"]:
            port.update(physical=True, is_vf=True)
        self.assertEqual(missing_up(node), [])

    def test_still_missing_stops_after_one_restart_and_recheck(self):
        before = mixed()
        before["nodes"][0]["ports"].append(
            dict(before["nodes"][0]["ports"][0], interface="eth2")
        )
        with (
            patch(
                "etherlink.recovery.restart_one", return_value={"returncode": 0}
            ) as restart,
            patch(
                "etherlink.recovery.scan_one",
                return_value=copy.deepcopy(before["nodes"][0]),
            ) as scan,
            patch("etherlink.recovery.time.sleep") as sleep,
            patch("sys.stderr", new=io.StringIO()),
        ):
            after = recover(before)
            again = recover(after)
        restart.assert_called_once()
        scan.assert_called_once()
        sleep.assert_called_once_with(5)
        self.assertEqual(after["nodes"][0]["lldp_recovery"]["outcome"], "still_missing")
        self.assertEqual(again, after)

    def test_success_and_failure_recorded_without_retry(self):
        before = mixed()
        refreshed = copy.deepcopy(before["nodes"][0])
        refreshed["ports"][0]["neighbors"] = [neighbor()]
        for code, outcome in [(0, "recovered"), (1, "restart_failed")]:
            with (
                patch(
                    "etherlink.recovery.restart_one",
                    return_value={"returncode": code, "stderr": "test"},
                ) as restart,
                patch(
                    "etherlink.recovery.scan_one", return_value=copy.deepcopy(refreshed)
                ),
                patch("etherlink.recovery.time.sleep"),
                patch("sys.stderr", new=io.StringIO()),
            ):
                after = recover(before)
            self.assertEqual(after["nodes"][0]["lldp_recovery"]["outcome"], outcome)
            restart.assert_called_once()

    def test_default_live_cli_calls_recovery(self):
        with (
            patch("etherlink.__main__.scan", return_value=mixed()["nodes"]),
            patch(
                "etherlink.__main__.recover", side_effect=lambda report, *a, **k: report
            ) as recovery,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(["n01"]), 0)
        recovery.assert_called_once()

    def test_transport_timeout_is_not_retried(self):
        with patch(
            "etherlink.recovery.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ssh", 1),
        ) as run:
            result = restart_one("n01", timeout=1)
        run.assert_called_once()
        self.assertIsNone(result["returncode"])


class HostViewTests(unittest.TestCase):
    def test_host_order_not_switch_order_and_down_is_explicit(self):
        node = mixed()["nodes"][0]
        base = node["ports"][0]
        node["ports"] = [
            dict(base, interface="eth10", neighbors=[neighbor("a", "aa")]),
            dict(base, interface="eth2", neighbors=[], operstate="down", carrier="0"),
            dict(base, interface="eth1", neighbors=[neighbor("z", "zz")]),
        ]
        root = ET.fromstring(node_diagram(node))
        texts = root.findall(".//{http://www.w3.org/2000/svg}text")
        positions = {
            t.text: float(t.attrib["y"])
            for t in texts
            if t.text in ("eth1", "eth2", "eth10")
        }
        self.assertLess(positions["eth1"], positions["eth2"])
        self.assertLess(positions["eth2"], positions["eth10"])
        self.assertTrue(any((t.text or "").startswith("DOWN") for t in texts))
        self.assertTrue(any("normal for DOWN" in (t.text or "") for t in texts))


class OfflineTests(unittest.TestCase):
    def test_saved_input_never_recovers(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(mixed()))
            with (
                patch("etherlink.__main__.recover") as recovery,
                patch("etherlink.__main__.scan") as scan,
            ):
                self.assertEqual(main(["--input", str(path), "--quiet"]), 0)
            recovery.assert_not_called()
            scan.assert_not_called()
