"""GeminiService tested against a fake SDK client - no real API key or network needed."""
import pytest

pytest.importorskip("pydantic")

from pydantic import BaseModel

from app.gemini.service import GeminiError, GeminiService, check_api_key


class Echo(BaseModel):
    value: str


class FakeResponse:
    def __init__(self, text=None, parsed=None):
        self.text, self.parsed, self.usage_metadata = text, parsed, None


class FakeModels:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


class Boom(Exception):
    def __init__(self, code):
        self.code = code


def svc(script, **kw):
    return GeminiService("key", "m", client=FakeClient(script), sleep=lambda s: None, **kw)


def test_generate_returns_text():
    s = svc([FakeResponse(text="hello")])
    assert s.generate("hi") == "hello"
    assert s.call_count == 1


def test_generate_structured_uses_parsed_then_falls_back_to_json_text():
    s = svc([FakeResponse(parsed=Echo(value="a"))])
    assert s.generate_structured("q", Echo).value == "a"
    s2 = svc([FakeResponse(text='{"value": "b"}')])
    assert s2.generate_structured("q", Echo).value == "b"


def test_bad_structured_output_raises_gemini_error():
    s = svc([FakeResponse(text="not json")])
    with pytest.raises(GeminiError) as e:
        s.generate_structured("q", Echo)
    assert e.value.code == "bad_output"


def test_retries_on_rate_limit_then_succeeds():
    s = svc([Boom(429), FakeResponse(text="ok")], max_retries=2)
    assert s.generate("q") == "ok"


def test_gives_up_after_max_retries():
    s = svc([Boom(429), Boom(429), Boom(429)], max_retries=1)
    with pytest.raises(GeminiError) as e:
        s.generate("q")
    assert e.value.code == "rate_limited"


def test_invalid_key_is_not_retried():
    s = svc([Boom(401), FakeResponse(text="should not be reached")], max_retries=3)
    with pytest.raises(GeminiError) as e:
        s.generate("q")
    assert e.value.code == "invalid_key"
    assert len(s._client.models.calls) == 1


def test_empty_response_raises():
    s = svc([FakeResponse(text="")])
    with pytest.raises(GeminiError) as e:
        s.generate("q")
    assert e.value.code == "empty_response"


def test_check_api_key_valid_and_invalid():
    class Patched(GeminiService):
        def __init__(self, ok):
            super().__init__("key", "m", client=FakeClient([FakeResponse(text="ok")] if ok else [Boom(401)]))

    import app.gemini.service as mod
    orig = mod.GeminiService
    try:
        mod.GeminiService = lambda api_key, model, max_retries=0: Patched(True)
        assert check_api_key("k", "m") == (True, "ok")
        mod.GeminiService = lambda api_key, model, max_retries=0: Patched(False)
        assert check_api_key("k", "m") == (False, "invalid_key")
    finally:
        mod.GeminiService = orig


def test_empty_response_during_key_check_counts_as_valid():
    class Patched(GeminiService):
        def __init__(self):
            super().__init__("key", "m", client=FakeClient([FakeResponse(text="")]))

    import app.gemini.service as mod
    orig = mod.GeminiService
    try:
        mod.GeminiService = lambda api_key, model, max_retries=0: Patched()
        assert check_api_key("k", "m") == (True, "ok")
    finally:
        mod.GeminiService = orig
