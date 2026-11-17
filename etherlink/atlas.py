"""Dependency-free topology atlas: overview SVG and expandable port diagrams."""

import json
import math
from collections import defaultdict
from html import escape
from .render import clean, identity, rows
from .hosts import compact

COLORS = ["#2563eb", "#0d9488", "#7c3aed", "#d97706", "#db2777", "#0284c7"]


def natural(value):
    import re

    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", value)]


def peers(report):
    result = {}
    for row in rows(report):
        if row["switch"] or row["chassis_id"]:
            result.setdefault(identity(row), row)
    return result


class Canvas:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#f4f7fc"/>',
            '<g font-family="DejaVu Sans,Arial,sans-serif">',
        ]

    def rect(self, x, y, w, h, fill="white", stroke="#dbe3ef", radius=12):
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}"/>'
        )

    def text(self, x, y, value, size=14, color="#172b4d", weight=400):
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(clean(value))}</text>'
        )

    def path(self, d, color="#2563eb", width=2):
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
        )

    def finish(self):
        return "\n".join(self.parts + ["</g></svg>"])


def grouping(report):
    all_peers = peers(report)
    groups = defaultdict(list)
    for node in report["nodes"]:
        keys = set()
        for port in node["ports"]:
            for neighbor in port["neighbors"]:
                row = {
                    "chassis_id": neighbor.get("chassis_id", ""),
                    "switch": neighbor.get("switch", ""),
                    "management_ips": ";".join(neighbor.get("management_ips", [])),
                }
                if row["switch"] or row["chassis_id"]:
                    keys.add(identity(row))
        groups[tuple(sorted(keys))].append(node)
    return all_peers, sorted(
        groups.items(), key=lambda pair: (not bool(pair[0]), pair[0])
    )


def overview(report):
    devices, groups = grouping(report)
    ports = [p for n in report["nodes"] for p in n["ports"]]
    colors = {key: COLORS[i % len(COLORS)] for i, key in enumerate(sorted(devices))}
    blocks = []
    y = 246
    for index in range(0, len(groups), 2):
        pair = groups[index : index + 2]
        columns = 5 if len(pair) == 2 else 10
        panel_width = 744 if len(pair) == 2 else 1520
        h = max(
            170 + math.ceil(len(nodes) / columns) * 56 + math.ceil(len(keys) / 2) * 92
            for keys, nodes in pair
        )
        for column, (keys, nodes) in enumerate(pair):
            blocks.append((32 + column * 776, y, panel_width, h, keys, nodes))
        y += h + 24
    c = Canvas(1600, y + 82)
    c.text(32, 48, "ETHERNET / LLDP", 14, "#4f6381", 700)
    c.text(32, 88, "Observed network topology", 32, weight=700)
    c.text(
        32,
        116,
        compact([n["node"] for n in report["nodes"]])[:140]
        + " | "
        + report["collected_at"],
        13,
        "#64748b",
    )
    metrics = [
        (len(report["nodes"]), "NODES SCANNED"),
        (len(devices), "NEIGHBOR DEVICES"),
        (sum(len(p["neighbors"]) for p in ports), "LLDP LINKS"),
        (sum(not p["neighbors"] for p in ports), "PORTS WITHOUT LLDP"),
    ]
    for i, (value, label) in enumerate(metrics):
        x = 32 + i * 388
        c.rect(x, 140, 364, 82)
        c.text(x + 18, 175, value, 28, weight=700)
        c.text(x + 18, 202, label, 12, "#64748b", 600)
    for x, top, w, h, keys, nodes in blocks:
        c.rect(x, top, w, h)
        title = (
            "LLDP not observed" if not keys else f"Neighbor group / {len(keys)} devices"
        )
        c.text(x + 20, top + 32, title, 18, weight=700)
        c.text(
            x + 20,
            top + 55,
            f"{len(nodes)} nodes | same observed neighbor set",
            12,
            "#64748b",
        )
        for i, key in enumerate(keys):
            sx = x + 20 + (i % 2) * 352
            sy = top + 72 + (i // 2) * 92
            dev = devices[key]
            c.rect(sx, sy, 336, 76, "#f8fbff", colors[key], 8)
            c.text(
                sx + 12,
                sy + 24,
                dev["switch"] or dev["chassis_id"],
                12,
                colors[key],
                700,
            )
            c.text(
                sx + 12,
                sy + 45,
                dev["management_ips"] or dev["chassis_id"],
                11,
                "#64748b",
            )
            links = sum(
                1
                for row in rows({"nodes": nodes})
                if (row["switch"] or row["chassis_id"]) and identity(row) == key
            )
            c.text(
                sx + 12,
                sy + 64,
                f"{links} observed port links to this group",
                11,
                colors[key],
            )
        start = top + 88 + math.ceil(len(keys) / 2) * 92
        if keys:
            for i, key in enumerate(keys):
                sx = x + 188 + (i % 2) * 352
                sy = top + 148 + (i // 2) * 92
                c.path(f"M{sx},{sy} V{start + 4} H{x + w / 2}", colors[key], 3)
            c.path(f"M{x + w / 2},{start + 4} V{start + 20}", "#94a3b8", 2)
        c.text(
            x + 20,
            start + 44,
            "Aggregated connections above; click a node in HTML for exact port wiring."
            if keys
            else "No switch inferred. Link-UP ports still have empty neighbor fields.",
            10,
            "#64748b",
        )
        start += 60
        for index, node in enumerate(sorted(nodes, key=lambda n: natural(n["node"]))):
            columns = 5 if w == 744 else 10
            nx = x + 20 + (index % columns) * 140
            ny = start + (index // columns) * 56
            known = sum(bool(p["neighbors"]) for p in node["ports"])
            up = sum(p["carrier"] == "1" for p in node["ports"])
            color = (
                "#d97706" if up and not known else "#64748b" if not known else "#2563eb"
            )
            name = escape(clean(node["node"]), quote=True)
            c.parts.append(f'<a href="#node-{name}">')
            c.rect(
                nx,
                ny,
                128,
                46,
                "#fffbeb" if up and not known else "#f8fafc",
                "#e2e8f0",
                7,
            )
            c.text(nx + 9, ny + 19, node["node"], 12, weight=700)
            c.text(
                nx + 9,
                ny + 36,
                (
                    "COLLECTION ERROR"
                    if node["errors"]
                    else "NO MATCHING NICS"
                    if not node["ports"]
                    else f"{known}/{len(node['ports'])} LLDP | {up} UP"
                ),
                10,
                color,
            )
            c.parts.append("</a>")
    c.text(
        32,
        y + 22,
        "Only observed LLDP is drawn. Group lines are aggregated; no switch-to-switch links are inferred.",
        13,
        "#64748b",
    )
    c.text(
        32,
        y + 46,
        "PCI vendor selection: "
        + str(report.get("selection", {}).get("vendors", "all")),
        12,
        "#64748b",
    )
    return c.finish()


def node_diagram(node, devices=None, colors=None):
    report = {"nodes": [node]}
    devices = devices or peers(report)
    colors = colors or {
        key: COLORS[i % len(COLORS)] for i, key in enumerate(sorted(devices))
    }
    known, missing = defaultdict(list), []
    for row in rows(report):
        if row["switch"] or row["chassis_id"]:
            known[identity(row)].append(row)
        else:
            missing.append(row)
    ordered = [row for key in sorted(known) for row in known[key]] + missing
    height = 150 + max(1, len(ordered)) * 48 + len(known) * 64
    c = Canvas(1280, height)
    c.text(26, 38, node["node"], 24, weight=700)
    c.text(26, 62, "Exact port mapping | advertised LLDP neighbors", 12, "#64748b")
    c.rect(26, 88, 456, height - 116)
    c.text(44, 116, "LOCAL ETHERNET PORT", 12, "#64748b", 700)
    y = 144
    for key, group in sorted(known.items()):
        dev = devices[key]
        c.rect(836, y - 8, 418, 56 + len(group) * 48, "#ffffff", colors[key], 10)
        c.text(850, y + 14, dev["switch"] or dev["chassis_id"], 13, colors[key], 700)
        c.text(850, y + 34, dev["management_ips"] or dev["chassis_id"], 11, "#64748b")
        y += 64
        for row in group:
            label = (
                row["interface"]
                + "  "
                + (str(row["speed_mbps"] // 1000) + "G" if row["speed_mbps"] else "?")
            )
            c.text(44, y, label, 14, weight=600)
            c.text(
                850, y, row["switch_port"] or "(port ID absent)", 14, colors[key], 600
            )
            c.path(
                f"M482,{y - 5} C610,{y - 5} 708,{y - 5} 836,{y - 5}", colors[key], 2.5
            )
            y += 48
    for row in missing:
        c.text(44, y, row["interface"], 14, weight=600)
        c.text(
            520,
            y,
            "LLDP: empty | "
            + row["operstate"]
            + (
                " | " + str(row["speed_mbps"] // 1000) + "G"
                if row["speed_mbps"]
                else ""
            ),
            13,
            "#a16207",
        )
        y += 48
    if not ordered:
        c.text(44, 160, "No matching Ethernet interfaces collected", 14, "#64748b")
    return c.finish()


def document(report):
    devices = peers(report)
    colors = {key: COLORS[i % len(COLORS)] for i, key in enumerate(sorted(devices))}
    out = [
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">',
        "<title>Etherlink | Observed topology</title>",
        """<style>
body{margin:0;background:#f4f7fc;color:#172b4d;font:15px system-ui,Arial}
header{position:sticky;top:0;z-index:2;background:#10233f;color:white;padding:16px 24px;display:flex;gap:24px;align-items:center}
input{padding:12px;border:0;border-radius:8px;min-width:320px;font:inherit}
main{max-width:1600px;margin:auto;padding:20px}svg{width:100%;height:auto;display:block}
h2{margin:26px 0 8px}details{background:white;border:1px solid #dbe3ef;border-radius:12px;margin:12px 0;scroll-margin-top:90px;overflow:hidden}
summary{padding:18px;cursor:pointer;font-weight:650}summary span{font-weight:400;color:#64748b;margin-left:18px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px 14px;border-bottom:1px solid #edf1f7;text-align:left}
th{background:#f8fafc;color:#64748b}.table{overflow:auto}.warn{padding:12px;color:#a16207}
p{line-height:1.6;color:#64748b}a{color:inherit}
@media print{header{position:static}details{break-inside:avoid}input{display:none}}
</style>""",
        '<header><b>ETHERLINK</b><input id="search" placeholder="Search node / interface / switch / model" aria-label="Search"><span id="count"></span></header><main>',
        overview(report),
        "<h2>Exact port wiring</h2><p>Click a node above or expand a row below. Blank switch fields mean no LLDP neighbor was observed, not a disconnected cable.</p>",
    ]
    fields = (
        "interface",
        "vendor_name",
        "model",
        "driver",
        "operstate",
        "speed_mbps",
        "switch",
        "switch_port",
    )
    for node in sorted(report["nodes"], key=lambda n: natural(n["node"])):
        name = escape(clean(node["node"]), quote=True)
        data = json.dumps(node, ensure_ascii=False).lower()
        known = sum(bool(p["neighbors"]) for p in node["ports"])
        out.append(
            f'<details id="node-{name}" data-search="{escape(data, quote=True)}"><summary>{name}<span>{known}/{len(node["ports"])} ports with LLDP</span></summary>'
        )
        out.append(node_diagram(node, devices, colors))
        out.append(
            '<div class="table"><table><thead><tr>'
            + "".join("<th>" + f + "</th>" for f in fields)
            + "</tr></thead><tbody>"
        )
        for row in rows({"nodes": [node]}):
            out.append(
                "<tr>"
                + "".join(
                    "<td>" + escape(clean(row.get(f, ""))) + "</td>" for f in fields
                )
                + "</tr>"
            )
        out.append("</tbody></table></div>")
        for error in node["errors"]:
            out.append('<div class="warn">' + escape(clean(error)) + "</div>")
        out.append("</details>")
    out.append("""<script>
const search=document.getElementById('search'), cards=[...document.querySelectorAll('details')];
function filter(){let n=0;for(const c of cards){c.hidden=!c.dataset.search.includes(search.value.toLowerCase());if(!c.hidden)n++}document.getElementById('count').textContent=n+' nodes'}
search.addEventListener('input',filter);
document.addEventListener('click',event=>{const a=event.target.closest('a[href^="#node-"]');if(!a)return;const id=a.getAttribute('href').slice(1),c=document.getElementById(id);if(c){event.preventDefault();search.value='';filter();c.open=true;c.scrollIntoView({behavior:'smooth',block:'start'})}});
filter();
</script></main></html>""")
    return "\n".join(out)
