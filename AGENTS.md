# aivis repository operating contract

Use `aivis guide`, `aivis capabilities`, and command `--help` as the workflow source of truth.

- Develop with Python 3.11+; run `python -m compileall -q src`, `pytest -q`, `ruff check .`, and `git diff --check`.
- Keep business logic outside `cli.py`; Pydantic records in `models.py` are the serialization source of truth.
- Only `store.write_json()` may serialize store JSON. Preserve deterministic formatting, atomic replacement, stable IDs, and locking.
- Never mutate finalized sample files. Observation versions coexist and may be re-extracted.
- Never print, inspect, serialize, or commit API keys. `.aivis/raw/`, `.aivis/screenshots/`, and `.aivis/.lock` stay uncommitted.
- Treat provider responses as potentially private. Do not publish them without authorization.
- Live model calls incur cost. Run `aivis run --dry-run` and `aivis doctor` first and obtain approval when authority is not explicit.
- Keep tests offline. Mock the EDSL boundary; mark future browser integration tests `live`.
