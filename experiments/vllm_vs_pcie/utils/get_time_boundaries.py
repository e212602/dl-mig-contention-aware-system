#!/usr/bin/env python3
"""Print the time window covered by an aiperf raw JSONL export as JSON."""
import argparse
import datetime as dt
import json
import sys

NANOSECONDS_PER_SECOND = 10**9


def iso(unix_seconds: int) -> str:
    return dt.datetime.fromtimestamp(
        unix_seconds, tz=dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="aiperf *_raw.jsonl file")
    parser.add_argument("--pad-seconds", type=int, default=0)
    args = parser.parse_args()

    starts = []
    ends = []
    with open(args.file, encoding="utf-8") as raw_file:
        for line_number, line in enumerate(raw_file, 1):
            line = line.strip()
            if not line:
                continue
            try:
                metadata = json.loads(line)["metadata"]
            except (json.JSONDecodeError, KeyError) as error:
                sys.exit(f"{args.file}:{line_number}: unreadable record: {error!r}")
            if metadata.get("request_start_ns") is not None:
                starts.append(int(metadata["request_start_ns"]))
            if metadata.get("request_end_ns") is not None:
                ends.append(int(metadata["request_end_ns"]))

    if not starts or not ends:
        sys.exit(f"{args.file}: no request timestamps found")

    start_seconds = min(starts) // NANOSECONDS_PER_SECOND - args.pad_seconds
    end_seconds = -(-max(ends) // NANOSECONDS_PER_SECOND) + args.pad_seconds
    if start_seconds < 1_500_000_000 or end_seconds <= start_seconds:
        sys.exit(
            f"{args.file}: timestamps look wrong "
            f"(start={start_seconds}, end={end_seconds})"
        )

    json.dump(
        {
            "file": args.file,
            "requests": len(starts),
            "start": iso(start_seconds),
            "end": iso(end_seconds),
            "start_unix": start_seconds,
            "end_unix": end_seconds,
        },
        sys.stdout,
    )
    print()


if __name__ == "__main__":
    main()
