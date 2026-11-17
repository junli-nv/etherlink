import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def scan_one(host, timeout=25, include_virtual=False, sudo=False):
    script = Path(__file__).with_name("probe.py").read_text()
    flags = (["--include-virtual"] if include_virtual else []) + (
        ["--sudo"] if sudo else []
    )
    if host == "local":
        argv = [sys.executable, "-", *flags]
    else:
        argv = [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "ConnectionAttempts=1",
            "--",
            host,
            "python3 - " + " ".join(flags),
        ]
    try:
        proc = subprocess.run(
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode:
            raise RuntimeError(
                proc.stderr.strip() or "remote exit " + str(proc.returncode)
            )
        report = json.loads(proc.stdout)
        if not isinstance(report, dict) or not isinstance(report.get("ports"), list):
            raise ValueError("unexpected node response")
        report["node"] = host
        return report
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {
            "node": host,
            "hostname": "",
            "ports": [],
            "lldp_status": "unavailable",
            "errors": [str(exc)],
        }


def scan(hosts, workers=8, **kwargs):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda host: scan_one(host, **kwargs), hosts))
