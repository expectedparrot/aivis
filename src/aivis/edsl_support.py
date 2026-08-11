from __future__ import annotations


def inference_service(model_id: str) -> str | None:
    lowered = model_id.casefold()
    if lowered.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if lowered.startswith("claude"):
        return "anthropic"
    if lowered.startswith("gemini"):
        return "google"
    if lowered.startswith("sonar"):
        return "perplexity"
    return None


def make_model(model_factory, model_id: str):
    service = inference_service(model_id)
    return model_factory(model_id, service_name=service) if service else model_factory(model_id)
