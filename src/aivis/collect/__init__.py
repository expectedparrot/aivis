from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rich.console import Console

from ..config import APIEngine
from ..models import Counts, Prompt
from ..store import Store


@dataclass
class CollectorStats:
    counts: Counts


class Collector(Protocol):
    id: str

    def supports(self, engine_id: str) -> bool: ...
    def collect(
        self,
        prompts: list[Prompt],
        engines: list[APIEngine],
        n_samples: int,
        run_id: str,
        store: Store,
        console: Console,
    ) -> CollectorStats: ...
