import csv
import re
from collections import defaultdict


def clean(value):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value or ""))


def rows(report):
    for node in report["nodes"]:
        for port in node["ports"]:
            for peer in port["neighbors"] or [{}]:
                yield {
                    "node": node["node"],
                    "hostname": node["hostname"],
                    "interface": port["interface"],
                    "mac": port["mac"],
                    "operstate": port["operstate"],
                    "carrier": port["carrier"],
                    "speed_mbps": port["speed_mbps"],
                    "master": port["master"],
                    "device": port["device"],
                    "is_vf": port["is_vf"],
                    "switch": peer.get("switch", ""),
                    "chassis_id": peer.get("chassis_id", ""),
                    "switch_port": peer.get("port", ""),
                    "port_description": peer.get("port_description", ""),
                    "management_ips": ";".join(peer.get("management_ips", [])),
                    "lldp_age": peer.get("age", ""),
                    "lldp_ttl": peer.get("ttl", ""),
                    "lldp_status": node["lldp_status"],
                }


def identity(row):
    return (
        ("id", row["chassis_id"])
        if row["chassis_id"]
        else ("fallback", row["switch"], row["management_ips"])
    )


def console(report):
    groups, missing = defaultdict(list), []
    for row in rows(report):
        if row["switch"] or row["chassis_id"]:
            groups[identity(row)].append(row)
        else:
            missing.append(row)
    lines = ["Etherlink | " + report["collected_at"]]
    for key in sorted(groups):
        group = groups[key]
        first = group[0]
        lines.append(
            "\n"
            + clean(first["switch"] or first["chassis_id"])
            + " ["
            + clean(first["chassis_id"])
            + "] "
            + clean(first["management_ips"])
        )
        for row in group:
            lines.append(
                "  "
                + clean(row["switch_port"])
                + " ── "
                + clean(row["node"])
                + ":"
                + clean(row["interface"])
                + status(row)
            )
    if missing:
        lines.append("\nNo LLDP neighbor (switch fields empty)")
        for row in missing:
            lines.append(
                "   ── "
                + clean(row["node"])
                + ":"
                + clean(row["interface"])
                + status(row)
            )
    for node in report["nodes"]:
        if not node["ports"]:
            lines.append(
                "\n" + clean(node["node"]) + ": no Ethernet interfaces collected"
            )
        for error in node["errors"]:
            lines.append("  WARNING " + clean(node["node"]) + ": " + clean(error))
    lines.append("\nLLDP is advertised neighbor data; empty does not mean unplugged.")
    return "\n".join(lines)


def status(row):
    speed = str(row["speed_mbps"]) + "Mb/s" if row["speed_mbps"] else "speed=?"
    return (
        " ["
        + clean(row["operstate"])
        + " "
        + speed
        + (" master=" + clean(row["master"]) if row["master"] else "")
        + "]"
    )


def write_csv(report, path):
    fields = [
        "node",
        "hostname",
        "interface",
        "mac",
        "operstate",
        "carrier",
        "speed_mbps",
        "master",
        "device",
        "is_vf",
        "switch",
        "chassis_id",
        "switch_port",
        "port_description",
        "management_ips",
        "lldp_age",
        "lldp_ttl",
        "lldp_status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows(report))


def svg(report):
    from html import escape

    all_rows = list(rows(report))
    groups = defaultdict(list)
    for row in all_rows:
        if row["switch"] or row["chassis_id"]:
            groups[identity(row)].append(row)
    longest = max(
        [40]
        + [len(clean(r["node"]) + clean(r["interface"]) + status(r)) for r in all_rows]
    )
    box_width = max(430, longest * 8 + 30)
    right = box_width + 420
    width = right + box_width + 30
    switch_slots, node_slots, boxes = {}, {}, []
    sy = ny = 100
    for key, group in sorted(groups.items()):
        height = 70 + 32 * len(group)
        first = group[0]
        labels = [
            first["switch"] or first["chassis_id"],
            first["chassis_id"] + " " + first["management_ips"],
        ]
        for index, row in enumerate(group):
            switch_slots[id(row)] = sy + 82 + index * 32
            labels.append(row["switch_port"] or "(port ID absent)")
        boxes.append((20, sy, height, labels, "#e6f1ff"))
        sy += height + 30
    by_node = defaultdict(list)
    for row in all_rows:
        by_node[row["node"]].append(row)
    for node in report["nodes"]:
        group = by_node[node["node"]]
        height = 70 + 32 * max(1, len(group))
        labels = [node["node"], node["hostname"]]
        for index, row in enumerate(group):
            node_slots[id(row)] = ny + 82 + index * 32
            labels.append(
                row["interface"]
                + status(row)
                + (
                    " LLDP: empty"
                    if not row["switch"] and not row["chassis_id"]
                    else ""
                )
            )
        if not group:
            labels.append("No interfaces collected")
        boxes.append((right, ny, height, labels, "#eef8ef"))
        ny += height + 30
    warnings = [
        n["node"] + ": " + error for n in report["nodes"] for error in n["errors"]
    ]
    height = max(sy, ny) + 50 + 24 * len(warnings)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="monospace" font-size="13">',
    ]

    def text(x, y, value, color="#16263b"):
        out.append(
            f'<text x="{x}" y="{y}" fill="{color}">{escape(clean(value))}</text>'
        )

    text(20, 28, "Etherlink — Ethernet / LLDP topology")
    text(20, 50, report["collected_at"] + " | empty LLDP does not mean unplugged")
    text(20, 78, "Advertised neighbors")
    text(right, 78, "Nodes / Ethernet interfaces")
    for row in all_rows:
        if id(row) not in switch_slots:
            continue
        a, b = switch_slots[id(row)] - 4, node_slots[id(row)] - 4
        color = "#27834a" if row["carrier"] == "1" else "#a36b28"
        x1 = 20 + box_width
        out.append(
            f'<path d="M{x1},{a} C{x1 + 140},{a} {right - 140},{b} {right},{b}" fill="none" stroke="{color}" stroke-width="1.5"/>'
        )
    for x, y, h, labels, color in boxes:
        out.append(
            f'<rect x="{x}" y="{y}" width="{box_width}" height="{h}" rx="8" fill="{color}" stroke="#94a6b8"/>'
        )
        for index, label in enumerate(labels):
            text(
                x + 12,
                y + (24 if index == 0 else 48 if index == 1 else 82 + (index - 2) * 32),
                label,
            )
    for index, warning in enumerate(warnings):
        text(20, max(sy, ny) + 22 + index * 24, warning, "#ad291e")
    out.append("</g></svg>")
    return "\n".join(out)
