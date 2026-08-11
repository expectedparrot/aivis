# aivis — AI Visibility Tracking CLI

**Technical Specification v1.1** **Status:** Ready for implementation **Target:** Python 3.11+, built on EDSL (`expectedparrot/edsl`), Playwright, flat-file JSON store, Typer, Rich

**Changelog v1.1:** Replaced SQLite with a git-friendly flat-file JSON store (§6). Storage layer, doctor checks, and tests updated accordingly. Everything else unchanged in substance.

---

## 1. Purpose and scope

`aivis` is a Python command-line tool that measures how a brand appears in AI-generated answers ("AI visibility" / GEO / AEO tracking). It repeatedly administers a library of realistic user prompts to a panel of AI answer engines, extracts structured observations from the responses (brand mentions, recommendations, sentiment, cited sources), stores them as a time series of flat JSON files, and reports metrics such as share of voice, mention rate, and citation-source influence — including diffs and threshold-based alerting suitable for cron/CI.

### 1.1 Design thesis

AI visibility measurement is survey research: prompts are questionnaire items, engines are respondents, and metrics are response distributions over repeated samples. EDSL is therefore the core execution engine for both:

1. **Collection** (where the engine is API-accessible): parameterized prompts (`ScenarioList`) × engines (`ModelList`) via EDSL.
2. **Extraction** (always): an LLM-as-judge pass implemented as an EDSL `Survey` of *typed* questions (`QuestionCheckBox`, `QuestionMultipleChoice`, `QuestionList`) over raw responses, which enforces output schema without hand-rolled JSON parsing.

A second design thesis follows from the storage choice: **the data store is a git-diffable artifact.** All state lives in deterministic, pretty-printed JSON files so that `git diff` between commits (or between runs) is itself a meaningful change report, and the entire measurement history can be versioned, reviewed, branched, and shared as a repository.

### 1.2 Important constraint (do not design around it incorrectly)

**EDSL does not drive Playwright.** EDSL is an LLM API survey framework; it has no browser automation capability. Surfaces without APIs (Google AI Overviews, Google AI Mode, optionally ChatGPT web UI) must be collected by a **separate Playwright-based collector**. Its scraped answers are normalized into the same raw-response record format and then flow into the same EDSL judge pass as API-collected answers. The architecture below encodes this as a collector plugin interface.

### 1.3 Non-goals

- No web dashboard or server. Terminal + exported files only.
- No content generation / optimization ("GEO writing"). Measurement only.
- No built-in scheduler. `aivis` is stateless per invocation; cron / GitHub Actions / launchd provide cadence. Exit codes support alerting.
- No attempt to defeat CAPTCHAs or aggressive bot walls. The Playwright collector must degrade gracefully and record failures honestly (see §7.3.5).
- No multi-tenant support. One project directory = one brand under study.
- No database engine of any kind (no SQLite, no DuckDB). If in-memory analysis needs richer querying, load JSON into pandas at read time; never persist derived state.

---

## 2. Terminology


| Term               | Meaning                                                                                                                                                                           |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Prompt**         | A realistic user query, e.g. "how do I hire a freelance developer".                                                                                                               |
| **Cluster**        | Prompt category: `branded`, `category`, `comparison`, `use_case` (extensible).                                                                                                    |
| **Engine**         | An answer surface being measured: an API model (`gpt-4o`, `claude-sonnet-4-6`, `gemini-2.5-flash`, `sonar` for Perplexity) or a browser surface (`google-aio`, `google-ai-mode`). |
| **Run**            | One scheduled collection+extraction execution, identified by `run_id`.                                                                                                            |
| **Sample**         | One (prompt, engine) response within a run. `runs_per_prompt` controls samples per (prompt, engine) per run.                                                                      |
| **Observation**    | One structured extraction result for one (sample, brand) pair.                                                                                                                    |
| **Tracked brands** | The focal brand plus configured competitors.                                                                                                                                      |
| **SOV**            | Share of voice: focal brand mentions ÷ all tracked-brand mentions, over a defined slice.                                                                                          |


---

## 3. Repository layout

```
aivis/
├── pyproject.toml              # package metadata; console_script: aivis = aivis.cli:app
├── README.md
├── src/aivis/
│   ├── __init__.py
│   ├── cli.py                  # Typer app; command definitions only, no business logic
│   ├── config.py               # pydantic models for aivis.yaml; load/validate/save
│   ├── store.py                # flat-file JSON store: schemas, atomic IO, loaders, lock
│   ├── models.py               # pydantic records shared across modules (serialization source of truth)
│   ├── prompts.py              # prompt library CRUD + LLM-assisted generation (EDSL)
│   ├── collect/
│   │   ├── __init__.py         # Collector protocol + registry
│   │   ├── edsl_collector.py   # API engines via EDSL
│   │   └── playwright_collector.py  # google-aio / google-ai-mode via Playwright
│   ├── extract.py              # EDSL judge survey; response → observations
│   ├── metrics.py              # pure functions: loaded records → metric values
│   ├── report.py               # Rich rendering: snapshot, trend, diff
│   ├── export.py               # csv/json/html export
│   └── util.py                 # ids, hashing, time, logging setup
├── tests/
│   ├── test_config.py
│   ├── test_store.py           # serialization determinism, atomicity, locking, idempotency
│   ├── test_prompts.py
│   ├── test_extract.py         # uses recorded fixtures, no live LLM calls
│   ├── test_metrics.py         # pure-function tests; the most important test file
│   ├── test_report.py
│   └── fixtures/               # canned raw responses + expected observations
└── .github/workflows/example-schedule.yml   # documented example, not required

```

Dependencies (pin major versions): `edsl`, `typer`, `rich`, `pydantic>=2`, `pyyaml`, `playwright`, `tenacity` (retries), `python-dateutil`, `filelock`. Dev: `pytest`, `pytest-asyncio`, `ruff`. Optional extra `[analysis]`: `pandas` (used only at read time by metrics/export when installed; core must work without it).

---

## 4. Project directory and initialization

`aivis init` scaffolds the working directory (the "project"):

```
.aivis/
├── aivis.yaml          # config (source of truth)
├── data/               # the flat-file store (§6) — designed to be committed to git
├── raw/                # bulky raw archives (full EDSL records, DOM snapshots) — gitignored
├── screenshots/        # Playwright evidence captures — gitignored
├── .gitignore          # generated: raw/, screenshots/, .lock
└── .lock               # filelock guard for write operations

```

All commands locate the project by walking up from CWD for `.aivis/` (git-style). `--project PATH` overrides. `init` is idempotent; it must refuse to overwrite an existing `aivis.yaml` without `--force`.

`init` runs an interactive wizard (skippable with flags): brand name, competitors, engines to enable, and whether to seed a starter prompt library via LLM generation (§5.2). Non-interactive: `aivis init --brand "Upwork" --competitors "Fiverr,Toptal" --no-generate`. If the enclosing directory is not a git repository, `init` prints a one-line suggestion to `git init` and commit `.aivis/` (excluding gitignored paths) so run-over-run diffs accrue automatically; it must not run git itself.

---

## 5. Configuration (`aivis.yaml`)

Validated with pydantic; unknown keys are an error. Full schema with defaults:

```yaml
version: 1
brand:
  name: "Upwork"                  # canonical display name
  aliases: ["Upwork.com"]         # strings the judge should treat as the same brand
competitors:
  - name: "Fiverr"
    aliases: []
  - name: "Toptal"
    aliases: []

engines:
  api:                            # collected via EDSL
    - id: "gpt-4o"                # EDSL model name
      enabled: true
    - id: "claude-sonnet-4-6"
      enabled: true
    - id: "gemini-2.5-flash"
      enabled: true
    - id: "sonar"                 # Perplexity; returns citations natively
      enabled: false
  browser:                        # collected via Playwright
    - id: "google-aio"            # Google AI Overviews on the SERP
      enabled: false
      locale: "en-US"
      geo: "us"
    - id: "google-ai-mode"
      enabled: false
      locale: "en-US"
      geo: "us"

sampling:
  runs_per_prompt: 3              # samples per (prompt, engine) per run
  temperature: null               # null = engine default; else applied to API engines

judge:
  model: "gpt-4o-mini"            # cheap model for extraction pass
  version: 1                      # bump when judge survey wording changes (§8.4)

collection:
  api_cache: false                # MUST default false: fresh samples each run (§7.2.3)
  judge_cache: true               # judge calls are deterministic → cache aggressively
  timeout_seconds: 120
  max_concurrency: 8              # EDSL-side; Playwright collector runs serially
  retries: 2

playwright:
  headless: true
  slow_mo_ms: 0
  min_delay_seconds: 8            # randomized delay between queries (8–2x this value)
  screenshot: true                # save full-page screenshot per sample
  storage_state: null             # optional path to a logged-in browser state file

reporting:
  default_weeks: 8
  fail_threshold_sov_drop: null   # e.g. 5.0 → exit 2 if SOV drops ≥5 pts vs prior run

```

`aivis config set KEY VALUE`, `aivis config get KEY`, `aivis config competitors add NAME`, `aivis config competitors rm NAME` edit the file safely (round-trip YAML, preserve comments if practical; otherwise rewrite is acceptable).

API keys are **never** stored in `aivis.yaml`. Remote inference is the default
and uses EDSL's `EXPECTED_PARROT_API_KEY`; direct provider keys
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, etc.) are needed only
when `collection.remote: false`. `aivis doctor` (§9.8) validates the selected
authentication path without exposing key values.

---

## 6. Data model (flat-file JSON store)

### 6.1 Rationale and principles

The store is a directory tree of JSON documents, designed so that version-control diffs are the primary change-inspection mechanism:

1. **One file per logical unit** at the granularity where change happens: one file per sample, one file per sample's observations. A new run adds files (pure additions in `git diff`); re-extraction changes only the observation files it touches.
2. **Deterministic serialization.** Every file is written with `sort_keys=True`, `indent=2`, `ensure_ascii=False`, LF line endings, and a trailing newline. Serializing the same logical record twice must produce byte-identical output. All serialization goes through a single `store.write_json()`; nothing else in the codebase calls `json.dump`.
3. **Atomic writes.** Write to `<path>.tmp` in the same directory, `fsync`, `os.rename`. A crash never leaves a torn file.
4. **Single-writer locking.** Mutating commands acquire `.aivis/.lock` (via `filelock`, 30s timeout, clear error message on contention). Read-only commands (`report`, `diff`, `export`, `prompts list`) do not take the lock.
5. **Self-describing files.** Every file carries `"schema": <int>` (per-file-type schema version) so future migrations can upgrade lazily on read, rewriting files only when they are next written.
6. **No derived state on disk.** No indexes, no caches of computed metrics. Everything reportable is recomputed from the files at read time. (At the expected scale — see §6.7 — this is fast.)
7. **Stable IDs, stable ordering.** IDs are content hashes or run-scoped hashes (below). Any JSON array whose order is not semantically meaningful is sorted by a stable key before writing, so diffs never churn from ordering.

### 6.2 Directory layout

```
data/
├── prompts.json                          # the whole prompt library, one file
└── runs/
    └── <run_id>/                         # e.g. 2026-08-11T14-30-00Z-a1b2
        ├── run.json                      # run manifest
        ├── samples/
        │   └── <engine>/                 # one subdir per engine keeps dirs small
        │       └── <sample_id>.json
        └── observations/
            └── v<judge_version>/
                └── <engine>/
                    └── <sample_id>.json  # ALL brands' observations for that sample

```

`run_id` format: UTC timestamp to the second with `:` replaced by `-`, plus 4 hex chars of randomness: `2026-08-11T14-30-00Z-a1b2`. Lexicographic order of `run_id` = chronological order; loaders may rely on this.

### 6.3 File schemas

`data/prompts.json` — array sorted by `prompt_id`. Prompts are append-mostly; retiring sets `retired_at` rather than deleting, so historical runs stay attributable and the diff shows a two-line change, not a removal.

```json
{
  "schema": 1,
  "prompts": [
    {
      "prompt_id": "3f9a2c8e01b4d7f2",
      "text": "how do I hire a freelance developer",
      "cluster": "category",
      "active": true,
      "created_at": "2026-08-11T14:00:00Z",
      "retired_at": null
    }
  ]
}

```

`prompt_id` = `sha256(normalized_text)[:16]`, where normalization is lowercase + collapsed whitespace. Re-importing an existing prompt is a no-op.

`runs/<run_id>/run.json` — manifest, written at run start and finalized at run end:

```json
{
  "schema": 1,
  "run_id": "2026-08-11T14-30-00Z-a1b2",
  "started_at": "2026-08-11T14:30:00Z",
  "finished_at": "2026-08-11T14:41:22Z",
  "status": "complete",
  "config_hash": "sha256:…",
  "config_snapshot": { "…resolved config used for this run…": "…" },
  "plan": { "prompts": 25, "engines": ["gpt-4o", "claude-sonnet-4-6"], "samples_per_prompt": 3 },
  "counts": { "ok": 148, "error": 2, "not_present": 0, "blocked": 0 },
  "notes": null
}

```

`status` ∈ `running | complete | partial | failed`. `config_snapshot` embeds the resolved config (minus secrets, which are never in config anyway) so a run is fully interpretable even if `aivis.yaml` later changes — and so `git diff` on a run directory shows exactly what settings changed between runs.

`runs/<run_id>/samples/<engine>/<sample_id>.json` — one raw engine response. Immutable after the run finishes; extraction never touches these.

```json
{
  "schema": 1,
  "sample_id": "8c1d44aa90e2f3b7",
  "run_id": "2026-08-11T14-30-00Z-a1b2",
  "prompt_id": "3f9a2c8e01b4d7f2",
  "engine": "gpt-4o",
  "sample_index": 0,
  "collected_at": "2026-08-11T14:30:41Z",
  "collector": "edsl",
  "status": "ok",
  "response_text": "…full normalized answer text…",
  "citations": [
    { "url": "https://www.reddit.com/r/freelance/…", "domain": "reddit.com", "title": null, "source": "native" }
  ],
  "raw_ref": "raw/2026-08-11T14-30-00Z-a1b2/8c1d44aa90e2f3b7.json.gz",
  "error": null
}

```

`sample_id` = `sha256(run_id + prompt_id + engine + sample_index)[:16]` — deterministic, so re-attempting a failed sample within the same run overwrites its file rather than duplicating. `status` semantics: `not_present` = surface loaded but no AI answer shown for this query (common for AI Overviews); `blocked` = bot wall / CAPTCHA. Both are real data — report them. `citations[].source` is `native` here; judge-derived domains live in the observation file (§ below), keeping the immutability rule clean.

`runs/<run_id>/observations/v<N>/<engine>/<sample_id>.json` — the judge's structured reading of one sample, all tracked brands together. Rewritten atomically as a whole on (re-)extraction, which makes a re-extraction diff exactly the semantic change:

```json
{
  "schema": 1,
  "sample_id": "8c1d44aa90e2f3b7",
  "judge_version": 1,
  "judge_model": "gpt-4o-mini",
  "extracted_at": "2026-08-11T14:39:02Z",
  "brands": [
    {
      "brand": "Upwork",
      "mentioned": true,
      "framing": "recommended",
      "first_position": 1
    },
    {
      "brand": "Fiverr",
      "mentioned": true,
      "framing": "neutral",
      "first_position": 2
    },
    {
      "brand": "Toptal",
      "mentioned": false,
      "framing": "not_mentioned",
      "first_position": null
    }
  ],
  "judged_domains": ["g2.com", "reddit.com"]
}

```

`brands` sorted by canonical brand name; `judged_domains` sorted alphabetically (registrable domain, lowercase, `www.` stripped). `framing` ∈ `recommended | neutral | negative | not_mentioned`.

### 6.4 Store API (`store.py`)

Expose typed loaders/writers; the rest of the codebase never touches paths or `json` directly:

```python
class Store:
    # writes (require lock)
    def write_prompts(self, prompts: list[Prompt]) -> None: ...
    def start_run(self, plan: RunPlan, config: ResolvedConfig) -> RunManifest: ...
    def write_sample(self, sample: Sample) -> None: ...
    def write_observations(self, obs: SampleObservations) -> None: ...
    def finalize_run(self, run_id: str, status: str, counts: Counts) -> None: ...
    # reads (no lock)
    def load_prompts(self, include_retired: bool = False) -> list[Prompt]: ...
    def list_runs(self) -> list[RunManifest]: ...          # sorted by run_id
    def load_run(self, run_id: str) -> RunManifest: ...
    def iter_samples(self, run_id: str, engines: list[str] | None = None) -> Iterator[Sample]: ...
    def load_observations(self, run_id: str, judge_version: int | None = None,
                          engines: list[str] | None = None) -> list[SampleObservations]: ...
    def latest_judge_version(self, run_id: str) -> int | None: ...
    def missing_observations(self, run_id: str, judge_version: int) -> list[Sample]: ...

```

Pydantic models in `models.py` are the single source of truth for file schemas; `store.write_json()` serializes `model.model_dump()` under the determinism rules of §6.1. Loaders validate on read and raise a clear error naming the offending file path.

### 6.5 Idempotency and immutability rules

- Samples are immutable once their run is finalized. The only legal post-finalization writes under `runs/<run_id>/` are new or replaced observation files and the `run.json` `status`/`counts` fields during `finalize`.
- Extraction is idempotent per (sample, judge_version): rewriting an observation file with unchanged inputs must produce a byte-identical file (guaranteed by deterministic serialization), i.e. a no-op in git.
- Adding a competitor then re-extracting at the same judge version rewrites observation files with one added element per `brands` array — a clean, reviewable diff.

### 6.6 Integrity checking

`aivis doctor` (§9.8) includes a store fsck: every sample file parses and validates; every observation file references an existing sample; `run.json` counts match on-disk sample statuses; no orphaned `.tmp` files; ID hashes verify against file contents. `--fix` may delete orphaned `.tmp` files and recompute manifest counts; it never deletes data files.

### 6.7 Scale envelope and performance budget

Design target: 100 prompts × 6 engines × 3 samples = 1,800 samples/run; weekly runs for 2 years ≈ 190k sample files + 190k observation files. Requirements: `aivis report` (single run) loads only that run's directory and completes in <2s on that envelope; `aivis report --trend` loads manifests for all runs plus observations for the selected window only. Daily runs at larger prompt sets will produce large trees — document in the README that git handles this fine (many small text files) but that `git gc` and shallow clones are the user's tools, and that `raw/` and `screenshots/` must stay gitignored.

### 6.8 Raw archives (unchanged)

`raw/` holds bulky, non-diffable artifacts: full EDSL result records and Playwright DOM snapshots, gzip'd, named by `sample_id` under a per-run subdirectory. `samples.raw_ref` points to them. Gitignored. `aivis vacuum --older-than 90d` prunes `raw/` and `screenshots/` only — never `data/`.

---

## 7. Collection

### 7.1 Collector plugin interface

```python
class Collector(Protocol):
    id: str  # "edsl" | "playwright"
    def supports(self, engine_id: str) -> bool: ...
    def collect(
        self,
        prompts: list[Prompt],
        engines: list[EngineConfig],
        n_samples: int,
        run_id: str,
        store: Store,
        console: Console,
    ) -> CollectorStats: ...   # writes sample files itself; returns counts for the run summary

```

Registry maps engine ids to collectors from config (`engines.api` → edsl, `engines.browser` → playwright). Adding a future collector (e.g. a SERP API vendor) means implementing this protocol only — metrics/report layers never know the origin beyond `sample.collector`.

### 7.2 EDSL collector (API engines)

#### 7.2.1 Execution

Build once per run:

```python
q = QuestionFreeText(question_name="response", question_text="{{ scenario.prompt }}")
scenarios = ScenarioList([...])       # one per (prompt, sample_index); include prompt_id
                                      # and sample_index as scenario fields for join-back
models = ModelList(Model(e.id) for e in api_engines)
results = q.by(scenarios).by(models).run(cache=False, disable_remote_inference=<per config>)

```

Implementation notes:

- To get `runs_per_prompt` distinct samples, duplicate each prompt into N scenarios distinguished by a `sample_index` scenario field. This also defeats any within-run response caching keyed on identical inputs.
- Map EDSL result rows back to `(prompt_id, engine, sample_index)` via the scenario fields and `model.model`; never rely on row order.
- Per-question failures in EDSL must not abort the run: write `status='error'` sample files with the error string and continue. Run `status` becomes `partial` if any sample failed.
- If the `sonar` (Perplexity) engine returns citations in the response metadata, capture them into the sample's `citations` array with `source='native'`.

#### 7.2.2 What API collection measures (documentation requirement)

API models ≠ consumer products (no browsing/memory/personalization). The README and report footers must state this: results are a proxy trend line, not a replica of what a ChatGPT user sees. This mirrors the standard limitation of commercial tools' API modes.

#### 7.2.3 Caching policy (critical)

EDSL caches LLM calls by default, which is *wrong* for collection (we want fresh samples every run) and *right* for judging (identical inputs → cache hit saves money). Therefore: collection runs with `cache=False` (or a per-run cache namespace that is never reused); the judge pass runs with caching enabled. `collection.api_cache` / `collection.judge_cache` expose this; tests must assert the defaults.

### 7.3 Playwright collector (browser engines)

#### 7.3.1 Surfaces

- `google-aio`: load `https://www.google.com/search?q=<prompt>&hl=<locale>&gl=<geo>`, detect an AI Overview block; if present, expand ("Show more") and extract its text and its source links.
- `google-ai-mode`: navigate to Google AI Mode, submit the prompt, wait for the streamed answer to settle, extract answer text and cited links.

Selectors for these surfaces churn. **Isolate all selectors/heuristics in a single module-level** `SELECTORS` **structure** with versioned fallback chains, and prefer resilient strategies (ARIA roles, text anchors like the "AI Overview" heading) over brittle CSS paths. Every extraction failure with a loaded page must save a screenshot and DOM snapshot to `screenshots/` for post-hoc selector repair.

#### 7.3.2 Behavior

- Serial execution, randomized inter-query delay: `uniform(min_delay_seconds, 2 * min_delay_seconds)`.
- Fresh browser context per sample by default; if `playwright.storage_state` is set, reuse that authenticated/consented state (also the escape hatch for the EU consent wall: user records a consented state once via `aivis browser login`, a helper command that opens a headed browser and saves `storage_state` on close).
- `not_present` (no AI answer shown) is a first-class outcome, recorded and reported — the *rate* at which AI Overviews appear for your prompt set is itself a metric users care about.
- `blocked` (CAPTCHA/bot wall) likewise. If >50% of a browser engine's samples in a run are `blocked`, print a prominent warning and mark the run `partial`.
- Respect `--engines` filtering; browser engines are off by default in config to keep v1 friction low.

#### 7.3.3 Legal/ToS note (README requirement)

Automated querying of Google may violate its Terms of Service. The README must say this plainly, note that the feature is off by default, and leave the decision to the user. `aivis` must not implement CAPTCHA solving or bot-detection evasion beyond honest, low-rate, human-paced querying.

#### 7.3.4 Normalization

Playwright output is normalized to the same sample record: answer text, native citations (`source='native'`), screenshot ref in `raw_ref`. Downstream, the judge pass treats these samples identically to API samples.

#### 7.3.5 Failure honesty

Never fabricate or silently skip. Every attempted (prompt, engine, sample_index) yields exactly one sample file with an accurate `status`.

### 7.4 Run orchestration (`aivis run`)

1. Acquire the project lock; create the run directory and `run.json` (`status='running'`, `config_hash`, `config_snapshot`).
2. Resolve active prompts (`--cluster`, `--sample N` for a random subset, `--engines` filters).
3. Dispatch to collectors (EDSL first, then Playwright), streaming progress with Rich (per-engine progress bars; live counts of ok/error/not_present/blocked).
4. Unless `--no-extract`, run extraction (§8) for the run.
5. Finalize `run.json`; print run summary; if `reporting.fail_threshold_sov_drop` is set and breached vs. the previous complete run, exit 2 (§9.7).

`--dry-run` prints the resolved plan (prompt count × engine count × samples, estimated API call count for collection and judging) and exits 0 without collecting or creating any files.

---

## 8. Extraction (LLM-as-judge via EDSL)

### 8.1 Judge survey

For each sample with `status='ok'`, build scenarios containing `response`, the tracked-brand list (canonical names + aliases), and run an EDSL `Survey`:

```python
brands_display = [b.render() for b in tracked_brands]   # "Upwork (aka Upwork.com)"

q_mentioned = QuestionCheckBox(
    question_name="mentioned",
    question_text=(
        "Which of these brands are mentioned anywhere in the response below, "
        "including via their aliases?\n\nRESPONSE:\n{{ scenario.response }}"
    ),
    question_options=brands_display + ["None of these"],
)

q_order = QuestionList(
    question_name="mention_order",
    question_text=(
        "List the mentioned tracked brands in the order they first appear "
        "in the response. Use canonical names only.\n\nRESPONSE:\n{{ scenario.response }}"
    ),
)

q_framing = QuestionMultipleChoice(          # asked once per (sample, mentioned brand),
    question_name="framing",                 # via brand-parameterized scenarios
    question_text=(
        "How is {{ scenario.brand }} framed in this response?\n\n"
        "RESPONSE:\n{{ scenario.response }}"
    ),
    question_options=[
        "Recommended — presented as the answer or a top choice",
        "Neutral mention — named without endorsement",
        "Negative — criticized, cautioned against, or unfavorably compared",
    ],
)

q_domains = QuestionList(
    question_name="cited_domains",
    question_text=(
        "List any website domains this response cites, links, or names as "
        "sources (e.g. reddit.com, g2.com). Empty list if none.\n\n"
        "RESPONSE:\n{{ scenario.response }}"
    ),
)

```

Judge runs on `judge.model` with `cache=True`. Pipeline: first pass (mentioned + order + domains) over all ok samples; second pass (framing) only over (sample, brand) pairs where the brand was mentioned. Brands not mentioned get a `brands` entry with `mentioned=false, framing='not_mentioned'`. Results for one sample are assembled into a single `SampleObservations` record and written as one file (§6.3).

### 8.2 Post-processing

- Map judge outputs (which may use aliases or minor misspellings) back to canonical brand names with case-insensitive alias matching; log unmapped names at debug level.
- `first_position`: 1-based index in `mention_order`, restricted to tracked brands.
- Judged domains are normalized (registrable domain, lowercase, `www.` stripped), deduped against the sample's native citations, and stored in the observation file's `judged_domains`. **Native citations override judged ones** where both exist for a sample; the report layer prefers `native`.

### 8.3 Cost control

Judging is the dominant marginal cost at scale. Requirements: batch via EDSL's natural fan-out (do not loop single calls); caching on; `aivis extract --estimate` prints projected call counts before running; second-pass framing questions only for mentioned brands.

### 8.4 Judge versioning

Any change to judge question wording, options, or model bumps `judge.version`. Observation files live under `observations/v<N>/`, so versions coexist on disk; reports use the highest version available per run and warn when a queried range mixes versions. `aivis extract --run all --judge-version N` re-extracts history after a bump (immutable raw samples make this cheap and safe), and the resulting git diff — new `v<N>/` trees alongside old ones — documents the methodology change.

---

## 9. CLI reference

Framework: Typer. Global flags: `--project PATH`, `--verbose/-v`, `--quiet/-q`, `--format table|json` (json = machine-readable to stdout, logs to stderr). Every command must work non-interactively.

### 9.1 `aivis init`

Scaffold project (§4). Flags: `--brand`, `--competitors CSV`, `--no-generate`, `--force`.

### 9.2 `aivis prompts`

```
aivis prompts add TEXT --cluster CLUSTER
aivis prompts list [--cluster C] [--all]        # --all includes retired
aivis prompts rm PROMPT_ID                      # soft-retire
aivis prompts import FILE.csv                   # columns: text,cluster
aivis prompts export [--format csv|json]
aivis prompts generate --n 30 [--cluster C] [--topic "hiring freelancers"]

```

`generate` uses EDSL (`QuestionList` on the judge model) seeded with brand, competitors, and cluster definitions to propose realistic user phrasings; proposals are printed and require `--yes` or interactive confirmation before insertion. Generated prompts must vary in specificity, phrasing formality, and intent (informational vs. transactional vs. comparative).

### 9.3 `aivis run`

Flags: `--engines CSV`, `--cluster CSV`, `--sample N`, `--dry-run`, `--no-extract`, `--notes TEXT`.

### 9.4 `aivis extract`

Flags: `--run RUN_ID|last|all`, `--estimate`, `--judge-version N`. Extracts any ok samples lacking an observation file at the current (or given) judge version (via `store.missing_observations`).

### 9.5 `aivis report`

```
aivis report                     # snapshot of last complete run
aivis report --run RUN_ID
aivis report --trend --weeks 8   # per-run time series
aivis report --cluster category  # slice any report by cluster and/or --engines

```

Snapshot contents (Rich tables):

1. Header: run id/date, prompts × engines × samples, ok/error/not_present/blocked counts.
2. **Share of voice** table: per tracked brand — SOV %, mention rate %, recommendation rate %, avg first-position; focal brand highlighted; per-engine breakdown beneath.
3. **Sentiment mix** for focal brand: recommended/neutral/negative distribution overall and per engine.
4. **Citation leaderboard**: top 15 domains by sample count, with a column marking domains where the focal brand was mentioned in the same sample vs. not ("carries you" vs. "carries competitors").
5. AI-answer presence rate per browser engine (share of prompts where the surface showed an AI answer), when browser engines ran.
6. Footer: proxy-measurement caveat (§7.2.2); judge version; volatility note if applicable.

Trend view: one row per run — SOV, mention rate, recommendation rate, presence rate — with Rich sparklines per metric, plus a volatility column (§10.6).

### 9.6 `aivis diff`

```
aivis diff                              # last two complete runs
aivis diff --from RUN_OR_DATE --to RUN_OR_DATE

```

Shows metric deltas (SOV, mention rate, recommendation rate, sentiment mix) overall, per cluster, and per engine; brands gaining/losing share; domains entering/leaving the citation leaderboard; prompts whose focal-brand outcome flipped (mentioned→not, recommended→neutral, etc.), listed explicitly — these are the actionable units. This is the *semantic* diff; users can additionally `git diff` the run directories for the raw record-level view, and the README should show both side by side.

### 9.7 Exit codes and alerting

`0` success; `1` operational error (config invalid, collectors failed entirely); `2` threshold breach: `run`/`diff` exit 2 when `reporting.fail_threshold_sov_drop` is configured and the focal brand's overall SOV fell by at least that many points vs. the comparison run. This makes cron/CI alerting trivial. `--fail-threshold X` overrides config per invocation.

### 9.8 `aivis doctor`

Environment check: EDSL importable and version; which API keys are present (name only, never values); Playwright browsers installed (offer `playwright install chromium` hint); config validates; store fsck per §6.6 (`--fix` for safe repairs). Exit 1 if anything required for enabled engines is missing or the store is corrupt.

### 9.9 `aivis export`

`aivis export --format csv|json|html [--run RUN_ID|all] [--out PATH]`

- `csv`: three files (samples, observations flattened to one row per (sample, brand), citations) — analysis-ready.
- `json`: nested run → samples → observations document (a materialized join of the store, for consumers who don't want to walk the tree).
- `html`: single self-contained file mirroring the snapshot report (inline CSS, no JS deps required; simple tables + the same numbers).

### 9.10 `aivis browser login`

Opens a headed Chromium; user resolves consent/login manually; on window close, saves `storage_state` and writes its path into config (§7.3.2).

### 9.11 `aivis vacuum`

`--older-than 90d`: prune `raw/` archives and `screenshots/` (never anything under `data/`).

---

## 10. Metrics (definitions — implement in `metrics.py` as pure functions over loaded records)

All metrics accept a slice filter (run(s), cluster(s), engine(s), brand). Denominators exclude samples with `status != 'ok'` unless stated. Percentages reported to 1 decimal.

**10.1 Mention rate(brand)** = mentioned samples ÷ ok samples.

**10.2 Recommendation rate(brand)** = samples with framing `recommended` ÷ ok samples. (Not ÷ mentioned samples — we want "share of all answers where you're the recommendation." Also expose the conditional variant `rec_given_mention` in exports.)

**10.3 Share of voice(brand)** = brand's mentioned-sample count ÷ Σ over tracked brands of mentioned-sample counts, within the slice. If the denominator is 0, SOV is undefined (render "—", never 0).

**10.4 Avg first position(brand)** = mean of `first_position` over samples where mentioned.

**10.5 Presence rate(browser engine)** = samples with status `ok` ÷ samples with status in (`ok`,`not_present`).

**10.6 Volatility(brand)** = for prompts sampled in both of two consecutive runs, the share whose focal-brand outcome (mentioned y/n) differs between runs, computed per engine and averaged. High volatility contextualizes small SOV moves as possibly noise; the trend report prints it alongside deltas.

**10.7 Citation influence(domain)** = ok samples citing the domain, split by whether the focal brand was mentioned in those samples.

**Small-sample guard:** any table cell whose denominator is <20 samples is rendered with a `†` marker and a single footnote ("small sample — directional only"). Metrics functions return `(value, n)` pairs so the report layer can do this.

---

## 11. Error handling, retries, logging

- Transient API errors: retry with exponential backoff (tenacity), max `collection.retries`, then write a `status='error'` sample file.
- A run is `complete` only if every planned sample has status `ok` or `not_present`; else `partial`. `failed` only when no sample files were written.
- Ctrl-C: finalize the run as `partial` cleanly (sample files written so far are kept; extraction can be run later). The atomic-write rule (§6.1) guarantees no torn files on interrupt.
- Logging via stdlib `logging`, Rich handler at INFO for humans; `--verbose` = DEBUG including per-sample outcomes; `--format json` routes logs to stderr.
- Never print API keys or other users' data in errors. Store-validation errors always name the offending file path.

## 12. Testing requirements

- `metrics.py` is pure and must reach ~100% branch coverage, including denominators of zero, mixed judge versions, small-sample flags, and volatility on partially-overlapping prompt sets.
- `store.py` tests: byte-identical re-serialization of identical records (write, load, write → same bytes); atomicity under injected failure between tmp-write and rename; lock contention error message; schema-validation error naming the file; idempotent re-extraction producing a no-op file write; loader behavior with a hand-corrupted file present.
- Extraction tests run against recorded fixtures (canned response texts → expected observation files) with the EDSL call boundary mocked; no network in CI. Golden-file comparisons are exact byte comparisons, leveraging deterministic serialization.
- Playwright collector: unit-test the DOM-extraction functions against saved HTML fixtures for AIO-present, AIO-absent, and consent-wall pages; live browser tests are opt-in (`pytest -m live`).
- CLI smoke tests via Typer's `CliRunner`: init → prompts add → run --dry-run → report on a fixture-seeded store tree.

## 13. Documentation requirements (README)

Quickstart (init → add prompts → run → report); the API-vs-product proxy caveat; the Google ToS note; the caching rationale; the git workflow (commit `data/` after each run; example of reading a run-over-run `git diff` next to `aivis diff` output); a cron and a GitHub Actions example using exit-code alerting (including a job step that commits and pushes `data/` after a successful run); cost estimation guidance (rule of thumb: collection calls = prompts × engines × samples; judge calls ≈ ok samples × 2 passes ÷ cache hits); scale notes from §6.7.

## 14. Milestones

**v1 (MVP):** init, config, prompts (add/list/rm/import), EDSL collector, extraction, flat-file store with determinism/atomicity/locking guarantees, snapshot report, doctor (incl. fsck), csv/json export, exit codes. No Playwright, no trend/diff. Definition of done: a user with OpenAI+Anthropic keys can measure SOV for a brand vs. 3 competitors across 25 prompts × 2 engines × 3 samples in one command after setup, in under 10 minutes — and committing `.aivis/data/` after two runs yields a readable git diff consisting purely of added files.

**v2:** trend + diff reports, volatility, threshold alerting, prompts generate, html export, vacuum, raw archives.

**v3:** Playwright collector (google-aio, then google-ai-mode), browser login helper, presence-rate metric, screenshot evidence, selector-fixture test suite.

## 15. Open questions (implementer may decide; document choices)

1. EDSL remote inference (Expected Parrot server) is the default. Set
   `collection.remote: false` explicitly for local provider keys.
2. Perplexity citation metadata shape via EDSL — verify what the `sonar` result rows expose; if citations aren't accessible through EDSL results, either call Perplexity's API directly in a small adapter within the EDSL collector, or defer native citations for that engine to v2.
3. Exact Google AI Mode entry URL/flow at implementation time — selectors module owns this; expect churn.
4. Whether `response_text` should be stored with normalized line endings only, or also unicode-normalized (NFC), to maximize diff stability across engines that vary whitespace. Recommendation: LF normalization + NFC, applied identically in the collector and documented.
