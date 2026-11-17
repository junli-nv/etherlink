import csv
import re
from collections import defaultdict


def clean(value):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str("" if value is None else value))


def rows(report):
    for node in report["nodes"]:
        for port in sorted(
            node["ports"],
            key=lambda p: [
                int(v) if v.isdigit() else v for v in re.split(r"(\d+)", p["interface"])
            ],
        ):
            for peer in port["neighbors"] or [{}]:
                yield {
                    "node": node["node"],
                    "hostname": node["hostname"],
                    "interface": port["interface"],
                    "mac": port["mac"],
                    **{
                        key: port.get(key, "")
                        for key in (
                            "vendor_id",
                            "device_id",
                            "vendor_name",
                            "model",
                            "driver",
                        )
                    },
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
        recovery = node.get("lldp_recovery")
        if recovery:
            lines.append(
                "  LLDP recovery "
                + clean(node["node"])
                + ": "
                + clean(recovery.get("outcome", "attempted"))
                + " (one attempt)"
            )
        for warning in node.get("warnings", []):
            lines.append("  WARNING " + clean(node["node"]) + ": " + clean(warning))
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
        "vendor_id",
        "device_id",
        "vendor_name",
        "model",
        "driver",
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
    from .atlas import overview, node_diagram

    if len(report["nodes"]) == 1:
        return node_diagram(report["nodes"][0])
    return overview(report)
