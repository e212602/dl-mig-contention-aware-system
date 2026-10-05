#!/usr/bin/env python3
"""Print the time window covered by an aiperf raw JSONL export as JSON.

Only the standard library is needed, so it runs with any python3 (no pandas).
The window is widened to whole seconds (start rounded down, end rounded up)
and optionally padded, so Prometheus samples at the edges are not cut off.
"""
import argparse
import datetime as dt
import json
import sys

NS = 10**9


def iso(unix_s: int) -> str:
    return dt.datetime.fromtimestamp(unix_s, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="aiperf *_raw.jsonl file")
    ap.add_argument("--pad-seconds", type=int, default=0, help="extend the window on both sides")
    args = ap.parse_args()

    starts, ends, n = [], [], 0
    with open(args.file) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                meta = json.loads(line)["metadata"]
            except (json.JSONDecodeError, KeyError) as e:
                sys.exit(f"{args.file}:{lineno}: unreadable record: {e!r}")
            n += 1
            # Failed requests may lack an end time; skip missing values.
            if meta.get("request_start_ns") is not None:
                starts.append(int(meta["request_start_ns"]))
            if meta.get("request_end_ns") is not None:
                ends.append(int(meta["request_end_ns"]))

    if not starts or not ends:
        sys.exit(f"{args.file}: no request timestamps found")

    # Integer math: nanosecond epochs exceed float precision.
    start_s = min(starts) // NS - args.pad_seconds
    end_s = -(-max(ends) // NS) + args.pad_seconds  # ceil

    # Prometheus needs wall-clock epoch time; catch a monotonic clock early.
    if start_s < 1_500_000_000 or end_s <= start_s:
        sys.exit(f"{args.file}: timestamps look wrong (start={start_s}, end={end_s}); "
                 "request_*_ns must be Unix epoch nanoseconds")

    json.dump({
        "file": args.file,
        "requests": n,
        "start": iso(start_s),
        "end": iso(end_s),
        "start_unix": start_s,
        "end_unix": end_s,
    }, sys.stdout)
    print()


if __name__ == "__main__":
    main()