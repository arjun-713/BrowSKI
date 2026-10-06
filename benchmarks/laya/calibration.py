"""Calibration-only calculations, intentionally separate from prompt evaluation."""

from __future__ import annotations

import statistics
from typing import Any


def confidence_buckets(
    rows: list[dict[str, Any]], field: str, count: int = 10
) -> list[dict[str, Any]]:
    """Return equal-width confidence bins with sample count, mean, and accuracy."""
    grouped: list[list[dict[str, Any]]] = [[] for _ in range(count)]
    for row in rows:
        value = row.get(field)
        if not isinstance(value, (float, int)) or isinstance(value, bool):
            continue
        grouped[min(count - 1, max(0, int(float(value) * count)))].append(row)
    bins = []
    for index, group in enumerate(grouped):
        bins.append(
            {
                "bucket": f"{index / count:.1f}-{(index + 1) / count:.1f}",
                "count": len(group),
                "mean_confidence": statistics.fmean(float(row[field]) for row in group)
                if group
                else None,
                "accuracy": statistics.fmean(bool(row["correct"]) for row in group)
                if group
                else None,
            }
        )
    return bins


def expected_calibration_error(
    rows: list[dict[str, Any]], field: str, count: int = 10
) -> float | None:
    usable = [
        row
        for row in rows
        if isinstance(row.get(field), (float, int))
        and not isinstance(row.get(field), bool)
    ]
    if not usable:
        return None
    return sum(
        item["count"] / len(usable) * abs(item["mean_confidence"] - item["accuracy"])
        for item in confidence_buckets(usable, field, count)
        if item["count"]
    )


def brier_score(rows: list[dict[str, Any]]) -> float | None:
    """Multiclass Brier score averaged by label; unavailable without a distribution."""
    terms: list[float] = []
    for row in rows:
        probabilities = row.get("raw_probabilities") or row.get("probabilities") or {}
        if not isinstance(probabilities, dict) or not probabilities:
            continue
        gold = str(row.get("gold_key"))
        terms.append(
            sum(
                (float(prob) - float(str(label) == gold)) ** 2
                for label, prob in probabilities.items()
            )
        )
    return statistics.fmean(terms) if terms else None


def top_margin(row: dict[str, Any]) -> float | None:
    probabilities = row.get("raw_probabilities") or row.get("probabilities") or {}
    if not isinstance(probabilities, dict):
        return None
    values = sorted((float(value) for value in probabilities.values()), reverse=True)
    return values[0] - values[1] if len(values) >= 2 else None


def noul_probability_buckets(
    rows: list[dict[str, Any]], count: int = 10
) -> list[dict[str, Any]]:
    """Calibrate raw P(yes) against the observed gold yes rate, not answer correctness."""
    grouped: list[list[dict[str, Any]]] = [[] for _ in range(count)]
    for row in rows:
        probability = row.get("noul_p_yes")
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            grouped[min(count - 1, max(0, int(float(probability) * count)))].append(row)
    bins = []
    for index, group in enumerate(grouped):
        bins.append(
            {
                "bucket": f"{index / count:.1f}-{(index + 1) / count:.1f}",
                "count": len(group),
                "mean_p_yes": statistics.fmean(
                    float(row["noul_p_yes"]) for row in group
                )
                if group
                else None,
                "observed_yes_rate": statistics.fmean(
                    bool(row["gold_yes"]) for row in group
                )
                if group
                else None,
            }
        )
    return bins


def noul_ece(rows: list[dict[str, Any]], count: int = 10) -> float | None:
    usable = [row for row in rows if isinstance(row.get("noul_p_yes"), (int, float))]
    if not usable:
        return None
    return sum(
        item["count"]
        / len(usable)
        * abs(item["mean_p_yes"] - item["observed_yes_rate"])
        for item in noul_probability_buckets(usable, count)
        if item["count"]
    )


def noul_brier(rows: list[dict[str, Any]]) -> float | None:
    terms = [
        (float(row["noul_p_yes"]) - float(bool(row["gold_yes"]))) ** 2
        for row in rows
        if isinstance(row.get("noul_p_yes"), (int, float)) and "gold_yes" in row
    ]
    return statistics.fmean(terms) if terms else None
