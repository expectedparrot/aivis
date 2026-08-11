from __future__ import annotations

import json
import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TypeVar

from filelock import FileLock, Timeout
from pydantic import BaseModel, ValidationError

from .config import Config
from .models import Counts, Prompt, PromptDocument, RunManifest, RunPlan, Sample, SampleObservations
from .util import config_hash, new_run_id, prompt_id, sample_id, utc_now

T = TypeVar("T", bound=BaseModel)


class StoreError(RuntimeError):
    pass


def write_json(path: Path, value: BaseModel | dict[str, Any]) -> None:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    payload = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        # Preserve the tmp file for fsck and forensic recovery.
        raise


def _load(path: Path, model: type[T]) -> T:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise StoreError(f"Invalid store file {path}: {exc}") from exc


class Store:
    def __init__(self, project: Path):
        self.project = project
        self.data = project / "data"
        self.runs = self.data / "runs"
        self._lock = FileLock(project / ".lock", timeout=30)

    @contextmanager
    def locked(self) -> Iterator[None]:
        try:
            with self._lock:
                yield
        except Timeout as exc:
            raise StoreError(
                f"Timed out waiting 30s for project lock {self.project / '.lock'}"
            ) from exc

    def initialize(self) -> None:
        self.runs.mkdir(parents=True, exist_ok=True)
        if not (self.data / "prompts.json").exists():
            self.write_prompts([])

    def write_prompts(self, prompts: list[Prompt]) -> None:
        ordered = sorted(prompts, key=lambda item: item.prompt_id)
        write_json(self.data / "prompts.json", PromptDocument(prompts=ordered))

    def load_prompts(self, include_retired: bool = False) -> list[Prompt]:
        path = self.data / "prompts.json"
        if not path.exists():
            return []
        prompts = _load(path, PromptDocument).prompts
        return prompts if include_retired else [item for item in prompts if item.active]

    def start_run(self, plan: RunPlan, config: Config, notes: str | None = None) -> RunManifest:
        run_id = new_run_id()
        snapshot = config.model_dump(mode="json")
        manifest = RunManifest(
            run_id=run_id,
            started_at=utc_now(),
            status="running",
            config_hash=config_hash(snapshot),
            config_snapshot=snapshot,
            plan=plan,
            notes=notes,
        )
        write_json(self.runs / run_id / "run.json", manifest)
        return manifest

    def write_sample(self, sample: Sample) -> None:
        run = self.load_run(sample.run_id)
        if run.status != "running":
            raise StoreError(f"Samples are immutable after run {sample.run_id} is finalized")
        expected = sample_id(sample.run_id, sample.prompt_id, sample.engine, sample.sample_index)
        if expected != sample.sample_id:
            raise StoreError(f"Invalid sample_id {sample.sample_id}; expected {expected}")
        write_json(
            self.runs / sample.run_id / "samples" / sample.engine / f"{sample.sample_id}.json",
            sample,
        )

    def write_observations(self, run_id: str, engine: str, obs: SampleObservations) -> None:
        obs.brands.sort(key=lambda item: item.brand.casefold())
        obs.judged_domains = sorted(set(obs.judged_domains))
        path = (
            self.runs
            / run_id
            / "observations"
            / f"v{obs.judge_version}"
            / engine
            / f"{obs.sample_id}.json"
        )
        write_json(path, obs)

    def finalize_run(
        self, run_id: str, status: str | None = None, counts: Counts | None = None
    ) -> RunManifest:
        manifest = self.load_run(run_id)
        samples = list(self.iter_samples(run_id))
        actual = counts or Counts(**Counter(item.status for item in samples))
        if status is None:
            planned = (
                manifest.plan.prompts
                * len(manifest.plan.engines)
                * manifest.plan.samples_per_prompt
            )
            if not samples:
                status = "failed"
            elif len(samples) == planned and actual.error == 0 and actual.blocked == 0:
                status = "complete"
            else:
                status = "partial"
        updated = manifest.model_copy(
            update={"finished_at": utc_now(), "status": status, "counts": actual}
        )
        write_json(self.runs / run_id / "run.json", updated)
        return updated

    def list_runs(self) -> list[RunManifest]:
        if not self.runs.exists():
            return []
        return [self.load_run(path.parent.name) for path in sorted(self.runs.glob("*/run.json"))]

    def load_run(self, run_id: str) -> RunManifest:
        return _load(self.runs / run_id / "run.json", RunManifest)

    def iter_samples(self, run_id: str, engines: list[str] | None = None) -> Iterator[Sample]:
        root = self.runs / run_id / "samples"
        if not root.exists():
            return
        for path in sorted(root.glob("*/*.json")):
            if engines is None or path.parent.name in engines:
                yield _load(path, Sample)

    def load_observations(
        self, run_id: str, judge_version: int | None = None, engines: list[str] | None = None
    ) -> list[SampleObservations]:
        version = judge_version if judge_version is not None else self.latest_judge_version(run_id)
        if version is None:
            return []
        root = self.runs / run_id / "observations" / f"v{version}"
        result = []
        for path in sorted(root.glob("*/*.json")):
            if engines is None or path.parent.name in engines:
                result.append(_load(path, SampleObservations))
        return result

    def latest_judge_version(self, run_id: str) -> int | None:
        root = self.runs / run_id / "observations"
        versions = (
            [int(path.name[1:]) for path in root.glob("v[0-9]*") if path.name[1:].isdigit()]
            if root.exists()
            else []
        )
        return max(versions, default=None)

    def missing_observations(self, run_id: str, judge_version: int) -> list[Sample]:
        present = {item.sample_id for item in self.load_observations(run_id, judge_version)}
        return [
            item
            for item in self.iter_samples(run_id)
            if item.status == "ok" and item.sample_id not in present
        ]

    def fsck(self, fix: bool = False) -> list[str]:
        errors: list[str] = []
        for tmp in self.project.rglob("*.tmp"):
            if fix:
                tmp.unlink()
            else:
                errors.append(f"orphaned temporary file: {tmp}")
        try:
            prompts = self.load_prompts(include_retired=True)
            for item in prompts:
                if item.prompt_id != prompt_id(item.text):
                    errors.append(f"prompt ID mismatch: {item.prompt_id}")
        except StoreError as exc:
            errors.append(str(exc))
        for run in self.list_runs():
            samples: list[Sample] = []
            try:
                samples = list(self.iter_samples(run.run_id))
            except StoreError as exc:
                errors.append(str(exc))
            ids = {item.sample_id for item in samples}
            for item in samples:
                expected = sample_id(item.run_id, item.prompt_id, item.engine, item.sample_index)
                if item.sample_id != expected:
                    errors.append(f"sample ID mismatch: {item.sample_id}")
            for path in sorted((self.runs / run.run_id / "observations").glob("v*/*/*.json")):
                try:
                    obs = _load(path, SampleObservations)
                    if obs.sample_id not in ids:
                        errors.append(f"observation references missing sample: {path}")
                except StoreError as exc:
                    errors.append(str(exc))
            actual = Counts(**Counter(item.status for item in samples))
            if run.status != "running" and actual != run.counts:
                if fix:
                    write_json(
                        self.runs / run.run_id / "run.json",
                        run.model_copy(update={"counts": actual}),
                    )
                else:
                    errors.append(
                        f"manifest counts mismatch: {self.runs / run.run_id / 'run.json'}"
                    )
        return errors
