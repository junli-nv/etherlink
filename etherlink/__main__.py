import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from .collector import DEFAULT_WORKERS, scan
from .hosts import expand
from .selection import select, vendor_ids
from .recovery import recover
from .consistency import analyze
from .render import console, svg, write_csv


def main(argv=None):
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Ethernet topology and same-group wiring consistency check.

Quick start:
  ./etherlink-cli 'node[01-08]'
  ./etherlink-cli 'node[01-08]' --html topology.html

Defaults: Mellanox NICs; automatic wiring checks; one LLDP recovery when needed.
LLDP recovery is limited to one restart, a 5-second wait and one recheck.""",
        epilog="""Optional: --vendor all includes every NIC vendor.
Save data: --json links.json
Offline: ./etherlink-cli --input links.json --html topology.html""",
    )
    p.add_argument(
        "nodes",
        nargs="*",
        help="SSH hosts or quoted Slurm-style ranges; 'local' probes this machine",
    )
    p.add_argument(
        "--nodes-file", type=Path, help="one expression per line; # comments allowed"
    )
    p.add_argument("--input", type=Path, help="render a saved JSON report without SSH")
    p.add_argument("--limit", type=int, default=4096)
    p.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help="parallel workers across nodes (default: %(default)s; range: 1..128)",
    )
    p.add_argument(
        "--timeout", type=float, default=25, help="per-node total timeout in seconds"
    )
    p.add_argument("--sudo", action="store_true", help="use sudo -n for lldpcli only")
    p.add_argument(
        "--include-virtual",
        action="store_true",
        help="include virtual Ethernet devices",
    )
    p.add_argument("--json", type=Path, dest="json_path")
    p.add_argument("--csv", type=Path)
    p.add_argument("--svg", type=Path)
    p.add_argument("--quiet", action="store_true", help="suppress console topology")
    p.add_argument(
        "--vendor",
        action="append",
        help="comma-separated/repeatable PCI vendors; default: mellanox; all",
    )
    p.add_argument(
        "--driver", action="append", help="optional driver allowlist, repeatable"
    )
    p.add_argument("--html", type=Path, help="standalone searchable topology atlas")
    p.add_argument(
        "--no-restart-lldp",
        action="store_true",
        help="disable automatic one-time LLDP recovery (live collection only)",
    )
    args = p.parse_args(argv)
    if (
        not 1 <= args.workers <= 128
        or not 0 < args.timeout <= 3600
        or not 1 <= args.limit <= 100000
    ):
        p.error("workers: 1..128; timeout: (0,3600]; limit: 1..100000")
    try:
        vendor_ids(args.vendor)
        expressions = list(args.nodes)
        if args.nodes_file:
            expressions += [
                line.split("#", 1)[0].strip()
                for line in args.nodes_file.read_text().splitlines()
                if line.split("#", 1)[0].strip()
            ]
        if args.input and expressions:
            p.error("--input cannot be combined with node expressions")
        hosts = []
        for expression in expressions:
            hosts.extend(expand(expression, args.limit))
            if len(hosts) > args.limit:
                raise ValueError("total host expansion exceeds limit")
        hosts = list(dict.fromkeys(hosts))
        if args.input:
            report = json.loads(args.input.read_text())
            if report.get("schema_version") != 1:
                raise ValueError("unsupported report schema")
        else:
            if not hosts:
                p.error("provide nodes, --nodes-file or --input")
            report = {
                "schema_version": 1,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "nodes": scan(
                    hosts,
                    workers=args.workers,
                    timeout=args.timeout,
                    include_virtual=args.include_virtual,
                    sudo=args.sudo,
                ),
            }
        if not args.input and not args.no_restart_lldp:
            report = recover(
                report,
                args.vendor,
                args.driver,
                workers=args.workers,
                timeout=args.timeout,
                include_virtual=args.include_virtual,
                sudo=args.sudo,
            )
        report = analyze(select(report, args.vendor, args.driver))
        if args.html:
            from .atlas import document

            args.html.write_text(document(report), encoding="utf-8")
        if args.json_path:
            args.json_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n"
            )
        if args.csv:
            write_csv(report, args.csv)
        if args.svg:
            args.svg.write_text(svg(report), encoding="utf-8")
        if not args.quiet:
            print(console(report))
        return 1 if any(node["errors"] for node in report["nodes"]) else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.exit(2, "etherlink: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
