from __future__ import annotations

import importlib.metadata
import json
import os
import random
from pathlib import Path
from typing import Any

import typer
from edsl import Coop
from rich.console import Console

from . import __version__
from .collect.edsl_collector import EDSLCollector
from .config import (
    Brand,
    configure_collection,
    default_config,
    get_key,
    load_config,
    save_config,
    set_key,
)
from .environment import load_local_env
from .export import export_csv, export_json
from .extract import extract_run
from .models import RunPlan
from .prompts import add_prompt, import_csv, retire_prompt
from .report import render_snapshot, snapshot_data
from .report_context import write_report_context
from .store import Store
from .util import find_project

app = typer.Typer(no_args_is_help=True, help="Measure brand visibility in AI-generated answers.")
prompts_app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
competitors_app = typer.Typer(no_args_is_help=True)
app.add_typer(prompts_app, name="prompts")
app.add_typer(config_app, name="config")
config_app.add_typer(competitors_app, name="competitors")


class State:
    project: Path | None = None
    output_format: str = "json"
    human: bool = False


state = State()
stdout = Console()
stderr = Console(stderr=True)


def emit(
    command: str,
    data: Any = None,
    warnings: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> None:
    stdout.print_json(
        data={
            "status": "warning" if warnings else "ok",
            "command": command,
            "data": data or {},
            "warnings": warnings or [],
            "errors": [],
            "next_steps": next_steps or [],
        }
    )


def fail(command: str, code: str, message: str) -> None:
    stdout.print_json(
        data={
            "status": "error",
            "command": command,
            "data": {},
            "warnings": [],
            "errors": [{"code": code, "message": message}],
            "next_steps": [],
        }
    )
    raise typer.Exit(1)


def project_path() -> Path:
    try:
        return find_project(state.project)
    except FileNotFoundError as exc:
        fail("aivis", "project_not_found", str(exc))
        raise


@app.callback()
def main(
    project: Path | None = typer.Option(None, "--project"),
    output_format: str = typer.Option("json", "--format", help="json or table"),
    human: bool = typer.Option(False, "--human", help="Render human-readable tables."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    load_local_env()
    state.project, state.output_format, state.human = (
        project,
        output_format,
        human or output_format == "table",
    )


@app.command("version")
def version_cmd() -> None:
    emit("aivis version", {"version": __version__})


@app.command()
def init(
    brand: str = typer.Option(..., "--brand"),
    competitors: str = typer.Option("", "--competitors"),
    no_generate: bool = typer.Option(True, "--no-generate/--generate"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    base = (state.project or Path.cwd()).resolve()
    project = base if base.name == ".aivis" else base / ".aivis"
    config_path = project / "aivis.yaml"
    if config_path.exists() and not force:
        fail("aivis init", "project_exists", f"Refusing to overwrite {config_path}; pass --force")
    project.mkdir(parents=True, exist_ok=True)
    config = default_config(brand, [x.strip() for x in competitors.split(",") if x.strip()])
    save_config(project, config)
    (project / "raw").mkdir(exist_ok=True)
    (project / "screenshots").mkdir(exist_ok=True)
    (project / ".gitignore").write_text("raw/\nscreenshots/\n.lock\n", newline="\n")
    store = Store(project)
    with store.locked():
        store.initialize()
    warning = (
        []
        if any((p / ".git").exists() for p in (base, *base.parents))
        else ["Not inside a git repository; consider 'git init' and commit .aivis/data/."]
    )
    emit(
        "aivis init",
        {"project": str(project), "brand": brand},
        warning,
        [
            f"cd {base}",
            "aivis prompts add 'your customer question' --cluster category",
            "aivis run --dry-run",
        ],
    )


@prompts_app.command("add")
def prompts_add(text: str, cluster: str = typer.Option(..., "--cluster")) -> None:
    store = Store(project_path())
    with store.locked():
        item, created = add_prompt(store, text, cluster)
    emit("aivis prompts add", {"prompt": item.model_dump(mode="json"), "created": created})


@prompts_app.command("list")
def prompts_list(
    cluster: str | None = typer.Option(None, "--cluster"), all_: bool = typer.Option(False, "--all")
) -> None:
    items = Store(project_path()).load_prompts(include_retired=all_)
    if cluster:
        items = [x for x in items if x.cluster == cluster]
    emit("aivis prompts list", {"prompts": [x.model_dump(mode="json") for x in items]})


@prompts_app.command("rm")
def prompts_rm(prompt: str) -> None:
    store = Store(project_path())
    with store.locked():
        item = retire_prompt(store, prompt)
    emit("aivis prompts rm", {"prompt": item.model_dump(mode="json")})


@prompts_app.command("import")
def prompts_import(path: Path) -> None:
    store = Store(project_path())
    with store.locked():
        added, duplicates = import_csv(store, path)
    emit("aivis prompts import", {"added": added, "duplicates": duplicates})


@prompts_app.command("export")
def prompts_export(format_: str = typer.Option("json", "--format")) -> None:
    items = Store(project_path()).load_prompts(include_retired=True)
    if format_ == "json":
        emit("aivis prompts export", {"prompts": [x.model_dump(mode="json") for x in items]})
    else:
        stdout.print("text,cluster")
        for item in items:
            stdout.print(f"{json.dumps(item.text)},{json.dumps(item.cluster)}")


@config_app.command("get")
def config_get(key: str) -> None:
    config = load_config(project_path())
    emit("aivis config get", {"key": key, "value": get_key(config.model_dump(mode="json"), key)})


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    project = project_path()
    config = set_key(load_config(project), key, value)
    store = Store(project)
    with store.locked():
        save_config(project, config)
    emit("aivis config set", {"key": key, "value": get_key(config.model_dump(mode="json"), key)})


@competitors_app.command("add")
def competitor_add(name: str) -> None:
    project = project_path()
    config = load_config(project)
    if name.casefold() not in {x.name.casefold() for x in config.tracked_brands}:
        config.competitors.append(Brand(name=name))
    with Store(project).locked():
        save_config(project, config)
    emit("aivis config competitors add", {"competitors": [x.name for x in config.competitors]})


@competitors_app.command("rm")
def competitor_rm(name: str) -> None:
    project = project_path()
    config = load_config(project)
    config.competitors = [x for x in config.competitors if x.name.casefold() != name.casefold()]
    with Store(project).locked():
        save_config(project, config)
    emit("aivis config competitors rm", {"competitors": [x.name for x in config.competitors]})


@app.command()
def configure(
    engines: str = typer.Option(..., "--engines", help="Comma-separated configured API engines."),
    samples_per_prompt: int = typer.Option(3, "--samples-per-prompt", min=1),
) -> None:
    project = project_path()
    try:
        config = configure_collection(
            load_config(project),
            engines=engines.split(","),
            samples_per_prompt=samples_per_prompt,
        )
    except ValueError as exc:
        fail("aivis configure", "invalid_collection_config", str(exc))
    with Store(project).locked():
        save_config(project, config)
    emit(
        "aivis configure",
        {
            "engines": [item.id for item in config.engines.api if item.enabled],
            "samples_per_prompt": config.sampling.runs_per_prompt,
            "remote_inference": config.collection.remote,
        },
        next_steps=["aivis prompts list", "aivis run --dry-run", "aivis doctor"],
    )


@app.command("run")
def run_cmd(
    engines: str | None = typer.Option(None, "--engines"),
    cluster: str | None = typer.Option(None, "--cluster"),
    sample: int | None = typer.Option(None, "--sample"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_extract: bool = typer.Option(False, "--no-extract"),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    project = project_path()
    config = load_config(project)
    store = Store(project)
    prompts = store.load_prompts()
    if cluster:
        allowed = set(cluster.split(","))
        prompts = [x for x in prompts if x.cluster in allowed]
    if sample is not None:
        prompts = random.sample(prompts, min(sample, len(prompts)))
    enabled = [x for x in config.engines.api if x.enabled]
    if engines:
        requested = set(engines.split(","))
        enabled = [x for x in enabled if x.id in requested]
    plan = RunPlan(
        prompts=len(prompts),
        engines=[x.id for x in enabled],
        samples_per_prompt=config.sampling.runs_per_prompt,
    )
    calls = plan.prompts * len(plan.engines) * plan.samples_per_prompt
    if dry_run:
        emit(
            "aivis run",
            {
                "dry_run": True,
                "plan": plan.model_dump(),
                "remote_inference": config.collection.remote,
                "collection_calls": calls,
                "judge_first_pass_calls": calls,
                "judge_framing_calls": f"0–{calls * len(config.tracked_brands)}",
            },
        )
        return
    if not prompts or not enabled:
        fail("aivis run", "empty_plan", "No active prompts or enabled API engines")
    with store.locked():
        manifest = store.start_run(plan, config, notes)
        try:
            EDSLCollector(config).collect(
                prompts, enabled, config.sampling.runs_per_prompt, manifest.run_id, store, stderr
            )
            if not no_extract:
                extract_run(store, manifest.run_id, config)
        except KeyboardInterrupt:
            store.finalize_run(manifest.run_id, "partial")
            raise
        except Exception as exc:
            store.finalize_run(manifest.run_id)
            fail("aivis run", "collection_failed", str(exc))
        result = store.finalize_run(manifest.run_id)
    emit(
        "aivis run",
        {"run": result.model_dump(mode="json")},
        next_steps=[f"aivis report --run {manifest.run_id}"],
    )


@app.command()
def extract(
    run: str = typer.Option("last", "--run"),
    estimate: bool = typer.Option(False, "--estimate"),
    judge_version: int | None = typer.Option(None, "--judge-version"),
) -> None:
    project = project_path()
    store = Store(project)
    config = load_config(project)
    version = judge_version or config.judge.version
    runs = store.list_runs()
    selected = (
        runs if run == "all" else [runs[-1] if run == "last" and runs else store.load_run(run)]
    )
    missing = {
        item.run_id: len(store.missing_observations(item.run_id, version)) for item in selected
    }
    if estimate:
        emit(
            "aivis extract",
            {
                "judge_version": version,
                "missing_samples": missing,
                "first_pass_calls": sum(missing.values()),
                "framing_calls": f"0–{sum(missing.values()) * len(config.tracked_brands)}",
            },
        )
        return
    with store.locked():
        total = sum(extract_run(store, item.run_id, config, version) for item in selected)
    emit("aivis extract", {"judge_version": version, "samples_extracted": total})


@app.command()
def report(
    run: str | None = typer.Option(None, "--run"),
    engines: str | None = typer.Option(None, "--engines"),
) -> None:
    project = project_path()
    store = Store(project)
    config = load_config(project)
    if run is None or run == "last":
        complete = [x for x in store.list_runs() if x.status == "complete"]
        if not complete:
            fail("aivis report", "no_complete_run", "No complete run is available")
        run = complete[-1].run_id
    selected = engines.split(",") if engines else None
    if state.human:
        render_snapshot(store, run, config, stdout, selected)
    else:
        emit("aivis report", snapshot_data(store, run, config, selected))


@app.command("export")
def export_cmd(
    format_: str = typer.Option(..., "--format"),
    run: str = typer.Option("last", "--run"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    project = project_path()
    store = Store(project)
    runs = store.list_runs()
    ids = [x.run_id for x in runs] if run == "all" else [runs[-1].run_id if run == "last" else run]
    if format_ == "json":
        paths = export_json(store, ids, out or Path("aivis-export.json"))
    elif format_ == "csv":
        paths = export_csv(store, ids, out or Path("aivis-export"))
    else:
        fail("aivis export", "unsupported_format", "v1 supports csv and json")
    emit("aivis export", {"paths": [str(x) for x in paths]})


@app.command()
def doctor(fix: bool = typer.Option(False, "--fix")) -> None:
    project = project_path()
    checks: dict[str, Any] = {}
    errors = []
    try:
        config = load_config(project)
        checks["config"] = "ok"
    except Exception as exc:
        fail("aivis doctor", "invalid_config", str(exc))
    try:
        checks["edsl_version"] = importlib.metadata.version("edsl")
    except importlib.metadata.PackageNotFoundError:
        checks["edsl_version"] = None
        errors.append("EDSL is not installed")
    env_state = load_local_env()
    checks["env_file"] = env_state["path"]
    checks["api_keys_present"] = env_state["present_keys"]
    required = {"gpt": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY", "gemini": "GOOGLE_API_KEY"}
    checks["remote_inference"] = config.collection.remote
    if config.collection.remote:
        checks["expected_parrot_auth"] = Coop().has_api_key
        if not checks["expected_parrot_auth"]:
            errors.append("EXPECTED_PARROT_API_KEY is missing for remote inference")
    else:
        for engine in (x for x in config.engines.api if x.enabled):
            key = next(
                (value for prefix, value in required.items() if engine.id.startswith(prefix)), None
            )
            if key and not os.getenv(key):
                errors.append(f"{key} is missing for enabled engine {engine.id}")
    store = Store(project)
    with store.locked() if fix else _nullcontext():
        checks["store_errors"] = store.fsck(fix)
    errors.extend(checks["store_errors"])
    if errors:
        fail("aivis doctor", "doctor_failed", "; ".join(errors))
    emit("aivis doctor", checks)


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


@app.command()
def guide() -> None:
    emit(
        "aivis guide",
        {
            "workflow": [
                "aivis init --brand NAME --competitors A,B",
                "aivis prompts add TEXT --cluster category",
                "aivis prompts list",
                "aivis configure --engines ENGINE[,ENGINE] --samples-per-prompt N",
                "aivis run --dry-run",
                "aivis doctor",
                "aivis run",
                "aivis report",
            ]
        },
        next_steps=[
            "Configure engines and repetitions atomically before preflight.",
            "Run 'aivis doctor' before paid collection.",
            "Commit .aivis/data/ after each completed run.",
        ],
    )


@app.command()
def capabilities() -> None:
    emit(
        "aivis capabilities",
        {
            "store": "flat-json-v1",
            "collection": ["edsl-api"],
            "exports": ["csv", "json"],
            "later_milestones": ["trend", "diff", "playwright", "html"],
        },
    )


@app.command("report-context")
def report_context_cmd(
    run: str = typer.Option("last", "--run"),
    out: Path = typer.Option(..., "--out"),
    excerpt_chars: int = typer.Option(1200, "--excerpt-chars", min=200),
) -> None:
    project = project_path()
    store = Store(project)
    config = load_config(project)
    runs = store.list_runs()
    if run == "last":
        if not runs:
            fail("aivis report-context", "no_runs", "No run is available")
        run = runs[-1].run_id
    payload = write_report_context(store, run, config, out, excerpt_chars)
    emit(
        "aivis report-context",
        {
            "path": str(out),
            "run_id": run,
            "reportability": payload["reportability"],
            "evidence_records": len(payload["evidence"]),
        },
        next_steps=[f"Use {out} as the evidence context when composing the report."],
    )


if __name__ == "__main__":
    app()
