"""Sent over SSH and executed by the node's Python 3."""

import json
import shutil
import socket
import subprocess
from pathlib import Path


def items(value):
    return value if isinstance(value, list) else [value] if value else []


def parse_lldp(data):
    root = data.get("lldp", {})
    result = {}
    for block in items(root.get("interface")):
        if not isinstance(block, dict):
            raise ValueError("invalid LLDP interface object")
        for name, records in block.items():
            for record in items(records):
                if record.get("via", "LLDP") != "LLDP":
                    continue
                for chassis in items(record.get("chassis")):
                    for system_name, info in chassis.items():
                        for port in items(record.get("port")) or [{}]:
                            result.setdefault(name, []).append(
                                {
                                    "switch": system_name,
                                    "chassis_id": info.get("id", {}).get("value", ""),
                                    "management_ips": items(info.get("mgmt-ip")),
                                    "switch_description": info.get("descr", ""),
                                    "port": port.get("id", {}).get("value", ""),
                                    "port_description": port.get("descr", ""),
                                    "age": record.get("age", ""),
                                    "ttl": port.get("ttl", ""),
                                    "capabilities": info.get("capability", []),
                                }
                            )
    return result


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def interfaces(root=Path("/sys/class/net"), include_virtual=False):
    ports = []
    for p in sorted(root.iterdir()):
        if read(p / "type") != "1":
            continue
        physical = (p / "device").exists()
        if not physical and not include_virtual:
            continue
        speed = read(p / "speed")
        master = p / "master"
        ports.append(
            {
                "interface": p.name,
                "mac": read(p / "address"),
                "operstate": read(p / "operstate"),
                "carrier": read(p / "carrier"),
                "speed_mbps": int(speed)
                if speed.isdigit() and int(speed) > 0
                else None,
                "master": master.resolve().name if master.exists() else "",
                "device": (p / "device").resolve().name if physical else "",
                "physical": physical,
                "is_vf": (p / "device/physfn").exists(),
                "neighbors": [],
            }
        )
    return ports


def collect(include_virtual=False, sudo=False):
    report = {
        "hostname": socket.gethostname(),
        "ports": interfaces(include_virtual=include_virtual),
        "errors": [],
        "lldp_status": "unavailable",
    }
    binary = shutil.which("lldpcli")
    if not binary:
        for candidate in ("/usr/sbin/lldpcli", "/usr/local/sbin/lldpcli"):
            if Path(candidate).is_file():
                binary = candidate
                break
    if not binary:
        report["errors"].append("lldpcli not installed; no service was started")
        return report
    args = (["sudo", "-n"] if sudo else []) + [
        binary,
        "-f",
        "json",
        "show",
        "neighbors",
        "details",
    ]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
        if proc.returncode:
            raise RuntimeError(
                proc.stderr.strip() or "lldpcli exit " + str(proc.returncode)
            )
        neighbors = parse_lldp(json.loads(proc.stdout))
        for port in report["ports"]:
            port["neighbors"] = neighbors.get(port["interface"], [])
        report["lldp_status"] = "ok"
    except (
        OSError,
        ValueError,
        RuntimeError,
        AttributeError,
        TypeError,
        KeyError,
        subprocess.TimeoutExpired,
    ) as exc:
        report["errors"].append(str(exc))
    return report


if __name__ == "__main__":
    import sys

    print(json.dumps(collect("--include-virtual" in sys.argv, "--sudo" in sys.argv)))
