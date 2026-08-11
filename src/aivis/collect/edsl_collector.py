from __future__ import annotations

from collections import Counter
from typing import Any

from rich.console import Console

from ..config import APIEngine, Config
from ..edsl_support import make_model
from ..models import Counts, Prompt, Sample
from ..store import Store
from ..util import normalize_response, sample_id, utc_now
from . import CollectorStats


class EDSLCollector:
    id = "edsl"

    def __init__(self, config: Config):
        self.config = config

    def supports(self, engine_id: str) -> bool:
        return any(item.id == engine_id for item in self.config.engines.api)

    @staticmethod
    def _value(row: dict[str, Any], *keys: str) -> Any:
        return next((row[key] for key in keys if key in row), None)

    def collect(
        self,
        prompts: list[Prompt],
        engines: list[APIEngine],
        n_samples: int,
        run_id: str,
        store: Store,
        console: Console,
    ) -> CollectorStats:
        try:
            from edsl import Model, ModelList, QuestionFreeText, Scenario, ScenarioList
        except ImportError as exc:
            raise RuntimeError("EDSL is required for API collection") from exc
        scenarios = ScenarioList(
            [
                Scenario({"prompt": p.text, "prompt_id": p.prompt_id, "sample_index": i})
                for p in prompts
                for i in range(n_samples)
            ]
        )
        models = ModelList([make_model(Model, item.id) for item in engines])
        question = QuestionFreeText(question_name="response", question_text="{{ scenario.prompt }}")
        expected = {
            (p.prompt_id, e.id, i) for p in prompts for e in engines for i in range(n_samples)
        }
        seen: set[tuple[str, str, int]] = set()
        counts: Counter[str] = Counter()
        try:
            run_options = {"cache": self.config.collection.api_cache}
            if self.config.collection.remote:
                run_options["offload_execution"] = True
            else:
                run_options["disable_remote_inference"] = True
            results = question.by(scenarios).by(models).run(**run_options)
            rows = results.to_dicts()
        except Exception as exc:
            rows = []
            collection_error = f"EDSL collection failed: {type(exc).__name__}: {exc}"
        else:
            collection_error = "EDSL returned no result for planned sample"
        for row in rows:
            pid = self._value(row, "scenario.prompt_id", "prompt_id")
            engine = self._value(row, "model.model", "model")
            index = int(self._value(row, "scenario.sample_index", "sample_index") or 0)
            key = (pid, engine, index)
            if key not in expected:
                continue
            seen.add(key)
            response = self._value(row, "answer.response", "response")
            error = self._value(row, "error.response", "error")
            status = "ok" if response is not None and not error else "error"
            sample = Sample(
                sample_id=sample_id(run_id, pid, engine, index),
                run_id=run_id,
                prompt_id=pid,
                engine=engine,
                sample_index=index,
                collected_at=utc_now(),
                collector="edsl",
                status=status,
                response_text=normalize_response(str(response)) if status == "ok" else None,
                error=str(error) if error else None,
            )
            store.write_sample(sample)
            counts[status] += 1
        for pid, engine, index in sorted(expected - seen):
            store.write_sample(
                Sample(
                    sample_id=sample_id(run_id, pid, engine, index),
                    run_id=run_id,
                    prompt_id=pid,
                    engine=engine,
                    sample_index=index,
                    collected_at=utc_now(),
                    collector="edsl",
                    status="error",
                    error=collection_error,
                )
            )
            counts["error"] += 1
        console.print(f"Collected {sum(counts.values())} API samples")
        return CollectorStats(Counts(**counts))
