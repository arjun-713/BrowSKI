"""Probe Laya on frozen synthetic action decisions; never execute a browser action."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.task_mix.probe_dataset import freeze, load_frozen
from benchmarks.task_mix.probe_runtime import run_probe

DEFAULT_FROZEN = Path(__file__).with_name("laya_probe_frozen_20261012_v2.jsonl")
DEFAULT_MANIFEST = Path(__file__).with_name("laya_probe_manifest_20261012_v2.json")
DEFAULT_RESULTS = Path(__file__).with_name("laya_probe_results_20261012_v2.jsonl")
DEFAULT_SUMMARY = Path(__file__).with_name("laya_probe_summary_20261012_v2.json")
DEFAULT_REPORT = Path(__file__).with_name("laya_probe_report_20261012_v2.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser(
        "freeze", help="write offline synthetic packets only"
    )
    freeze_parser.add_argument("--frozen", type=Path, default=DEFAULT_FROZEN)
    freeze_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    run_parser = subparsers.add_parser(
        "run", help="infer only after SHA-256 is explicitly approved"
    )
    run_parser.add_argument("--frozen", type=Path, default=DEFAULT_FROZEN)
    run_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    run_parser.add_argument("--expected-sha256", required=True)
    run_parser.add_argument("--endpoint", default="http://127.0.0.1:8001")
    run_parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    run_parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    run_parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    if args.command == "freeze":
        manifest = freeze(args.frozen, args.manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    rows = load_frozen(args.frozen, args.manifest, args.expected_sha256)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    asyncio.run(
        run_probe(
            rows,
            endpoint=args.endpoint.rstrip("/"),
            results_path=args.results,
            summary_path=args.summary,
            report_path=args.report,
            manifest=manifest,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
