from aivis.config import default_config
from aivis.models import (
    BrandObservation,
    Prompt,
    RunPlan,
    Sample,
    SampleObservations,
)
from aivis.report_context import build_report_context
from aivis.store import Store
from aivis.util import prompt_id, sample_id, utc_now


def test_context_marks_partial_run_directional_and_traces_excerpt(tmp_path):
    project = tmp_path / ".aivis"
    project.mkdir()
    store = Store(project)
    store.initialize()
    config = default_config("Upwork", ["Fiverr"])
    text = "where should I hire a developer"
    prompt = Prompt(prompt_id=prompt_id(text), text=text, cluster="category", created_at=utc_now())
    store.write_prompts([prompt])
    run = store.start_run(RunPlan(prompts=1, engines=["gpt-4o"], samples_per_prompt=2), config)
    sid = sample_id(run.run_id, prompt.prompt_id, "gpt-4o", 0)
    response = "Upwork is a strong option, while Fiverr can work for smaller tasks."
    store.write_sample(
        Sample(
            sample_id=sid,
            run_id=run.run_id,
            prompt_id=prompt.prompt_id,
            engine="gpt-4o",
            sample_index=0,
            collected_at=utc_now(),
            collector="edsl",
            status="ok",
            response_text=response,
        )
    )
    store.write_observations(
        run.run_id,
        "gpt-4o",
        SampleObservations(
            sample_id=sid,
            judge_version=1,
            judge_model="judge",
            extracted_at=utc_now(),
            brands=[
                BrandObservation(
                    brand="Upwork", mentioned=True, framing="recommended", first_position=1
                ),
                BrandObservation(
                    brand="Fiverr", mentioned=True, framing="neutral", first_position=2
                ),
            ],
        ),
    )
    store.finalize_run(run.run_id)

    payload = build_report_context(store, run.run_id, config)

    assert payload["reportability"]["status"] == "directional"
    assert payload["coverage"]["planned_samples"] == 2
    assert payload["coverage"]["successful_samples"] == 1
    assert payload["evidence"][0]["exact_response_excerpt"] == response
    assert payload["metrics"]["overall"][0]["recommendation_rate_pct"]["n"] == 1
