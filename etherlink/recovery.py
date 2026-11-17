"""One bounded LLDP restart per eligible node; never an open-ended retry."""

import copy
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from .collector import scan_one
from .selection import select


def missing_up(node):
    return [
        p["interface"]
        for p in node["ports"]
        if p.get("physical", True)
        and not p.get("is_vf", False)
        and p["operstate"] == "up"
        and p["carrier"] == "1"
        and not p["neighbors"]
    ]


def restart_one(host, timeout=25):
    remote_timeout = max(0.1, min(12, timeout - 2))
    script = f"""
import json, os, subprocess
command=["systemctl","--no-ask-password","restart","lldpd.service"]
if os.geteuid()!=0:
    command=["sudo","-n"]+command
try:
    p=subprocess.run(command,capture_output=True,text=True,timeout={remote_timeout!r})
    result={{"returncode":p.returncode,"stdout":p.stdout,"stderr":p.stderr,"command":command}}
except (OSError,subprocess.TimeoutExpired) as e:
    result={{"returncode":None,"error":str(e),"command":command}}
print(json.dumps(result))
"""
    argv = (
        [sys.executable, "-"]
        if host == "local"
        else [
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
            "python3 -",
        ]
    )
    try:
        proc = subprocess.run(
            argv, input=script, capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode:
            return {"returncode": proc.returncode, "error": proc.stderr.strip()}
        return json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"returncode": None, "error": str(exc)}


def recover(
    report,
    vendors=None,
    drivers=None,
    workers=8,
    timeout=25,
    include_virtual=False,
    sudo=False,
    wait=5,
):
    output = copy.deepcopy(report)
    selected = select(report, vendors, drivers)
    candidates = {
        n["node"]: missing_up(n)
        for n in selected["nodes"]
        if missing_up(n) and not n.get("lldp_recovery", {}).get("attempts")
    }
    if not candidates:
        return output
    print(
        f"LLDP: restarting lldpd once on {len(candidates)} node(s); waiting {wait}s then checking once.",
        file=sys.stderr,
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = dict(
            zip(
                candidates,
                pool.map(lambda host: restart_one(host, timeout), candidates),
            )
        )
    time.sleep(wait)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        after = list(
            pool.map(
                lambda host: scan_one(
                    host, timeout=timeout, include_virtual=include_virtual, sudo=sudo
                ),
                candidates,
            )
        )
    replacements = {}
    for node in after:
        host = node["node"]
        selected_node = select({"nodes": [node]}, vendors, drivers)["nodes"][0]
        remaining = missing_up(selected_node)
        restart = results[host]
        failed = restart.get("returncode") != 0
        node["lldp_recovery"] = {
            "attempts": 1,
            "wait_seconds": wait,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "restart": restart,
            "before_missing_ports": candidates[host],
            "remaining_missing_ports": remaining,
            "outcome": "restart_failed"
            if failed
            else "recheck_failed"
            if node["errors"]
            else "still_missing"
            if remaining
            else "recovered",
        }
        if failed:
            node["errors"].append(
                "LLDP restart failed: "
                + str(
                    restart.get("error")
                    or restart.get("stderr")
                    or restart.get("returncode")
                )
            )
        if remaining:
            node.setdefault("warnings", []).append(
                "UP physical ports still lack LLDP after one restart: "
                + ", ".join(remaining)
            )
        replacements[host] = node
    output["nodes"] = [replacements.get(n["node"], n) for n in output["nodes"]]
    output["recovery_policy"] = {
        "max_attempts_per_node": 1,
        "wait_seconds": wait,
        "rechecks": 1,
    }
    return output
