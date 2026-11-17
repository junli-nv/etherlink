#!/usr/bin/env python3
"""Bounded Slurm-style host expressions (not a dependency on Slurm)."""

import re


def expand(expression, limit=4096):
    result = []

    def visit(text):
        depth = 0
        start = 0
        parts = []
        for i, ch in enumerate(text):
            if ch == "[":
                depth += 1
                if depth > 1:
                    raise ValueError("nested brackets are unsupported")
            elif ch == "]":
                depth -= 1
                if depth < 0:
                    raise ValueError("unmatched closing bracket")
            elif ch == "," and depth == 0:
                parts.append(text[start:i])
                start = i + 1
        if depth:
            raise ValueError("unmatched opening bracket")
        parts.append(text[start:])
        if len(parts) > 1:
            for part in parts:
                visit(part)
            return
        if "[" in text:
            left, rest = text.split("[", 1)
            middle, right = rest.split("]", 1)
            for item in middle.split(","):
                match = re.fullmatch(r"(\d+)(?:-(\d+))?", item)
                if not match:
                    raise ValueError("ranges must contain numbers: " + item)
                first, last = match.groups()
                a, b = int(first), int(last or first)
                if a > b or b - a + 1 > limit:
                    raise ValueError("descending or oversized range: " + item)
                width = (
                    max(len(first), len(last or first))
                    if first.startswith("0") or (last or "").startswith("0")
                    else 0
                )
                for number in range(a, b + 1):
                    visit(left + str(number).zfill(width) + right)
            return
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:@%-]*", text):
            raise ValueError("invalid SSH host: " + text)
        result.append(text)
        if len(result) > limit:
            raise ValueError("host expansion exceeds limit")

    visit(expression)
    return list(dict.fromkeys(result))


def compact(hosts):
    """Compress the final numeric component; never invent a Cartesian product."""
    groups, plain = {}, set()
    for host in set(hosts):
        match = re.fullmatch(r"(.*?)(\d+)(\D*)", host)
        if not match:
            plain.add(host)
            continue
        prefix, digits, suffix = match.groups()
        width = len(digits) if len(digits) > 1 and digits.startswith("0") else 0
        groups.setdefault((prefix, suffix, width), set()).add(int(digits))
    output = list(plain)
    for (prefix, suffix, width), numbers in sorted(groups.items()):
        ordered = sorted(numbers)
        spans = []
        start = end = ordered[0]

        def label(n):
            return str(n).zfill(width)

        for n in ordered[1:] + [None]:
            if n is not None and n == end + 1:
                end = n
                continue
            spans.append(
                label(start) if start == end else label(start) + "-" + label(end)
            )
            start = end = n
        middle = spans[0] if len(numbers) == 1 else "[" + ",".join(spans) + "]"
        output.append(prefix + middle + suffix)
    return ",".join(sorted(output))


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Expand or compact Slurm-style host expressions."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--expand", "-e", action="store_true", help="expand expressions (default)"
    )
    mode.add_argument(
        "--compact", "-c", action="store_true", help="compact names/ranges"
    )
    parser.add_argument(
        "--limit", type=int, default=4096, help="maximum expanded input count"
    )
    parser.add_argument("--separator", default="\n", help="expanded output separator")
    parser.add_argument(
        "hosts",
        nargs="*",
        help="quoted expressions; '-' reads whitespace-separated stdin",
    )
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be positive")
    inputs = args.hosts or (["-"] if not sys.stdin.isatty() else [])
    if not inputs:
        parser.error("provide host expressions or stdin")
    names = []
    try:
        for expression in inputs:
            expressions = (
                sys.stdin.read().split() if expression == "-" else [expression]
            )
            for value in expressions:
                names.extend(expand(value, args.limit))
                if len(names) > args.limit:
                    raise ValueError("total host expansion exceeds limit")
        names = list(dict.fromkeys(names))
    except ValueError as exc:
        parser.error(str(exc))
    print(compact(names) if args.compact else args.separator.join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
