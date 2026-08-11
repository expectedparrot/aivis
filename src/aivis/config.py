from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Brand(StrictModel):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)

    def render(self) -> str:
        return self.name if not self.aliases else f"{self.name} (aka {', '.join(self.aliases)})"


class APIEngine(StrictModel):
    id: str
    enabled: bool = True


class BrowserEngine(APIEngine):
    locale: str = "en-US"
    geo: str = "us"


class Engines(StrictModel):
    api: list[APIEngine] = Field(
        default_factory=lambda: [
            APIEngine(id="gpt-4o"),
            APIEngine(id="claude-sonnet-4-6"),
            APIEngine(id="gemini-2.5-flash"),
            APIEngine(id="sonar", enabled=False),
        ]
    )
    browser: list[BrowserEngine] = Field(
        default_factory=lambda: [
            BrowserEngine(id="google-aio", enabled=False),
            BrowserEngine(id="google-ai-mode", enabled=False),
        ]
    )


class Sampling(StrictModel):
    runs_per_prompt: int = Field(default=3, ge=1)
    temperature: float | None = None


class Judge(StrictModel):
    model: str = "gpt-4o-mini"
    version: int = Field(default=1, ge=1)


class Collection(StrictModel):
    api_cache: bool = False
    judge_cache: bool = True
    timeout_seconds: int = Field(default=120, ge=1)
    max_concurrency: int = Field(default=8, ge=1)
    retries: int = Field(default=2, ge=0)
    remote: bool = False


class PlaywrightConfig(StrictModel):
    headless: bool = True
    slow_mo_ms: int = Field(default=0, ge=0)
    min_delay_seconds: float = Field(default=8, ge=0)
    screenshot: bool = True
    storage_state: str | None = None


class Reporting(StrictModel):
    default_weeks: int = Field(default=8, ge=1)
    fail_threshold_sov_drop: float | None = Field(default=None, ge=0)


class Config(StrictModel):
    version: int = 1
    brand: Brand
    competitors: list[Brand] = Field(default_factory=list)
    engines: Engines = Field(default_factory=Engines)
    sampling: Sampling = Field(default_factory=Sampling)
    judge: Judge = Field(default_factory=Judge)
    collection: Collection = Field(default_factory=Collection)
    playwright: PlaywrightConfig = Field(default_factory=PlaywrightConfig)
    reporting: Reporting = Field(default_factory=Reporting)

    @model_validator(mode="after")
    def unique_brands(self) -> "Config":
        names = [b.name.casefold() for b in self.tracked_brands]
        if len(names) != len(set(names)):
            raise ValueError("brand and competitor names must be unique")
        return self

    @property
    def tracked_brands(self) -> list[Brand]:
        return [self.brand, *self.competitors]


def load_config(project: Path) -> Config:
    path = project / "aivis.yaml"
    try:
        return Config.model_validate(yaml.safe_load(path.read_text()) or {})
    except Exception as exc:
        raise ValueError(f"Invalid config {path}: {exc}") from exc


def save_config(project: Path, config: Config) -> None:
    path = project / "aivis.yaml"
    text = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    path.write_text(text, newline="\n")


def default_config(brand: str, competitors: list[str]) -> Config:
    return Config(brand=Brand(name=brand), competitors=[Brand(name=x) for x in competitors])


def get_key(data: Any, key: str) -> Any:
    for part in key.split("."):
        if isinstance(data, list):
            data = data[int(part)]
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            raise KeyError(key)
    return data


def set_key(config: Config, key: str, value: Any) -> Config:
    data = config.model_dump(mode="json")
    target: Any = data
    parts = key.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    leaf = parts[-1]
    old = target[int(leaf)] if isinstance(target, list) else target.get(leaf)
    parsed = yaml.safe_load(value) if isinstance(value, str) else value
    if isinstance(old, str) and not isinstance(parsed, str):
        parsed = str(value)
    if isinstance(target, list):
        target[int(leaf)] = parsed
    else:
        target[leaf] = parsed
    return Config.model_validate(data)
