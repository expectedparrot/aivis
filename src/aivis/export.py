from __future__ import annotations

import csv
import json
from pathlib import Path

from .store import Store


def materialize(store: Store, run_ids: list[str]) -> dict:
    runs = []
    for run_id in run_ids:
        samples = list(store.iter_samples(run_id))
        observations = {item.sample_id: item for item in store.load_observations(run_id)}
        runs.append(
            {
                "run": store.load_run(run_id).model_dump(mode="json"),
                "samples": [
                    {
                        **sample.model_dump(mode="json"),
                        "observations": observations.get(sample.sample_id).model_dump(mode="json")
                        if sample.sample_id in observations
                        else None,
                    }
                    for sample in samples
                ],
            }
        )
    return {"runs": runs}


def export_json(store: Store, run_ids: list[str], out: Path) -> list[Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(materialize(store, run_ids), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    )
    return [out]


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_csv(store: Store, run_ids: list[str], out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    samples_rows, obs_rows, citation_rows = [], [], []
    for run_id in run_ids:
        for sample in store.iter_samples(run_id):
            row = sample.model_dump(mode="json")
            row["citations"] = json.dumps(row["citations"], sort_keys=True)
            samples_rows.append(row)
            for citation in sample.citations:
                citation_rows.append(
                    {
                        "run_id": run_id,
                        "sample_id": sample.sample_id,
                        **citation.model_dump(mode="json"),
                    }
                )
        for doc in store.load_observations(run_id):
            sample = next(
                (x for x in store.iter_samples(run_id) if x.sample_id == doc.sample_id), None
            )
            for brand in doc.brands:
                obs_rows.append(
                    {
                        "run_id": run_id,
                        "sample_id": doc.sample_id,
                        "engine": sample.engine if sample else None,
                        "judge_version": doc.judge_version,
                        **brand.model_dump(mode="json"),
                    }
                )
            for domain in doc.judged_domains:
                citation_rows.append(
                    {
                        "run_id": run_id,
                        "sample_id": doc.sample_id,
                        "domain": domain,
                        "url": None,
                        "title": None,
                        "source": "judged",
                    }
                )
    sample_fields = [
        "schema",
        "sample_id",
        "run_id",
        "prompt_id",
        "engine",
        "sample_index",
        "collected_at",
        "collector",
        "status",
        "response_text",
        "citations",
        "raw_ref",
        "error",
    ]
    obs_fields = [
        "run_id",
        "sample_id",
        "engine",
        "judge_version",
        "brand",
        "mentioned",
        "framing",
        "first_position",
    ]
    citation_fields = ["run_id", "sample_id", "domain", "url", "title", "source"]
    paths = [out / "samples.csv", out / "observations.csv", out / "citations.csv"]
    _write_csv(paths[0], samples_rows, sample_fields)
    _write_csv(paths[1], obs_rows, obs_fields)
    _write_csv(paths[2], citation_rows, citation_fields)
    return paths
