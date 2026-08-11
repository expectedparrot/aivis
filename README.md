# aivis

aivis is a Python CLI that administers a prompt library to AI models, extracts tracked-brand observations with an EDSL judge, stores deterministic JSON time-series records, and reports share of voice, mention rate, recommendations, sentiment, and citation influence.

It can create and maintain a brand-measurement project, collect repeated API samples, re-extract immutable responses under versioned judge methods, and export analysis-ready CSV or nested JSON.

![A panel of AI agents answering a recommendation prompt around the EDSL parrot](assets/aivis-overview.png)

## Copy and paste into a coding agent

```text
Set up aivis and help me measure how my brand and competitors appear in AI answers.
Install it in a Python 3.11+ environment, then run `aivis version`,
`aivis capabilities`, `aivis guide`, and `aivis --help`. Initialize a project,
add representative prompts, and run `aivis run --dry-run` plus `aivis doctor`.
Show me the planned model-call count and stop for approval before paid inference.
Never print or commit API keys. After collection, preserve and commit
`.aivis/data/`, inspect `aivis report`, and export CSV for analysis.
```

## Install and quickstart

```bash
uv tool install --python 3.11 "aivis @ git+https://github.com/expectedparrot/aivis.git@main"
aivis version
aivis capabilities
aivis init --brand Upwork --competitors Fiverr,Toptal --no-generate
aivis prompts add "how do I hire a freelance developer" --cluster category
aivis configure --engines claude-sonnet-4-6 --samples-per-prompt 3
aivis run --dry-run
aivis doctor
aivis run
aivis --human report
aivis report-context --run last --out report-context.json
```

The default interface emits one JSON envelope to stdout; use `--human` for Rich tables. Project discovery walks upward from the current directory, or `--project PATH` selects one explicitly. Commit `.aivis/data/` after each run: new runs are additions, while versioned re-extraction produces narrow semantic changes.

New projects use EDSL remote inference through Expected Parrot by default, so
one `EXPECTED_PARROT_API_KEY` covers every configured engine and the judge.
Set `collection.remote: false` only when intentionally using direct provider
keys. `aivis run --dry-run` reports the selected inference mode and `aivis
doctor` validates the corresponding authentication path.

`report-context` creates one deterministic JSON handoff for a driving agent. It contains run coverage, reportability limits, metrics with denominators, engine and cluster slices, prompt-level outcomes, and exact response excerpts linked to stored sample files. It does not draft or render a narrative report.

## Measurement and cost caveats

API models are not consumer products: they may lack browsing, memory, personalization, and product-specific system instructions. Treat results as a proxy trend line, not a replica of a user's ChatGPT, Claude, or Gemini session.

Collection caching defaults off because repeated fresh answers are the data. Judge caching defaults on because deterministic re-reading should not be paid for twice. Collection calls equal prompts × engines × samples. Judge work is one first pass per successful sample plus framing only for brands found in that sample; `aivis extract --estimate` reports bounds.

Browser engines are a v3 milestone and remain disabled. Automated Google querying may violate Google's Terms of Service; aivis will not solve CAPTCHAs or evade bot detection.

The flat-file design targets roughly 1,800 samples per weekly run for two years. Keep `raw/` and `screenshots/` gitignored; use ordinary `git gc` and shallow clones if history grows large.

## Automation

```cron
0 8 * * 1 cd /srv/visibility && aivis run && git add .aivis/data && git commit -m "aivis weekly run"
```

In CI, run `aivis doctor`, then `aivis run`; commit and push `.aivis/data/` only after a successful run. Exit `1` denotes an operational failure. Threshold exit `2`, trend/diff, HTML, raw pruning, and Playwright collection are later milestones from `SPEC.md`.

See [SPEC.md](SPEC.md) for the complete schemas, metric definitions, and milestones.
