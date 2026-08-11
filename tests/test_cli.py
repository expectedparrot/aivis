import json
from unittest.mock import patch

from typer.testing import CliRunner

from aivis.cli import app


runner = CliRunner()


def payload(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_init_prompt_and_dry_run(tmp_path):
    init = payload(
        runner.invoke(
            app, ["--project", str(tmp_path), "init", "--brand", "Acme", "--competitors", "Beta"]
        )
    )
    assert init["status"] in {"ok", "warning"}
    project = tmp_path / ".aivis"
    added = payload(
        runner.invoke(
            app,
            ["--project", str(project), "prompts", "add", "best tool?", "--cluster", "category"],
        )
    )
    assert added["data"]["created"] is True
    plan = payload(
        runner.invoke(app, ["--project", str(project), "run", "--dry-run", "--engines", "gpt-4o"])
    )
    assert plan["data"]["collection_calls"] == 3
    assert plan["data"]["remote_inference"] is True


def test_doctor_accepts_remote_auth_without_provider_keys(tmp_path, monkeypatch):
    payload(
        runner.invoke(app, ["--project", str(tmp_path), "init", "--brand", "Acme"])
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch("aivis.cli.Coop") as coop:
        coop.return_value.has_api_key = True
        result = payload(
            runner.invoke(app, ["--project", str(tmp_path / ".aivis"), "doctor"])
        )
    assert result["data"]["remote_inference"] is True
    assert result["data"]["expected_parrot_auth"] is True


def test_doctor_rejects_remote_mode_without_coop_auth(tmp_path):
    payload(
        runner.invoke(app, ["--project", str(tmp_path), "init", "--brand", "Acme"])
    )
    with patch("aivis.cli.Coop") as coop:
        coop.return_value.has_api_key = False
        result = runner.invoke(
            app, ["--project", str(tmp_path / ".aivis"), "doctor"]
        )
    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["errors"] == [
        {
            "code": "doctor_failed",
            "message": "EXPECTED_PARROT_API_KEY is missing for remote inference",
        }
    ]


def test_configure_sets_engines_and_samples_in_one_command(tmp_path):
    payload(runner.invoke(app, ["--project", str(tmp_path), "init", "--brand", "Acme"]))
    project = tmp_path / ".aivis"
    result = payload(
        runner.invoke(
            app,
            [
                "--project",
                str(project),
                "configure",
                "--engines",
                "claude-sonnet-4-6",
                "--samples-per-prompt",
                "1",
            ],
        )
    )
    assert result["data"] == {
        "engines": ["claude-sonnet-4-6"],
        "samples_per_prompt": 1,
        "remote_inference": True,
    }


def test_report_accepts_last_alias(tmp_path, monkeypatch):
    payload(runner.invoke(app, ["--project", str(tmp_path), "init", "--brand", "Acme"]))
    project = tmp_path / ".aivis"
    from types import SimpleNamespace

    run = SimpleNamespace(run_id="run-test", status="complete")
    monkeypatch.setattr("aivis.cli.Store.list_runs", lambda self: [run])
    monkeypatch.setattr("aivis.cli.snapshot_data", lambda *args: {"selected": args[1]})
    result = payload(
        runner.invoke(app, ["--project", str(project), "report", "--run", "last"])
    )
    assert result["data"]["selected"] == run.run_id
