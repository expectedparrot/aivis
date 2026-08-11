from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_prompt(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def normalize_response(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def hash16(*parts: object) -> str:
    return hashlib.sha256("".join(str(p) for p in parts).encode()).hexdigest()[:16]


def prompt_id(text: str) -> str:
    return hash16(normalize_prompt(text))


def sample_id(run_id: str, prompt: str, engine: str, index: int) -> str:
    return hash16(run_id, prompt, engine, index)


def new_run_id() -> str:
    stamp = utc_now().replace(":", "-")
    return f"{stamp}-{secrets.token_hex(2)}"


def config_hash(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def normalize_domain(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^[a-z]+://", "", value).split("/", 1)[0].split(":", 1)[0]
    return value.removeprefix("www.").rstrip(".")


def find_project(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.name == ".aivis" and (current / "aivis.yaml").exists():
        return current
    for parent in (current, *current.parents):
        candidate = parent / ".aivis"
        if (candidate / "aivis.yaml").exists():
            return candidate
    raise FileNotFoundError("No .aivis project found; run 'aivis init --brand NAME' first")
