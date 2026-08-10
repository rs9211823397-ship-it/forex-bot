"""Combine per-symbol/per-time context parity reports into one promotion gate."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--min-snapshots", type=int, default=100)
    parser.add_argument("--output", default="outputs/validation/context_parity_combined.json")
    args = parser.parse_args()
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.inputs]
    mismatches = sum(len(item.get("mismatches", [])) for item in reports)
    sample_complete = len(reports) >= args.min_snapshots
    report = {
        "snapshots": len(reports),
        "minimum_required": args.min_snapshots,
        "sample_complete": sample_complete,
        "mismatched_fields": mismatches,
        "passed": sample_complete and mismatches == 0 and all(item.get("passed", False) for item in reports),
        "inputs": args.inputs,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
