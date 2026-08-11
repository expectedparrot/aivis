from aivis.metrics import (
    avg_first_position,
    mention_rate,
    presence_rate,
    recommendation_rate,
    rec_given_mention,
    share_of_voice,
    volatility,
)
from aivis.models import BrandObservation, Sample, SampleObservations


def sample(sid, prompt="p", engine="e", index=0, status="ok"):
    return Sample(
        sample_id=sid,
        run_id="r",
        prompt_id=prompt,
        engine=engine,
        sample_index=index,
        collected_at="2026-01-01T00:00:00Z",
        collector="edsl",
        status=status,
    )


def obs(sid, a=True, framing="recommended", pos=1):
    return SampleObservations(
        sample_id=sid,
        judge_version=1,
        judge_model="j",
        extracted_at="2026-01-01T00:00:00Z",
        brands=[
            BrandObservation(
                brand="A",
                mentioned=a,
                framing=framing if a else "not_mentioned",
                first_position=pos if a else None,
            ),
            BrandObservation(brand="B", mentioned=True, framing="neutral", first_position=2),
        ],
    )


def test_metric_definitions_and_denominators():
    samples = [sample("1"), sample("2"), sample("3", status="error")]
    observations = [obs("1"), obs("2", False)]
    assert mention_rate(samples, observations, "A").value == 50
    assert recommendation_rate(samples, observations, "A").value == 50
    assert rec_given_mention(samples, observations, "A").value == 100
    assert share_of_voice(samples, observations, "A").value == 33.3
    assert avg_first_position(samples, observations, "A").value == 1


def test_zero_denominators_and_presence():
    assert mention_rate([], [], "A").value is None
    assert share_of_voice([sample("1")], [], "A").value is None
    assert avg_first_position([sample("1")], [obs("1", False)], "A").value is None
    assert (
        presence_rate(
            [
                sample("1", engine="browser"),
                sample("2", engine="browser", status="not_present"),
                sample("3", engine="browser", status="blocked"),
            ],
            "browser",
        ).value
        == 50
    )


def test_volatility_uses_only_overlapping_units():
    old_s = [sample("old1", "p1"), sample("old2", "old-only")]
    new_s = [sample("new1", "p1"), sample("new2", "new-only")]
    assert (
        volatility(
            old_s,
            [obs("old1", True), obs("old2", True)],
            new_s,
            [obs("new1", False), obs("new2", True)],
            "A",
        ).value
        == 100
    )
    assert volatility([], [], new_s, [obs("new1")], "A").value is None
