"""Dependency-free topology atlas: overview SVG and expandable port diagrams."""

import json
import math
from collections import defaultdict
from html import escape
from .render import clean, identity, rows
from .hosts import compact
from .consistency import analyze, html_summary

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
    if "wiring_check" not in report:
        report = analyze(report)
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
            wiring = node.get("wiring", {})
            known = sum(bool(p["neighbors"]) for p in node["ports"])
            up = sum(p["carrier"] == "1" for p in node["ports"])
            color = (
                "#b91c1c"
                if wiring.get("status") == "mismatch"
                else "#d97706"
                if up and not known
                else "#64748b"
                if not known
                else "#2563eb"
            )
            name = escape(clean(node["node"]), quote=True)
            c.parts.append(f'<a href="#node-{name}">')
            c.rect(
                nx,
                ny,
                128,
                46,
                "#fff1f2"
                if wiring.get("status") == "mismatch"
                else "#fffbeb"
                if up and not known
                else "#f8fafc",
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
                    else "WIRING DIFFERENT"
                    if wiring.get("status") == "mismatch"
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
        + str(report.get("selection", {}).get("vendors", "all"))
        + " | Wiring: "
        + str(report["wiring_check"]["summary"]["consistent"])
        + " consistent, "
        + str(report["wiring_check"]["summary"]["mismatch"])
        + " different",
        12,
        "#64748b",
    )
    return c.finish()


def node_diagram(node, devices=None, colors=None):
    devices = devices or peers({"nodes": [node]})
    colors = colors or {
        key: COLORS[i % len(COLORS)] for i, key in enumerate(sorted(devices))
    }
    differences = {
        d["interface"]: d for d in node.get("wiring", {}).get("differences", [])
    }
    ports = sorted(node["ports"], key=lambda p: natural(p["interface"]))
    source_y = {p["interface"]: 180 + i * 64 for i, p in enumerate(ports)}
    known = {}
    for port in ports:
        for row in rows({"nodes": [dict(node, ports=[port])]}):
            if row["switch"] or row["chassis_id"]:
                known.setdefault(identity(row), []).append(row)
    target_y = {}
    boxes = []
    top = 124
    for key, group in known.items():
        height = 64 + len(group) * 44
        boxes.append((key, group, top, height))
        for i, row in enumerate(group):
            target_y[id(row)] = top + 72 + i * 44
        top += height + 20
    height = max(260, 180 + len(ports) * 64, top + 20)
    c = Canvas(1280, height)
    c.text(26, 38, node["node"], 24, weight=700)
    if node.get("wiring"):
        c.text(
            650,
            38,
            "Wiring: " + node["wiring"]["status"],
            14,
            "#b91c1c" if node["wiring"]["status"] == "mismatch" else "#64748b",
            700,
        )
    c.text(26, 62, "Host view | local interface order is fixed", 12, "#64748b")
    c.rect(26, 88, 456, height - 116)
    c.text(44, 116, "LOCAL PHYSICAL PORT / LINK STATE", 12, "#64748b", 700)
    for port in ports:
        y = source_y[port["interface"]]
        speed = (
            str(port["speed_mbps"] // 1000) + "G"
            if port["speed_mbps"]
            else "speed unknown"
        )
        if port["interface"] in differences:
            c.rect(36, y - 22, 436, 52, "#fff1f2", "#fecdd3", 6)
            expected = differences[port["interface"]]["expected"]
            c.text(
                170,
                y + 20,
                "Reference: "
                + (expected.get("port") or expected.get("switch") or expected.get("chassis_id", "")),
                9,
                "#b91c1c",
            )
        c.text(
            44,
            y,
            port["interface"],
            14,
            "#b91c1c" if port["interface"] in differences else "#172b4d",
            weight=600,
        )
        c.text(44, y + 20, port["operstate"].upper() + "  " + speed, 11, "#64748b")
        if not port["neighbors"]:
            c.text(
                520,
                y,
                "LLDP: empty"
                + (
                    " (normal for DOWN)"
                    if port["operstate"] == "down"
                    else " (UP: needs checking)"
                ),
                12,
                "#64748b" if port["operstate"] == "down" else "#a16207",
            )
    for key, group, top, h in boxes:
        dev = devices[key]
        c.rect(836, top, 418, h, "white", colors[key], 10)
        c.text(850, top + 24, dev["switch"] or dev["chassis_id"], 13, colors[key], 700)
        c.text(850, top + 44, dev["management_ips"] or dev["chassis_id"], 11, "#64748b")
        for row in group:
            sy = source_y[row["interface"]] - 4
            ty = target_y[id(row)] - 4
            c.path(f"M482,{sy} C610,{sy} 708,{ty} 836,{ty}", colors[key], 2.5)
            c.text(
                850,
                ty + 4,
                row["switch_port"] or "(port ID absent)",
                14,
                colors[key],
                600,
            )
    if not ports:
        c.text(44, 160, "No matching Ethernet interfaces collected", 14, "#64748b")
    return c.finish()


def document(report):
    if "wiring_check" not in report:
        report = analyze(report)
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
        html_summary(report),
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
        recovery = node.get("lldp_recovery")
        if recovery:
            out.append(
                '<div class="warn">LLDP recovery: '
                + escape(clean(recovery.get("outcome", "attempted")))
                + " | one restart, one recheck</div>"
            )
        for error in node["errors"] + node.get("warnings", []):
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
