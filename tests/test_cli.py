import json

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
