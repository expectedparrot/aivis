from aivis.config import default_config
from aivis.extract import assemble_observations
from aivis.models import Sample


def test_null_framing_falls_back_to_neutral():
    config = default_config("Upwork", ["Fiverr"])
    sample = Sample(
        sample_id="sample",
        run_id="run",
        prompt_id="prompt",
        engine="gpt-4o",
        sample_index=0,
        collected_at="2026-01-01T00:00:00Z",
        collector="edsl",
        status="ok",
        response_text="Upwork is listed.",
    )
    result = assemble_observations(
        sample,
        config,
        {"mentioned": ["Upwork"], "mention_order": ["Upwork"], "cited_domains": []},
        {"Upwork": None},
    )
    assert result.brands[0].framing == "neutral"
