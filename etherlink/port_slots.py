"""Infer per-side breakout port slots for compute trays in the same rack."""

import re
from collections import Counter, defaultdict

MIN_VOTES = 5
MIN_SUPPORT_PERCENT = 70
_RACK_SLOT = re.compile(r"(.+)-gpu-cp-([0-9]+)")
_PORT = re.compile(r"swp([0-9]+)s([01])", re.IGNORECASE)


def _profile(node):
    match = _RACK_SLOT.fullmatch(node["node"].lower())
    if not match or node["errors"] or len(node["ports"]) != 2:
        return None
    rack, slot_text = match.groups()
    slot = int(slot_text)
    if slot < 1:
        return None

    links = []
    for port in sorted(node["ports"], key=lambda item: item["interface"]):
        neighbors = port["neighbors"]
        if port["operstate"] != "up" or port["carrier"] != "1" or len(neighbors) != 1:
            return None
        neighbor = neighbors[0]
        chassis = neighbor.get("chassis_id", "").strip()
        observed = neighbor.get("port", "").strip()
        physical = _PORT.fullmatch(observed)
        if not chassis or not physical:
            return None
        front, lane = map(int, physical.groups())
        endpoint = {
            "switch": neighbor.get("switch", ""),
            "chassis_id": chassis,
            "port": observed,
        }
        links.append((port["interface"], 2 * front + lane, endpoint))

    if links[0][0] == links[1][0] or links[0][2]["chassis_id"] == links[1][2]["chassis_id"]:
        return None
    pair = tuple((interface, peer["chassis_id"]) for interface, _, peer in links)
    return (rack, pair), slot, links


def assess(nodes):
    """Return checks only where a single slot map meets the support threshold."""
    groups = defaultdict(list)
    for node in nodes:
        profile = _profile(node)
        if profile:
            group, slot, links = profile
            groups[group].append((node["node"], slot, links))

    checks = {}
    for members in groups.values():
        if len({slot for _, slot, _ in members}) != len(members):
            continue
        votes = Counter(
            tuple(index - slot for _, index, _ in links)
            for _, slot, links in members
        )
        offsets, count = votes.most_common(1)[0]
        if count < MIN_VOTES or 100 * count < MIN_SUPPORT_PERCENT * len(members):
            continue

        for name, slot, links in members:
            expected_indexes = [slot + offset for offset in offsets]
            if min(expected_indexes) < 2:
                continue
            differences = []
            for expected, (interface, actual, peer) in zip(expected_indexes, links):
                if expected == actual:
                    continue
                front, lane = divmod(expected, 2)
                differences.append(
                    {
                        "kind": "port_slot",
                        "interface": interface,
                        "expected": {**peer, "port": f"swp{front}s{lane}"},
                        "actual": peer,
                    }
                )
            checks[name] = {
                "votes": count,
                "comparable_nodes": len(members),
                "differences": differences,
            }
    return checks
