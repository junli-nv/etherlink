import copy
import io
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from unittest.mock import patch
from test_core import fixture, neighbor
from etherlink.selection import select, vendor_ids
from etherlink.atlas import document, overview, node_diagram
from etherlink.__main__ import main


def mixed():
    report = fixture()
    first = report["nodes"][0]["ports"][0]
    first.update(
        vendor_id="0x15b3", vendor_name="Mellanox", model="Test NIC", driver="mlx5_core"
    )
    other = copy.deepcopy(first)
    other.update(interface="intel0", vendor_id="0x8086", driver="i40e")
    report["nodes"][0]["ports"].append(other)
    return report


class SelectionTests(unittest.TestCase):
    def test_default_mellanox(self):
        result = select(mixed())
        self.assertEqual(len(result["nodes"][0]["ports"]), 1)
        self.assertEqual(result["nodes"][0]["ports"][0]["vendor_id"], "0x15b3")

    def test_multi_repeat_and_comma(self):
        for values in (["mellanox,intel"], ["mellanox", "intel"], ["15b3", "0x8086"]):
            self.assertEqual(len(select(mixed(), values)["nodes"][0]["ports"]), 2)

    def test_all_and_driver(self):
        self.assertEqual(len(select(mixed(), ["all"])["nodes"][0]["ports"]), 2)
        self.assertEqual(
            len(select(mixed(), ["all"], ["i40e"])["nodes"][0]["ports"]), 1
        )

    def test_unknown_and_legacy(self):
        with self.assertRaises(ValueError):
            vendor_ids(["unknown"])
        with self.assertRaises(ValueError):
            select(fixture())
        self.assertEqual(len(select(fixture(), ["all"])["nodes"][0]["ports"]), 1)

    def test_no_match_preserves_node(self):
        result = select(mixed(), ["broadcom"])
        self.assertEqual(len(result["nodes"]), 1)
        self.assertEqual(result["nodes"][0]["ports"], [])

    def test_no_mutation(self):
        original = mixed()
        before = copy.deepcopy(original)
        select(original)
        self.assertEqual(original, before)

    def test_cli_default_and_multi(self):
        for args, count in (
            ([], 1),
            (["--vendor", "mellanox,intel"], 2),
            (["--vendor", "all"], 2),
        ):
            with (
                patch("etherlink.__main__.scan", return_value=mixed()["nodes"]),
                redirect_stdout(io.StringIO()),
                patch("etherlink.__main__.console", return_value="") as render,
            ):
                self.assertEqual(main(["n01", "--no-restart-lldp", *args]), 0)
                self.assertEqual(
                    len(render.call_args[0][0]["nodes"][0]["ports"]), count
                )


class AtlasTests(unittest.TestCase):
    def test_overview_preserves_all_nodes(self):
        report = mixed()
        report["nodes"][0]["ports"][0]["neighbors"] = [neighbor()]
        other = copy.deepcopy(report["nodes"][0])
        other["node"] = "n02"
        other["ports"][0]["neighbors"] = []
        report["nodes"].append(other)
        image = overview(report)
        ET.fromstring(image)
        self.assertIn('href="#node-n01"', image)
        self.assertIn('href="#node-n02"', image)
        self.assertIn("LLDP not observed", image)

    def test_exact_links_and_blank(self):
        report = mixed()
        report["nodes"][0]["ports"][0]["neighbors"] = [neighbor()]
        image = node_diagram(report["nodes"][0])
        ET.fromstring(image)
        self.assertEqual(image.count("<path "), 1)
        self.assertIn("LLDP: empty", image)
        self.assertIn("Ethernet1/1", image)

    def test_html_escape_and_search(self):
        report = mixed()
        report["nodes"][0]["hostname"] = "<script>bad</script>"
        html = document(report)
        self.assertNotIn("<script>bad</script>", html)
        self.assertIn('id="search"', html)
        self.assertIn("<details", html)


class ZeroCountTests(unittest.TestCase):
    def test_zero_metrics_are_visible(self):
        root = ET.fromstring(overview(mixed()))
        texts = [
            node.text for node in root.findall(".//{http://www.w3.org/2000/svg}text")
        ]
        self.assertGreaterEqual(texts.count("0"), 2)
