from aivis.edsl_support import inference_service, make_model


def test_inference_service_mapping():
    assert inference_service("gpt-4o") == "openai"
    assert inference_service("claude-sonnet-4-6") == "anthropic"
    assert inference_service("gemini-2.5-flash") == "google"
    assert inference_service("sonar") == "perplexity"
    assert inference_service("custom") is None


def test_make_model_passes_service_when_known():
    calls = []

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return "model"

    assert make_model(factory, "gpt-4o") == "model"
    assert calls == [(("gpt-4o",), {"service_name": "openai"})]
