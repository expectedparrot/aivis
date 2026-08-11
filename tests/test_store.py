from pathlib import Path

import pytest

from aivis.config import default_config
from aivis.models import BrandObservation, RunPlan, Sample, SampleObservations
from aivis.store import Store, StoreError
from aivis.util import prompt_id, sample_id, utc_now


def ready_store(tmp_path: Path):
    project = tmp_path / ".aivis"
    project.mkdir()
    store = Store(project)
    store.initialize()
    return store


def test_serialization_is_byte_identical(tmp_path):
    store = ready_store(tmp_path)
    from aivis.models import Prompt

    item = Prompt(
        prompt_id=prompt_id("Hello world"),
        text="Hello world",
        cluster="category",
        created_at=utc_now(),
    )
    store.write_prompts([item])
    path = store.data / "prompts.json"
    first = path.read_bytes()
    assert b'"schema": 1' in first
    assert b'"schema_version"' not in first
    store.write_prompts(store.load_prompts())
    assert path.read_bytes() == first
    assert first.endswith(b"\n")


def test_run_sample_observation_and_fsck(tmp_path):
    store = ready_store(tmp_path)
    config = default_config("A", ["B"])
    run = store.start_run(RunPlan(prompts=1, engines=["gpt"], samples_per_prompt=1), config)
    sid = sample_id(run.run_id, "prompt", "gpt", 0)
    sample = Sample(
        sample_id=sid,
        run_id=run.run_id,
        prompt_id="prompt",
        engine="gpt",
        sample_index=0,
        collected_at=utc_now(),
        collector="edsl",
        status="ok",
        response_text="A",
    )
    store.write_sample(sample)
    obs = SampleObservations(
        sample_id=sid,
        judge_version=1,
        judge_model="judge",
        extracted_at=utc_now(),
        brands=[
            BrandObservation(brand="B", mentioned=False, framing="not_mentioned"),
            BrandObservation(brand="A", mentioned=True, framing="recommended", first_position=1),
        ],
        judged_domains=["z.com", "a.com", "z.com"],
    )
    store.write_observations(run.run_id, "gpt", obs)
    store.finalize_run(run.run_id)
    assert store.load_run(run.run_id).status == "complete"
    loaded = store.load_observations(run.run_id)[0]
    assert [x.brand for x in loaded.brands] == ["A", "B"]
    assert loaded.judged_domains == ["a.com", "z.com"]
    assert store.fsck() == []
    with pytest.raises(StoreError, match="immutable"):
        store.write_sample(sample)


def test_corrupt_file_names_path(tmp_path):
    store = ready_store(tmp_path)
    path = store.data / "prompts.json"
    path.write_text("not json")
    with pytest.raises(StoreError, match=str(path)):
        store.load_prompts()


def test_orphan_tmp_fix(tmp_path):
    store = ready_store(tmp_path)
    tmp = store.data / "orphan.tmp"
    tmp.write_text("x")
    assert "orphaned" in store.fsck()[0]
    assert store.fsck(fix=True) == [] and not tmp.exists()
