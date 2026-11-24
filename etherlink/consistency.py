"""Compare observed local-interface to switch mappings within a neighbor group."""

import copy
from collections import Counter, defaultdict
from .port_slots import MIN_SUPPORT_PERCENT, MIN_VOTES, assess as assess_port_slots
from .render import identity, clean


def peer_key(peer):
    return identity(
        {
            "chassis_id": peer.get("chassis_id", ""),
            "switch": peer.get("switch", ""),
            "management_ips": ";".join(sorted(peer.get("management_ips", []))),
        }
    )


def profile(node, labels):
    mapping = {}
    switches = set()
    issues = []
    inventory = tuple(sorted(p["interface"] for p in node["ports"]))
    if not inventory:
        issues.append({"interface": "", "reason": "no matching interfaces"})
    if node["errors"]:
        issues.append({"interface": "", "reason": "collection error"})
    for port in node["ports"]:
        neighbors = {}
        for peer in port["neighbors"]:
            if not peer.get("chassis_id") and not peer.get("switch"):
                continue
            key = peer_key(peer)
            switches.add(key)
            labels.setdefault(
                key,
                {
                    "switch": peer.get("switch", ""),
                    "chassis_id": peer.get("chassis_id", ""),
                },
            )
            neighbors[key] = peer
        reason = ""
        if port["operstate"] != "up" or port["carrier"] != "1":
            reason = "link not UP; absent LLDP is normal for DOWN"
        elif not neighbors:
            reason = "UP interface without LLDP"
        elif len(neighbors) > 1:
            reason = "multiple distinct LLDP neighbor devices"
        if reason:
            issues.append({"interface": port["interface"], "reason": reason})
        if len(neighbors) == 1:
            mapping[port["interface"]] = next(iter(neighbors))
    return {
        "node": node["node"],
        "switches": tuple(sorted(switches)),
        "inventory": inventory,
        "signature": tuple(sorted(mapping.items())),
        "issues": issues,
    }


def majority(counter):
    if not counter:
        return None, 0, "insufficient"
    ranked = counter.most_common()
    key, count = ranked[0]
    if count < 2:
        return None, count, "insufficient" if len(ranked) == 1 else "ambiguous"
    if count * 2 <= sum(counter.values()):
        return None, count, "ambiguous"
    return key, count, "majority"


def analyze(report):
    output = copy.deepcopy(report)
    slot_checks = assess_port_slots(output["nodes"])
    labels = {}
    groups = defaultdict(list)
    for node in output["nodes"]:
        entry = profile(node, labels)
        groups[entry["switches"]].append(entry)
    assessments = {}
    results = []
    for number, (switches, entries) in enumerate(sorted(groups.items()), 1):
        group_id = f"group-{number:03}"
        complete = [p for p in entries if not p["issues"]]
        inventory, _, inventory_status = majority(
            Counter(p["inventory"] for p in complete)
        )
        comparable = [p for p in complete if p["inventory"] == inventory]
        signature, votes, reference_status = majority(
            Counter(p["signature"] for p in comparable)
        )
        expected = dict(signature or [])
        group = {
            "id": group_id,
            "switches": [labels[key] for key in switches],
            "nodes": [p["node"] for p in entries],
            "reference_status": reference_status
            if inventory is not None
            else inventory_status,
            "reference_votes": votes,
            "comparable_nodes": len(comparable),
            "reference": [
                {"interface": port, **labels[key]} for port, key in (signature or [])
            ],
            "patterns": [],
        }
        for pattern, count in Counter(p["signature"] for p in comparable).most_common():
            group["patterns"].append(
                {
                    "count": count,
                    "mapping": [
                        {"interface": port, **labels[key]} for port, key in pattern
                    ],
                }
            )
        group["interface_sets"] = [
            {"interfaces": list(inv), "count": count}
            for inv, count in Counter(p["inventory"] for p in complete).most_common()
        ]
        for entry in entries:
            item = {
                "group": group_id,
                "status": "",
                "differences": [],
                "reasons": entry["issues"],
                "interfaces": list(entry["inventory"]),
            }
            if entry["issues"]:
                item["status"] = "incomplete"
            elif inventory is None:
                item["status"] = inventory_status
            elif entry["inventory"] != inventory:
                item["status"] = "inventory_mismatch"
                item["reasons"] = [
                    {
                        "interface": "",
                        "reason": "interface names/count differ from majority inventory",
                    }
                ]
            elif signature is None:
                item["status"] = reference_status
            elif entry["signature"] == signature:
                item["status"] = "consistent"
            else:
                item["status"] = "mismatch"
                actual = dict(entry["signature"])
                item["differences"] = [
                    {
                        "interface": port,
                        "expected": labels[key],
                        "actual": labels[actual[port]],
                    }
                    for port, key in expected.items()
                    if actual[port] != key
                ]
            slot_check = slot_checks.get(entry["node"])
            if slot_check:
                item["slot_reference"] = {
                    "votes": slot_check["votes"],
                    "comparable_nodes": slot_check["comparable_nodes"],
                }
                diagnosed = {diff["interface"] for diff in item["differences"]}
                for diff in slot_check["differences"]:
                    if diff["interface"] not in diagnosed:
                        item["differences"].append(diff)
                        item["status"] = "mismatch"
            assessments[entry["node"]] = item
        states = Counter(assessments[p["node"]]["status"] for p in entries)
        group["counts"] = dict(states)
        group["status"] = next(
            (
                s
                for s in (
                    "mismatch",
                    "inventory_mismatch",
                    "incomplete",
                    "ambiguous",
                    "insufficient",
                )
                if states[s]
            ),
            "consistent",
        )
        results.append(group)
    for node in output["nodes"]:
        node["wiring"] = assessments[node["node"]]
    counts = Counter(item["status"] for item in assessments.values())
    output["wiring_check"] = {
        "method": "Exact observed neighbor set; strict majority among complete nodes with the majority interface inventory",
        "limits": (
            f"Slot references use complete dual links and require {MIN_VOTES} votes and "
            f"{MIN_SUPPORT_PERCENT}% support within a rack and switch pair. "
            "Inferred differences require cabling verification."
        ),
        "summary": {
            "groups": len(results),
            "slot_checked": len(slot_checks),
            "slot_mismatch": sum(bool(check["differences"]) for check in slot_checks.values()),
            **{
                s: counts[s]
                for s in (
                    "consistent",
                    "mismatch",
                    "incomplete",
                    "inventory_mismatch",
                    "ambiguous",
                    "insufficient",
                )
            },
        },
        "groups": results,
    }
    return output


def switch_label(device):
    name = device.get("switch", "")
    chassis = device.get("chassis_id", "")
    return (
        name + " [" + chassis + "]"
        if name and chassis
        else name or chassis or "(unknown)"
    )


def endpoint_label(endpoint):
    switch = switch_label(endpoint)
    port = endpoint.get("port")
    return f"{switch} / {port}" if port else switch


def _slot_note(diff, wiring):
    if diff.get("kind") != "port_slot":
        return ""
    reference = wiring["slot_reference"]
    return f" (inferred slot, {reference['votes']}/{reference['comparable_nodes']} nodes)"


def text_summary(report):
    if "wiring_check" not in report:
        report = analyze(report)
    check = report["wiring_check"]
    summary = check["summary"]
    lines = [
        "Wiring consistency | "
        + ", ".join(f"{key}={value}" for key, value in summary.items())
    ]
    for group in check["groups"]:
        names = (
            ", ".join(switch_label(s) for s in group["switches"])
            or "(no observed switch group)"
        )
        lines.append(
            f"  {group['id']} [{group['status']}] {len(group['nodes'])} nodes | "
            + clean(names)
        )
        if group["reference"]:
            lines.append(
                f"    Majority reference: {group['reference_votes']}/{group['comparable_nodes']} comparable nodes"
            )
            for row in group["reference"]:
                lines.append(
                    "      "
                    + clean(row["interface"])
                    + " -> "
                    + clean(switch_label(row))
                )
        else:
            lines.append(
                "    No usable majority reference: " + group["reference_status"]
            )
    for node in report["nodes"]:
        wiring = node["wiring"]
        if wiring["status"] == "consistent":
            continue
        lines.append("  " + clean(node["node"]) + ": " + wiring["status"])
        for diff in wiring["differences"]:
            lines.append(
                "    "
                + clean(diff["interface"])
                + ": expected "
                + clean(endpoint_label(diff["expected"]))
                + _slot_note(diff, wiring)
                + "; observed "
                + clean(endpoint_label(diff["actual"]))
            )
        for reason in wiring["reasons"]:
            lines.append(
                "    " + clean(reason["interface"]) + ": " + clean(reason["reason"])
            )
    return "\n".join(lines)


def html_summary(report):
    from html import escape

    if "wiring_check" not in report:
        report = analyze(report)
    check = report["wiring_check"]
    summary = check["summary"]

    def esc(value):
        return escape(clean(value), quote=True)

    parts = [
        '<section id="wiring"><h2>Wiring consistency</h2>',
        "<p>"
        + esc(", ".join(f"{key}: {value}" for key, value in summary.items()))
        + ". Reference is a strict group majority, not an approved cabling policy.</p>",
    ]
    for group in check["groups"]:
        names = (
            " / ".join(switch_label(s) for s in group["switches"])
            or "No observed switch group"
        )
        parts.append(
            "<h3>"
            + esc(group["id"] + " | " + group["status"])
            + "</h3><p>"
            + esc(names)
            + "</p>"
        )
        if group["reference"]:
            parts.append(
                "<p>Majority reference: "
                + esc(
                    str(group["reference_votes"]) + "/" + str(group["comparable_nodes"])
                )
                + " comparable nodes</p>"
            )
            parts.append(
                '<div class="table"><table><tr><th>Local interface</th><th>Reference neighbor</th></tr>'
            )
            for row in group["reference"]:
                parts.append(
                    "<tr><td>"
                    + esc(row["interface"])
                    + "</td><td>"
                    + esc(switch_label(row))
                    + "</td></tr>"
                )
            parts.append("</table></div>")
        else:
            parts.append(
                "<p>No usable majority: " + esc(group["reference_status"]) + "</p>"
            )
            for pattern in group["patterns"]:
                value = "; ".join(
                    r["interface"] + " -> " + switch_label(r)
                    for r in pattern["mapping"]
                )
                parts.append(
                    "<p>" + esc(str(pattern["count"]) + " nodes: " + value) + "</p>"
                )
    parts.append(
        '<h3>Differences and incomplete observations</h3><div class="table"><table><tr><th>Node</th><th>Status</th><th>Interface</th><th>Reference</th><th>Observed / reason</th></tr>'
    )
    for node in report["nodes"]:
        item = node["wiring"]
        if item["status"] == "consistent":
            continue
        link = '<a href="#node-' + esc(node["node"]) + '">' + esc(node["node"]) + "</a>"
        records = [
            (
                d["interface"],
                endpoint_label(d["expected"]) + _slot_note(d, item),
                endpoint_label(d["actual"]),
            )
            for d in item["differences"]
        ]
        records += [(r["interface"], "", r["reason"]) for r in item["reasons"]]
        for port, expected, observed in records or [
            ("", "", "No usable majority reference")
        ]:
            style = ' style="color:#b91c1c"' if item["status"] == "mismatch" else ""
            parts.append(
                "<tr"
                + style
                + "><td>"
                + link
                + "</td><td>"
                + esc(item["status"])
                + "</td><td>"
                + esc(port)
                + "</td><td>"
                + esc(expected)
                + "</td><td>"
                + esc(observed)
                + "</td></tr>"
            )
    parts.append(
        "</table></div><p>Inferred slot differences are reported with their reference votes. Different observed switch sets are checked separately.</p></section>"
    )
    return "\n".join(parts)
