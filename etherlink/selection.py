"""Select NIC vendors by numeric PCI identity, never by interface name."""

import copy
import re

VENDORS = {
    "mellanox": "0x15b3",
    "nvidia": "0x15b3",
    "intel": "0x8086",
    "broadcom": "0x14e4",
    "realtek": "0x10ec",
    "amazon": "0x1d0f",
}


def vendor_ids(values=None):
    names = [
        name.strip().lower()
        for value in (values or ["mellanox"])
        for name in value.split(",")
    ]
    if "all" in names:
        return None
    result = set()
    for name in names:
        if name in VENDORS:
            result.add(VENDORS[name])
        elif re.fullmatch(r"(?:0x)?[0-9a-f]{4}", name):
            result.add("0x" + name.removeprefix("0x"))
        else:
            raise ValueError(
                "Unknown vendor: " + name + "; use a vendor name, PCI ID, or all"
            )
    return result


def select(report, values=None, drivers=None):
    selected = vendor_ids(values)
    output = copy.deepcopy(report)
    output["selection"] = {
        "vendors": sorted(selected) if selected is not None else "all",
        "drivers": drivers or [],
    }
    for node in output["nodes"]:
        original = node["ports"]
        if selected is not None and any("vendor_id" not in p for p in original):
            raise ValueError(
                "Saved report lacks PCI vendor metadata; collect again or use --vendor all"
            )
        node["unfiltered_port_count"] = node.get("unfiltered_port_count", len(original))
        node["ports"] = [
            p
            for p in original
            if (selected is None or p.get("vendor_id") in selected)
            and (not drivers or p.get("driver") in drivers)
        ]
    return output
