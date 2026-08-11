from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .config import Config
from .metrics import (
    avg_first_position,
    citation_influence,
    mention_rate,
    recommendation_rate,
    sentiment_mix,
    share_of_voice,
)
from .store import Store


def _display(metric) -> str:
    value = "—" if metric.value is None else f"{metric.value:.1f}"
    return value + ("†" if metric.n < 20 else "")


def snapshot_data(
    store: Store, run_id: str, config: Config, engines: list[str] | None = None
) -> dict:
    run = store.load_run(run_id)
    samples = list(store.iter_samples(run_id, engines))
    observations = store.load_observations(run_id, engines=engines)
    brands = []
    for brand in config.tracked_brands:
        brands.append(
            {
                "brand": brand.name,
                "sov": share_of_voice(samples, observations, brand.name).__dict__,
                "mention_rate": mention_rate(samples, observations, brand.name).__dict__,
                "recommendation_rate": recommendation_rate(
                    samples, observations, brand.name
                ).__dict__,
                "avg_first_position": avg_first_position(
                    samples, observations, brand.name
                ).__dict__,
            }
        )
    return {
        "run": run.model_dump(mode="json"),
        "judge_version": store.latest_judge_version(run_id),
        "brands": brands,
        "sentiment": {
            k: v.__dict__
            for k, v in sentiment_mix(samples, observations, config.brand.name).items()
        },
        "citations": citation_influence(samples, observations, config.brand.name),
    }


def render_snapshot(
    store: Store, run_id: str, config: Config, console: Console, engines: list[str] | None = None
) -> dict:
    data = snapshot_data(store, run_id, config, engines)
    run = data["run"]
    console.print(f"Run {run_id}  {run['status']}  {run['counts']}")
    table = Table(title="Share of voice")
    table.add_column("Brand")
    table.add_column("SOV %", justify="right")
    table.add_column("Mention %", justify="right")
    table.add_column("Recommend %", justify="right")
    table.add_column("Avg position", justify="right")
    for row in data["brands"]:
        style = "bold cyan" if row["brand"] == config.brand.name else None
        table.add_row(
            row["brand"],
            *(
                _display(type("M", (), row[key])())
                for key in ("sov", "mention_rate", "recommendation_rate", "avg_first_position")
            ),
            style=style,
        )
    console.print(table)
    sentiment = Table(title=f"Sentiment mix: {config.brand.name}")
    sentiment.add_column("Framing")
    sentiment.add_column("%", justify="right")
    for name, metric in data["sentiment"].items():
        sentiment.add_row(name, _display(type("M", (), metric)()))
    console.print(sentiment)
    citations = Table(title="Citation leaderboard")
    citations.add_column("Domain")
    citations.add_column("Carries you", justify="right")
    citations.add_column("Carries competitors", justify="right")
    for domain, counts in sorted(data["citations"].items(), key=lambda x: sum(x[1]), reverse=True)[
        :15
    ]:
        citations.add_row(domain, str(counts[0]), str(counts[1]))
    console.print(citations)
    console.print("† small sample — directional only")
    console.print(
        "API results are a proxy trend line, not a replica of consumer products (browsing, memory, and personalization may differ)."
    )
    return data
