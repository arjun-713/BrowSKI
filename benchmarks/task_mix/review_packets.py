"""Prepare anonymous evidence packets for a separate qualitative reviewer."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


def write_packets(run_directory: Path, corpus: Path, seed: int) -> None:
    cases = {
        row["case_id"]: row
        for line in corpus.read_text().splitlines()
        if (row := json.loads(line))
    }
    results = [
        json.loads(line)
        for line in (run_directory / "results.jsonl").read_text().splitlines()
    ]
    replies: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pending: dict[str, dict[str, Any]] = {}
    for line in (run_directory / "provider-debug.jsonl").read_text().splitlines():
        record = json.loads(line)
        case_id = record["case_id"]
        payload = record["payload"]
        if record["event"] == "provider.request":
            pending[case_id] = payload.get("input", {})
        elif record["event"] == "provider.response":
            response = payload.get("response", {})
            parsed = response.get("output_parsed")
            if parsed is not None:
                context = pending.pop(case_id, {})
                replies[case_id].append(
                    {
                        "candidate_options": context.get("candidate_options", {}),
                        "public_decision": parsed,
                    }
                )

    packets = []
    mapping = {}
    for result in results:
        case_id = result["case_id"]
        packet_id = hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()[:12]
        mapping[packet_id] = case_id
        packets.append(
            {
                "packet_id": packet_id,
                "task": cases[case_id]["task"],
                "expected_browser_state": cases[case_id]["gold"],
                "browser_checks": result["evaluation"]["checks"],
                "observed_browser_state": result.get("observed_evaluator_state"),
                "active_url": result.get("active_url"),
                "tab_urls": result["tab_urls"],
                "runtime_status": result["runtime_status"],
                "public_decisions": replies[case_id],
                "evidence_limit": (
                    "Fixture state is independent of provider completion claims. "
                    "Provider outputs are sanitized; redacted values are not evidence. "
                    "Historical pages are not current visible completion evidence. "
                    "No internal reasoning is included."
                ),
            }
        )
    random.Random(seed).shuffle(packets)
    (run_directory / "qualitative-packets.jsonl").write_text(
        "".join(json.dumps(packet, sort_keys=True) + "\n" for packet in packets)
    )
    (run_directory / "qualitative-packet-map.json").write_text(
        json.dumps(mapping, indent=2, sort_keys=True) + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261014)
    args = parser.parse_args()
    write_packets(args.run_directory, args.corpus, args.seed)


if __name__ == "__main__":
    main()
