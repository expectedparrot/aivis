from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Iterable

from .models import BrandObservation, Sample, SampleObservations


@dataclass(frozen=True)
class Metric:
    value: float | None
    n: int

    @property
    def small_sample(self) -> bool:
        return self.n < 20


def _ok_ids(samples: Iterable[Sample]) -> set[str]:
    return {item.sample_id for item in samples if item.status == "ok"}


def _brand_rows(
    observations: Iterable[SampleObservations], brand: str, eligible: set[str]
) -> list[BrandObservation]:
    return [
        row
        for item in observations
        if item.sample_id in eligible
        for row in item.brands
        if row.brand.casefold() == brand.casefold()
    ]


def mention_rate(
    samples: Iterable[Sample], observations: Iterable[SampleObservations], brand: str
) -> Metric:
    eligible = _ok_ids(samples)
    rows = _brand_rows(observations, brand, eligible)
    return (
        Metric(round(100 * sum(row.mentioned for row in rows) / len(eligible), 1), len(eligible))
        if eligible
        else Metric(None, 0)
    )


def recommendation_rate(
    samples: Iterable[Sample], observations: Iterable[SampleObservations], brand: str
) -> Metric:
    eligible = _ok_ids(samples)
    rows = _brand_rows(observations, brand, eligible)
    return (
        Metric(
            round(100 * sum(row.framing == "recommended" for row in rows) / len(eligible), 1),
            len(eligible),
        )
        if eligible
        else Metric(None, 0)
    )


def rec_given_mention(
    samples: Iterable[Sample], observations: Iterable[SampleObservations], brand: str
) -> Metric:
    eligible = _ok_ids(samples)
    rows = [row for row in _brand_rows(observations, brand, eligible) if row.mentioned]
    return (
        Metric(
            round(100 * sum(row.framing == "recommended" for row in rows) / len(rows), 1), len(rows)
        )
        if rows
        else Metric(None, 0)
    )


def share_of_voice(
    samples: Iterable[Sample], observations: Iterable[SampleObservations], brand: str
) -> Metric:
    eligible = _ok_ids(samples)
    rows = [row for item in observations if item.sample_id in eligible for row in item.brands]
    total = sum(row.mentioned for row in rows)
    own = sum(row.mentioned and row.brand.casefold() == brand.casefold() for row in rows)
    return Metric(round(100 * own / total, 1), total) if total else Metric(None, 0)


def avg_first_position(
    samples: Iterable[Sample], observations: Iterable[SampleObservations], brand: str
) -> Metric:
    eligible = _ok_ids(samples)
    positions = [
        row.first_position
        for row in _brand_rows(observations, brand, eligible)
        if row.mentioned and row.first_position is not None
    ]
    return Metric(round(mean(positions), 1), len(positions)) if positions else Metric(None, 0)


def presence_rate(samples: Iterable[Sample], engine: str) -> Metric:
    rows = [
        item for item in samples if item.engine == engine and item.status in {"ok", "not_present"}
    ]
    return (
        Metric(round(100 * sum(item.status == "ok" for item in rows) / len(rows), 1), len(rows))
        if rows
        else Metric(None, 0)
    )


def sentiment_mix(
    samples: Iterable[Sample], observations: Iterable[SampleObservations], brand: str
) -> dict[str, Metric]:
    eligible = _ok_ids(samples)
    rows = [row for row in _brand_rows(observations, brand, eligible) if row.mentioned]
    return {
        kind: Metric(
            round(100 * sum(row.framing == kind for row in rows) / len(rows), 1), len(rows)
        )
        if rows
        else Metric(None, 0)
        for kind in ("recommended", "neutral", "negative")
    }


def citation_influence(
    samples: Iterable[Sample], observations: Iterable[SampleObservations], focal_brand: str
) -> dict[str, tuple[int, int]]:
    samples = [item for item in samples if item.status == "ok"]
    mentioned = {
        item.sample_id
        for item in observations
        for row in item.brands
        if row.brand.casefold() == focal_brand.casefold() and row.mentioned
    }
    judged = {item.sample_id: set(item.judged_domains) for item in observations}
    result: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for sample in samples:
        native = {citation.domain for citation in sample.citations}
        domains = native | (judged.get(sample.sample_id, set()) - native)
        for domain in domains:
            result[domain][0 if sample.sample_id in mentioned else 1] += 1
    return {domain: (counts[0], counts[1]) for domain, counts in result.items()}


def volatility(
    previous_samples: Iterable[Sample],
    previous_obs: Iterable[SampleObservations],
    current_samples: Iterable[Sample],
    current_obs: Iterable[SampleObservations],
    brand: str,
) -> Metric:
    def outcomes(samples: Iterable[Sample], observations: Iterable[SampleObservations]):
        by_id = {s.sample_id: s for s in samples if s.status == "ok"}
        result: dict[tuple[str, str, int], bool] = {}
        for obs in observations:
            sample = by_id.get(obs.sample_id)
            if sample:
                row = next((x for x in obs.brands if x.brand.casefold() == brand.casefold()), None)
                if row:
                    result[(sample.prompt_id, sample.engine, sample.sample_index)] = row.mentioned
        return result

    old, new = outcomes(previous_samples, previous_obs), outcomes(current_samples, current_obs)
    common = old.keys() & new.keys()
    return (
        Metric(
            round(100 * sum(old[key] != new[key] for key in common) / len(common), 1), len(common)
        )
        if common
        else Metric(None, 0)
    )
