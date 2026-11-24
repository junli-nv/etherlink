import unittest

from etherlink.atlas import node_diagram
from etherlink.consistency import analyze, html_summary, text_summary
from etherlink.render import rows
from test_consistency import sample


def rack(size, side_offsets=(20, 20)):
    report = sample([[1, 2]] * size)
    for slot, node in enumerate(report["nodes"], 1):
        node["node"] = f"rack-a-gpu-cp-{slot:02}"
        for offset, port in zip(side_offsets, node["ports"]):
            front, lane = divmod(offset + slot - 1, 2)
            port["neighbors"][0]["port"] = f"swp{front}s{lane}"
    return report


class PortSlotTests(unittest.TestCase):
    def test_single_lane_mismatch_visible_in_reports(self):
        report = rack(6)
        report["nodes"][2]["ports"][0]["neighbors"][0]["port"] = "swp11s1"
        result = analyze(report)
        node = result["nodes"][2]
        wiring = node["wiring"]
        self.assertEqual(result["wiring_check"]["summary"]["slot_checked"], 6)
        self.assertEqual(result["wiring_check"]["summary"]["slot_mismatch"], 1)
        self.assertEqual(wiring["status"], "mismatch")
        self.assertEqual(wiring["slot_reference"], {"votes": 5, "comparable_nodes": 6})
        diff, = wiring["differences"]
        self.assertEqual(diff["kind"], "port_slot")
        self.assertEqual(diff["interface"], "eth0")
        self.assertEqual(diff["actual"]["port"], "swp11s1")
        self.assertEqual(diff["expected"]["port"], "swp11s0")
        self.assertIn("inferred slot, 5/6 nodes", text_summary(result))
        self.assertIn("inferred slot, 5/6 nodes", html_summary(result))
        self.assertIn("Reference: swp11s0", node_diagram(node))
        expected_row = next(row for row in rows(result) if row["node"] == node["node"])
        self.assertEqual(expected_row["expected_switch_port"], "swp11s0")

    def test_both_links_can_be_on_the_same_wrong_slot(self):
        report = rack(6)
        for port in report["nodes"][2]["ports"]:
            port["neighbors"][0]["port"] = "swp11s1"
        result = analyze(report)
        self.assertEqual(len(result["nodes"][2]["wiring"]["differences"]), 2)

    def test_consistent_asymmetric_layout_is_valid(self):
        result = analyze(rack(6, side_offsets=(20, 32)))
        summary = result["wiring_check"]["summary"]
        self.assertEqual(summary["slot_checked"], 6)
        self.assertEqual(summary["slot_mismatch"], 0)

    def test_reference_at_or_above_seventy_percent(self):
        for size, outliers in ((7, 2), (10, 3)):
            report = rack(size)
            for index in range(outliers):
                report["nodes"][index]["ports"][0]["neighbors"][0]["port"] = "swp25s1"
            summary = analyze(report)["wiring_check"]["summary"]
            self.assertEqual(summary["slot_checked"], size)
            self.assertEqual(summary["slot_mismatch"], outliers)

    def test_weak_reference_and_incomplete_links(self):
        weak = rack(8)
        for index in (2, 3, 4):
            weak["nodes"][index]["ports"][0]["neighbors"][0]["port"] = "swp25s1"
        self.assertEqual(analyze(weak)["wiring_check"]["summary"]["slot_checked"], 0)

        incomplete = rack(6)
        incomplete["nodes"][2]["ports"][0].update(operstate="down", carrier="0")
        result = analyze(incomplete)
        self.assertEqual(result["wiring_check"]["summary"]["slot_checked"], 5)
        self.assertEqual(result["nodes"][2]["wiring"]["status"], "incomplete")
        self.assertNotIn("slot_reference", result["nodes"][2]["wiring"])
