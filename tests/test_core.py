import io
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from etherlink.hosts import expand, compact, main as hosts_main
from etherlink.probe import parse_lldp, interfaces, collect
from etherlink.collector import scan_one
from etherlink.render import rows, console, svg


def fixture():
    port = dict(
        interface="eth0",
        mac="00:11:22:33:44:55",
        operstate="up",
        carrier="1",
        speed_mbps=25000,
        master="",
        device="0000:01:00.0",
        is_vf=False,
        neighbors=[],
    )
    return {
        "schema_version": 1,
        "collected_at": "test",
        "nodes": [
            dict(node="n01", hostname="n01", ports=[port], lldp_status="ok", errors=[])
        ],
    }


def neighbor(switch="switch-a", chassis="aa"):
    return {
        "switch": switch,
        "chassis_id": chassis,
        "port": "Ethernet1/1",
        "management_ips": ["192.0.2.1"],
    }


class HostsTests(unittest.TestCase):
    def test_expand(self):
        self.assertEqual(
            expand("n[001-003,007],gpu9"), ["n001", "n002", "n003", "n007", "gpu9"]
        )

    def test_multi_dimensions(self):
        self.assertEqual(expand("r[1-2]n[01-02]"), ["r1n01", "r1n02", "r2n01", "r2n02"])

    def test_invalid(self):
        for value in ["n[3-1]", "n[1", "n1]", "n[]", "-x", "n;id", "n[1,,2]", "n[[1]]"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                expand(value)

    def test_limit(self):
        for value in ["n[1-100]", "r[1-3]n[1-3]"]:
            with self.assertRaises(ValueError):
                expand(value, 5)

    def test_roundtrip(self):
        for names in [
            ["n001", "n002", "n003", "n007"],
            ["n1", "n01", "n001"],
            ["r1n01", "r2n02"],
            ["n9", "n10", "n11"],
            ["host"],
        ]:
            self.assertEqual(set(expand(compact(names))), set(names))

    def test_compact(self):
        self.assertEqual(compact(["n003", "n001", "n002", "n007"]), "n[001-003,007]")

    def test_standalone(self):
        out = io.StringIO()
        with redirect_stdout(out):
            hosts_main(["-c", "n01", "n02"])
        self.assertEqual(out.getvalue(), "n[01-02]\n")


class ProbeTests(unittest.TestCase):
    def test_lldp_shapes(self):
        record = {
            "via": "LLDP",
            "chassis": {"s": {"id": {"value": "aa"}, "mgmt-ip": ["192.0.2.1", "::1"]}},
            "port": {"id": {"value": "p1"}},
        }
        for interfaces_value in [
            {"eth0": record},
            [{"eth0": record}],
            {"eth0": [record, record]},
        ]:
            result = parse_lldp({"lldp": {"interface": interfaces_value}})
            self.assertEqual(result["eth0"][0]["port"], "p1")
        self.assertEqual(parse_lldp({"lldp": {}}), {})

    def test_filter_protocol(self):
        self.assertEqual(parse_lldp({"lldp": {"interface": {"e": {"via": "CDP"}}}}), {})

    def test_missing_binary(self):
        with (
            patch("etherlink.probe.interfaces", return_value=[]),
            patch("etherlink.probe.shutil.which", return_value=None),
            patch.object(Path, "is_file", return_value=False),
        ):
            self.assertEqual(collect()["lldp_status"], "unavailable")

    def test_sysfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, kind, physical in [
                ("eth0", "1", True),
                ("ib0", "32", True),
                ("veth0", "1", False),
            ]:
                p = root / name
                p.mkdir()
                (p / "type").write_text(kind)
                if physical:
                    (p / "device").mkdir()
            self.assertEqual([p["interface"] for p in interfaces(root)], ["eth0"])

    def test_ssh_failure(self):
        with patch(
            "etherlink.collector.subprocess.run",
            return_value=subprocess.CompletedProcess([], 255, "", "denied"),
        ):
            self.assertIn("denied", scan_one("n01")["errors"][0])


class RenderTests(unittest.TestCase):
    def test_missing_port_retained(self):
        self.assertEqual(list(rows(fixture()))[0]["switch"], "")
        self.assertIn("n01:eth0", console(fixture()))

    def test_multiple_and_escape(self):
        report = fixture()
        report["nodes"][0]["ports"][0]["neighbors"] = [
            neighbor("<x&>"),
            neighbor("s2", "bb"),
        ]
        self.assertEqual(len(list(rows(report))), 2)
        image = svg(report)
        ET.fromstring(image)
        self.assertIn("&lt;x&amp;&gt;", image)
        self.assertEqual(image.count("<path "), 2)


class IntegrationTests(unittest.TestCase):
    def test_remote_timeout(self):
        with patch(
            "etherlink.collector.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ssh", 1),
        ):
            self.assertTrue(scan_one("n01")["errors"])

    def test_bad_json_keeps_ports(self):
        with (
            patch(
                "etherlink.probe.interfaces",
                return_value=[{"interface": "e", "neighbors": []}],
            ),
            patch("etherlink.probe.shutil.which", return_value="/usr/sbin/lldpcli"),
            patch(
                "etherlink.probe.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "[]", ""),
            ),
        ):
            report = collect()
            self.assertEqual(len(report["ports"]), 1)
            self.assertTrue(report["errors"])

    def test_no_name_mode_in_main_tool(self):
        from etherlink.__main__ import main

        with (
            patch("sys.stderr", new=io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            main(["--compact", "n01"])
        self.assertEqual(error.exception.code, 2)
