from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .config import Config
from .metrics import (
    avg_first_position,
    mention_rate,
    rec_given_mention,
    recommendation_rate,
    share_of_voice,
)
from .models import Sample, SampleObservations
from .store import Store, write_json


def _metric(metric) -> dict:
    return {
        "value": metric.value,
        "n": metric.n,
        "small_sample": metric.small_sample,
    }


def _brand_metrics(
    samples: list[Sample], observations: list[SampleObservations], config: Config
) -> list[dict]:
    return [
        {
            "brand": brand.name,
            "share_of_voice_pct": _metric(share_of_voice(samples, observations, brand.name)),
            "mention_rate_pct": _metric(mention_rate(samples, observations, brand.name)),
            "recommendation_rate_pct": _metric(
                recommendation_rate(samples, observations, brand.name)
            ),
            "recommendation_given_mention_pct": _metric(
                rec_given_mention(samples, observations, brand.name)
            ),
            "average_first_position": _metric(
                avg_first_position(samples, observations, brand.name)
            ),
        }
        for brand in config.tracked_brands
    ]


def _excerpt(text: str, names: Iterable[str], limit: int) -> str:
    if len(text) <= limit:
        return text
    lowered = text.casefold()
    positions = [lowered.find(name.casefold()) for name in names]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - limit // 4)
    end = min(len(text), start + limit)
    start = max(0, end - limit)
    return text[start:end]


def build_report_context(
    store: Store, run_id: str, config: Config, excerpt_chars: int = 1200
) -> dict:
    run = store.load_run(run_id)
    samples = list(store.iter_samples(run_id))
    observations = store.load_observations(run_id)
    prompts = {item.prompt_id: item for item in store.load_prompts(include_retired=True)}
    obs_by_sample = {item.sample_id: item for item in observations}
    successful = [item for item in samples if item.status == "ok"]
    planned = run.plan.prompts * len(run.plan.engines) * run.plan.samples_per_prompt
    coverage = 100 * len(successful) / planned if planned else None

    reasons = []
    if run.status != "complete":
        reasons.append(f"Run status is {run.status}.")
    if len(successful) != planned:
        reasons.append(f"Only {len(successful)} of {planned} planned samples succeeded.")
    if len(observations) != len(successful):
        reasons.append(
            f"Observations exist for {len(observations)} of {len(successful)} successful samples."
        )
    reportability = (
        "invalid"
        if not successful or not observations
        else "reportable"
        if run.status == "complete" and len(observations) == len(successful)
        else "directional"
    )

    engine_coverage = []
    for engine in run.plan.engines:
        rows = [item for item in samples if item.engine == engine]
        counts = Counter(item.status for item in rows)
        engine_coverage.append(
            {
                "engine": engine,
                "planned": run.plan.prompts * run.plan.samples_per_prompt,
                "counts": dict(sorted(counts.items())),
                "coverage_pct": round(100 * counts["ok"] / len(rows), 1) if rows else None,
            }
        )

    slices = {"overall": _brand_metrics(samples, observations, config)}
    slices["by_engine"] = {
        engine: _brand_metrics(
            [item for item in samples if item.engine == engine], observations, config
        )
        for engine in run.plan.engines
    }
    clusters = sorted({prompt.cluster for prompt in prompts.values()})
    slices["by_cluster"] = {}
    for cluster in clusters:
        ids = {prompt.prompt_id for prompt in prompts.values() if prompt.cluster == cluster}
        cluster_samples = [item for item in samples if item.prompt_id in ids]
        slices["by_cluster"][cluster] = _brand_metrics(cluster_samples, observations, config)

    prompt_rows = []
    grouped: dict[tuple[str, str], list[Sample]] = defaultdict(list)
    for sample in samples:
        grouped[(sample.prompt_id, sample.engine)].append(sample)
    for (prompt_id, engine), rows in sorted(grouped.items()):
        prompt = prompts.get(prompt_id)
        focal_rows = []
        for sample in rows:
            obs = obs_by_sample.get(sample.sample_id)
            if obs:
                focal = next((row for row in obs.brands if row.brand == config.brand.name), None)
                if focal:
                    focal_rows.append(focal)
        prompt_rows.append(
            {
                "prompt_id": prompt_id,
                "prompt": prompt.text if prompt else None,
                "cluster": prompt.cluster if prompt else None,
                "engine": engine,
                "planned_samples": run.plan.samples_per_prompt,
                "successful_samples": sum(item.status == "ok" for item in rows),
                "error_samples": sum(item.status == "error" for item in rows),
                "focal_brand_mentions": sum(item.mentioned for item in focal_rows),
                "focal_brand_recommendations": sum(
                    item.framing == "recommended" for item in focal_rows
                ),
                "observed_focal_outcomes": [
                    {
                        "mentioned": item.mentioned,
                        "framing": item.framing,
                        "first_position": item.first_position,
                    }
                    for item in focal_rows
                ],
            }
        )

    evidence = []
    names = [name for brand in config.tracked_brands for name in [brand.name, *brand.aliases]]
    for sample in sorted(successful, key=lambda item: item.sample_id):
        obs = obs_by_sample.get(sample.sample_id)
        if not obs:
            continue
        prompt = prompts.get(sample.prompt_id)
        native = [item.model_dump(mode="json") for item in sample.citations]
        evidence.append(
            {
                "evidence_id": f"sample:{sample.sample_id}",
                "sample_id": sample.sample_id,
                "prompt_id": sample.prompt_id,
                "prompt": prompt.text if prompt else None,
                "cluster": prompt.cluster if prompt else None,
                "engine": sample.engine,
                "sample_index": sample.sample_index,
                "brand_observations": [item.model_dump(mode="json") for item in obs.brands],
                "citations": native,
                "judged_domains": obs.judged_domains,
                "exact_response_excerpt": _excerpt(
                    sample.response_text or "", names, excerpt_chars
                ),
                "source_path": str(
                    store.runs / run_id / "samples" / sample.engine / f"{sample.sample_id}.json"
                ),
            }
        )

    failure_reasons = Counter(item.error or item.status for item in samples if item.status != "ok")
    return {
        "schema": 1,
        "kind": "aivis_report_context",
        "run": run.model_dump(mode="json"),
        "reportability": {
            "status": reportability,
            "reasons": reasons,
            "coverage_pct": round(coverage, 1) if coverage is not None else None,
            "allowed_use": "Compose a qualified account of patterns in the observed samples.",
            "restriction": "Do not generalize partial-run metrics to the full plan or consumer AI products.",
        },
        "methodology": {
            "metric_denominator_rule": "Metrics exclude samples whose status is not ok.",
            "share_of_voice": "Brand mentioned-sample count divided by all tracked-brand mentioned-sample counts.",
            "recommendation_rate": "Recommended samples divided by all successful samples.",
            "small_sample_threshold": 20,
            "judge_version": store.latest_judge_version(run_id),
            "judge_model": config.judge.model,
            "api_product_caveat": "API models are proxy trend lines, not replicas of consumer products with browsing, memory, and personalization.",
        },
        "coverage": {
            "planned_samples": planned,
            "successful_samples": len(successful),
            "observation_files": len(observations),
            "by_engine": engine_coverage,
            "failure_reasons": [
                {"reason": reason, "count": count}
                for reason, count in sorted(failure_reasons.items())
            ],
        },
        "metrics": slices,
        "prompt_outcomes": prompt_rows,
        "evidence": evidence,
        "agent_instructions": [
            "Lead with reportability and coverage before metrics.",
            "Use metric values and denominators exactly as supplied; do not recompute them from excerpts.",
            "Qualify every partial-run finding as applying to successful samples only.",
            "Cite evidence_id and sample_id for claims about particular answers.",
            "Treat exact_response_excerpt as evidence, not as a representative quotation unless multiple samples support the pattern.",
            "Do not infer causality from citation co-occurrence.",
        ],
    }


def write_report_context(
    store: Store,
    run_id: str,
    config: Config,
    output: Path,
    excerpt_chars: int = 1200,
) -> dict:
    payload = build_report_context(store, run_id, config, excerpt_chars)
    write_json(output, payload)
    return payload
