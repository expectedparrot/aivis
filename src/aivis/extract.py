from __future__ import annotations

import logging
from typing import Any, Callable

from .config import Config
from .edsl_support import make_model
from .models import BrandObservation, Sample, SampleObservations
from .store import Store
from .util import normalize_domain, utc_now

log = logging.getLogger(__name__)


def _canonical(value: str, config: Config) -> str | None:
    cleaned = value.split(" (aka ", 1)[0].strip().casefold()
    for brand in config.tracked_brands:
        if cleaned in {brand.name.casefold(), *(alias.casefold() for alias in brand.aliases)}:
            return brand.name
    log.debug("Unmapped judge brand: %s", value)
    return None


def assemble_observations(
    sample: Sample,
    config: Config,
    first: dict[str, Any],
    framings: dict[str, str],
    version: int | None = None,
) -> SampleObservations:
    mentioned = {_canonical(str(value), config) for value in (first.get("mentioned") or [])}
    mentioned.discard(None)
    order = []
    for value in first.get("mention_order") or []:
        canonical = _canonical(str(value), config)
        if canonical and canonical not in order:
            order.append(canonical)
    brands = []
    for brand in config.tracked_brands:
        is_mentioned = brand.name in mentioned
        raw = str(framings.get(brand.name) or "neutral").lower()
        framing = (
            "recommended"
            if raw.startswith("recommended")
            else "negative"
            if raw.startswith("negative")
            else "neutral"
        )
        brands.append(
            BrandObservation(
                brand=brand.name,
                mentioned=is_mentioned,
                framing=framing if is_mentioned else "not_mentioned",
                first_position=order.index(brand.name) + 1 if brand.name in order else None,
            )
        )
    domains = [normalize_domain(str(value)) for value in first.get("cited_domains") or []]
    return SampleObservations(
        sample_id=sample.sample_id,
        judge_version=version or config.judge.version,
        judge_model=config.judge.model,
        extracted_at=utc_now(),
        brands=brands,
        judged_domains=sorted({x for x in domains if x}),
    )


def _edsl_judge(samples: list[Sample], config: Config) -> dict[str, SampleObservations]:
    try:
        from edsl import (
            Model,
            QuestionCheckBox,
            QuestionList,
            QuestionMultipleChoice,
            Scenario,
            ScenarioList,
            Survey,
        )
    except ImportError as exc:
        raise RuntimeError("EDSL is required for extraction") from exc
    displays = [brand.render() for brand in config.tracked_brands]
    scenarios = ScenarioList(
        [Scenario({"sample_id": s.sample_id, "response": s.response_text or ""}) for s in samples]
    )
    survey = Survey(
        [
            QuestionCheckBox(
                question_name="mentioned",
                question_text="Which tracked brands are mentioned, including aliases?\n\nRESPONSE:\n{{ scenario.response }}",
                question_options=displays + ["None of these"],
            ),
            QuestionList(
                question_name="mention_order",
                question_text="List mentioned tracked brands in first-appearance order using canonical names.\n\nRESPONSE:\n{{ scenario.response }}",
            ),
            QuestionList(
                question_name="cited_domains",
                question_text="List website domains cited, linked, or named as sources; empty list if none.\n\nRESPONSE:\n{{ scenario.response }}",
            ),
        ]
    )
    run_options = {"cache": config.collection.judge_cache}
    if config.collection.remote:
        run_options["offload_execution"] = True
    else:
        run_options["disable_remote_inference"] = True
    results = survey.by(scenarios).by(make_model(Model, config.judge.model)).run(**run_options)
    first_by_id: dict[str, dict[str, Any]] = {}
    for row in results.to_dicts():
        sid = row.get("scenario.sample_id") or row.get("sample_id")
        first_by_id[sid] = {
            key: row.get(f"answer.{key}", row.get(key))
            for key in ("mentioned", "mention_order", "cited_domains")
        }
    framing_scenarios = []
    for sample in samples:
        first = first_by_id.get(sample.sample_id, {})
        names = {_canonical(str(x), config) for x in first.get("mentioned") or []}
        for name in names - {None}:
            framing_scenarios.append(
                {
                    "sample_id": sample.sample_id,
                    "response": sample.response_text or "",
                    "brand": name,
                }
            )
    framing_by_id: dict[str, dict[str, str]] = {}
    if framing_scenarios:
        question = QuestionMultipleChoice(
            question_name="framing",
            question_text="How is {{ scenario.brand }} framed?\n\nRESPONSE:\n{{ scenario.response }}",
            question_options=[
                "Recommended — presented as the answer or a top choice",
                "Neutral mention — named without endorsement",
                "Negative — criticized, cautioned against, or unfavorably compared",
            ],
        )
        results2 = (
            question.by(ScenarioList([Scenario(item) for item in framing_scenarios]))
            .by(make_model(Model, config.judge.model))
            .run(**run_options)
        )
        for row in results2.to_dicts():
            sid = row.get("scenario.sample_id") or row.get("sample_id")
            name = row.get("scenario.brand") or row.get("brand")
            framing_by_id.setdefault(sid, {})[name] = row.get(
                "answer.framing", row.get("framing", "neutral")
            )
    return {
        sample.sample_id: assemble_observations(
            sample,
            config,
            first_by_id.get(sample.sample_id, {}),
            framing_by_id.get(sample.sample_id, {}),
        )
        for sample in samples
    }


def extract_run(
    store: Store,
    run_id: str,
    config: Config,
    version: int | None = None,
    judge: Callable[[list[Sample], Config], dict[str, SampleObservations]] | None = None,
) -> int:
    version = version or config.judge.version
    samples = store.missing_observations(run_id, version)
    if not samples:
        return 0
    outputs = (judge or _edsl_judge)(samples, config)
    for sample in samples:
        obs = outputs[sample.sample_id].model_copy(update={"judge_version": version})
        store.write_observations(run_id, sample.engine, obs)
    return len(samples)
