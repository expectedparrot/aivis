from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


CREDENTIAL_KEYS = (
    "EXPECTED_PARROT_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


def find_local_env(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_local_env(start: Path | None = None) -> dict[str, Any]:
    path = find_local_env(start)
    loaded: list[str] = []
    if path:
        for key, value in dotenv_values(path).items():
            if key and value is not None and key not in os.environ:
                os.environ[key] = str(value)
                loaded.append(key)
    return {
        "path": str(path) if path else None,
        "loaded_keys": sorted(key for key in loaded if key in CREDENTIAL_KEYS),
        "present_keys": sorted(key for key in CREDENTIAL_KEYS if os.environ.get(key)),
    }
