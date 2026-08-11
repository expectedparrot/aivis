from __future__ import annotations

import csv
from pathlib import Path

from .models import Prompt
from .store import Store
from .util import prompt_id, utc_now


def add_prompt(store: Store, text: str, cluster: str) -> tuple[Prompt, bool]:
    text = " ".join(text.split())
    if not text:
        raise ValueError("prompt text cannot be empty")
    if not cluster or (
        ":" not in cluster and cluster not in {"branded", "category", "comparison", "use_case"}
    ):
        raise ValueError(
            "cluster must be branded, category, comparison, use_case, or custom:<name>"
        )
    prompts = store.load_prompts(include_retired=True)
    pid = prompt_id(text)
    for index, existing in enumerate(prompts):
        if existing.prompt_id == pid:
            if not existing.active:
                existing = existing.model_copy(
                    update={"active": True, "retired_at": None, "cluster": cluster}
                )
                prompts[index] = existing
                store.write_prompts(prompts)
            return existing, False
    item = Prompt(prompt_id=pid, text=text, cluster=cluster, created_at=utc_now())
    store.write_prompts([*prompts, item])
    return item, True


def retire_prompt(store: Store, prefix: str) -> Prompt:
    prompts = store.load_prompts(include_retired=True)
    matches = [item for item in prompts if item.prompt_id.startswith(prefix)]
    if not matches:
        raise ValueError(f"unknown prompt ID: {prefix}")
    if len(matches) > 1:
        raise ValueError(f"ambiguous prompt ID {prefix}: {', '.join(x.prompt_id for x in matches)}")
    target = matches[0].model_copy(update={"active": False, "retired_at": utc_now()})
    store.write_prompts(
        [target if item.prompt_id == target.prompt_id else item for item in prompts]
    )
    return target


def import_csv(store: Store, path: Path) -> tuple[int, int]:
    added = duplicate = 0
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"text", "cluster"}.issubset(reader.fieldnames):
            raise ValueError("CSV must contain text and cluster columns")
        for row in reader:
            _, created = add_prompt(store, row["text"], row["cluster"])
            added += int(created)
            duplicate += int(not created)
    return added, duplicate
