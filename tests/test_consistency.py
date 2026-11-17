import copy
import unittest
from test_core import fixture
from etherlink.consistency import analyze, text_summary, html_summary

NORMAL = [1, 2, 1, 2]
SWAPPED = [2, 1, 1, 2]


def sample(patterns):
    report = {"schema_version": 1, "collected_at": "synthetic", "nodes": []}
    for i, pattern in enumerate(patterns):
        node = copy.deepcopy(fixture()["nodes"][0])
        node.update(node=f"n{i + 1:02}", hostname=f"n{i + 1:02}", ports=[])
        for j, target in enumerate(pattern):
            port = copy.deepcopy(fixture()["nodes"][0]["ports"][0])
            port.update(
                interface=f"eth{j}",
                physical=True,
                vendor_id="0x15b3",
                neighbors=[
                    {
                        "switch": f"leaf-{target}",
                        "chassis_id": f"id-{target}",
                        "management_ips": [],
                        "port": f"Ethernet1/{i * 4 + j + 1}",
                    }
                ],
            )
            node["ports"].append(port)
        report["nodes"].append(node)
    return report


class ConsistencyTests(unittest.TestCase):
    def test_only_swapped_ports_are_different(self):
        result = analyze(sample([NORMAL, NORMAL, SWAPPED]))
        self.assertEqual(result["wiring_check"]["summary"]["mismatch"], 1)
        diffs = result["nodes"][2]["wiring"]["differences"]
        self.assertEqual({d["interface"] for d in diffs}, {"eth0", "eth1"})
        self.assertEqual(diffs[0]["expected"]["chassis_id"], "id-1")

    def test_remote_port_numbers_may_differ(self):
        result = analyze(sample([NORMAL, NORMAL, NORMAL]))
        self.assertEqual(result["wiring_check"]["summary"]["consistent"], 3)

    def test_no_reference_on_tie_or_plurality(self):
        for patterns in (
            [NORMAL, NORMAL, SWAPPED, SWAPPED],
            [NORMAL, NORMAL, SWAPPED, [2, 1, 2, 1]],
        ):
            summary = analyze(sample(patterns))["wiring_check"]["summary"]
            self.assertEqual(summary["mismatch"], 0)
            self.assertEqual(summary["ambiguous"], 4)

    def test_single_node_is_insufficient(self):
        self.assertEqual(
            analyze(sample([NORMAL]))["nodes"][0]["wiring"]["status"], "insufficient"
        )

    def test_missing_and_down_are_not_miswired(self):
        for down in (False, True):
            report = sample([NORMAL, NORMAL, NORMAL])
            port = report["nodes"][2]["ports"][0]
            port["neighbors"] = []
            if down:
                port.update(operstate="down", carrier="0")
            result = analyze(report)
            self.assertEqual(result["nodes"][2]["wiring"]["status"], "incomplete")
            self.assertEqual(result["wiring_check"]["groups"][0]["reference_votes"], 2)

    def test_inventory_difference_is_separate(self):
        report = sample([NORMAL, NORMAL, NORMAL])
        report["nodes"][2]["ports"].pop()
        result = analyze(report)
        self.assertEqual(result["nodes"][2]["wiring"]["status"], "inventory_mismatch")
        self.assertEqual(result["wiring_check"]["summary"]["mismatch"], 0)

    def test_separate_switch_groups(self):
        result = analyze(sample([NORMAL, NORMAL, [3, 4, 3, 4], [3, 4, 3, 4]]))
        self.assertEqual(result["wiring_check"]["summary"]["groups"], 2)
        self.assertEqual(result["wiring_check"]["summary"]["consistent"], 4)

    def test_chassis_identity_is_not_system_name(self):
        report = sample([NORMAL, NORMAL, SWAPPED])
        for node in report["nodes"]:
            for port in node["ports"]:
                port["neighbors"][0]["switch"] = "same-name"
        self.assertEqual(analyze(report)["wiring_check"]["summary"]["mismatch"], 1)

    def test_no_mutation_and_visible_differences(self):
        from etherlink.atlas import overview, node_diagram

        report = sample([NORMAL, NORMAL, SWAPPED])
        before = copy.deepcopy(report)
        result = analyze(report)
        self.assertEqual(before, report)
        self.assertIn("expected", text_summary(result))
        self.assertIn('href="#node-n03"', html_summary(result))
        self.assertIn("WIRING DIFFERENT", overview(result))
        self.assertIn("Reference:", node_diagram(result["nodes"][2]))

    def test_help_starts_with_minimal_examples(self):
        import io
        from contextlib import redirect_stdout
        from etherlink.__main__ import main

        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as error:
            main(["--help"])
        self.assertEqual(error.exception.code, 0)
        self.assertIn("etherlink-cli 'node[01-08]'", out.getvalue())
        self.assertNotIn("--workers 8", out.getvalue())

    def test_csv_retains_expected_identity(self):
        import csv
        import tempfile
        from pathlib import Path
        from etherlink.render import write_csv

        result = analyze(sample([NORMAL, NORMAL, SWAPPED]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.csv"
            write_csv(result, path)
            with path.open() as stream:
                record = next(
                    r
                    for r in csv.DictReader(stream)
                    if r["node"] == "n03" and r["interface"] == "eth0"
                )
            self.assertEqual(record["expected_switch"], "leaf-1")
            self.assertEqual(record["expected_chassis_id"], "id-1")
