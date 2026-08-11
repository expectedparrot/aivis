from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema: Literal[1] = 1


class Prompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_id: str
    text: str
    cluster: str
    active: bool = True
    created_at: str
    retired_at: str | None = None


class PromptDocument(Record):
    prompts: list[Prompt] = Field(default_factory=list)


class RunPlan(BaseModel):
    prompts: int
    engines: list[str]
    samples_per_prompt: int


class Counts(BaseModel):
    ok: int = 0
    error: int = 0
    not_present: int = 0
    blocked: int = 0


class RunManifest(Record):
    run_id: str
    started_at: str
    finished_at: str | None = None
    status: Literal["running", "complete", "partial", "failed"]
    config_hash: str
    config_snapshot: dict
    plan: RunPlan
    counts: Counts = Field(default_factory=Counts)
    notes: str | None = None


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str | None = None
    domain: str
    title: str | None = None
    source: Literal["native"] = "native"


class Sample(Record):
    sample_id: str
    run_id: str
    prompt_id: str
    engine: str
    sample_index: int = Field(ge=0)
    collected_at: str
    collector: Literal["edsl", "playwright"]
    status: Literal["ok", "error", "not_present", "blocked"]
    response_text: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    raw_ref: str | None = None
    error: str | None = None


class BrandObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str
    mentioned: bool
    framing: Literal["recommended", "neutral", "negative", "not_mentioned"]
    first_position: int | None = None


class SampleObservations(Record):
    sample_id: str
    judge_version: int
    judge_model: str
    extracted_at: str
    brands: list[BrandObservation]
    judged_domains: list[str] = Field(default_factory=list)
