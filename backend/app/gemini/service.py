"""GeminiService: the only module that talks to the Gemini API (google-genai SDK).

* Uses the current `google-genai` SDK (`from google import genai`), not the retired `google-generativeai`.
* Sampling parameters (temperature/top_p/top_k) are intentionally NOT set - Google has deprecated them.
* Never logs prompts, responses or keys. Errors are mapped to safe, key-free messages.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, List, Optional, Type, TypeVar

from pydantic import BaseModel

from app.core.logging import log_event

logger = logging.getLogger("gemini")
T = TypeVar("T", bound=BaseModel)

_TRANSIENT = {"rate_limited", "unavailable", "network"}


class GeminiError(Exception):
    """A Gemini failure with a stable `code` and a message that is safe to show to users."""

    def __init__(self, code: str, user_message: str):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


def _classify(exc: Exception) -> GeminiError:
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status in (401, 403):
        return GeminiError("invalid_key", "Gemini rejected the API key.")
    if status == 404:
        return GeminiError("model_not_found", "The configured Gemini model was not found.")
    if status == 429:
        return GeminiError("rate_limited", "Gemini rate limit reached. Please retry shortly.")
    if isinstance(status, int) and status >= 500:
        return GeminiError("unavailable", "Gemini is temporarily unavailable.")
    if isinstance(status, int) and status == 400:
        return GeminiError("bad_request", "Gemini rejected the request (invalid key or unsupported input).")
    name = type(exc).__name__.lower()
    if any(k in name for k in ("timeout", "connect", "network", "transport")):
        return GeminiError("network", "Could not reach Gemini. Check the network connection.")
    return GeminiError("unknown", "Unexpected error while calling Gemini.")


class GeminiService:
    def __init__(self, api_key: str, model: str, client: Any = None, max_retries: int = 2,
                 sleep: Callable[[float], None] = time.sleep):
        if client is None:
            from google import genai  # lazy import keeps unit tests independent of the SDK

            client = genai.Client(api_key=api_key)
        self._client = client
        self.model = model
        self.max_retries = max_retries
        self._sleep = sleep
        self.call_count = 0

    # -- public API ------------------------------------------------------------------------
    def generate(self, prompt: str, system: Optional[str] = None, max_output_tokens: Optional[int] = None) -> str:
        config = self._config(system=system, max_output_tokens=max_output_tokens)
        response = self._call("text", prompt, config)
        return self._text(response)

    def generate_structured(self, prompt: str, schema: Type[T], system: Optional[str] = None) -> T:
        config = self._config(system=system, response_mime_type="application/json", response_schema=schema)
        response = self._call("structured", prompt, config)
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        try:
            return schema.model_validate_json(self._text(response))
        except Exception:
            raise GeminiError("bad_output", "Gemini returned output that did not match the expected format.") from None

    def generate_with_tools(self, prompt: str, tools: List[Callable], system: Optional[str] = None, max_calls: int = 8) -> str:
        """Native Gemini function calling: the SDK executes the given Python callables as the model requests them."""
        from google.genai import types

        config = self._config(
            system=system, tools=tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=max_calls),
        )
        response = self._call("tools", prompt, config)
        try:
            return self._text(response)
        except GeminiError:
            return ""  # the model may end on a tool call with no closing text; tool results are recorded by the callables

    # -- internals -------------------------------------------------------------------------
    def _config(self, system: Optional[str] = None, **kwargs: Any) -> Any:
        from google.genai import types

        params = {k: v for k, v in kwargs.items() if v is not None}
        if system:
            params["system_instruction"] = system
        return types.GenerateContentConfig(**params)

    def _call(self, kind: str, prompt: str, config: Any) -> Any:
        attempt = 0
        while True:
            attempt += 1
            start = time.perf_counter()
            try:
                response = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
            except GeminiError:
                raise
            except Exception as exc:
                err = _classify(exc)
                log_event(logger, "gemini_error", logging.WARNING, kind=kind, code=err.code, attempt=attempt,
                          error_type=type(exc).__name__, latency_ms=round((time.perf_counter() - start) * 1000, 1))
                if err.code in _TRANSIENT and attempt <= self.max_retries:
                    self._sleep(2 ** (attempt - 1))
                    continue
                raise err from None  # never chain: the original exception could carry request details
            self.call_count += 1
            usage = getattr(response, "usage_metadata", None)
            log_event(logger, "gemini_call", kind=kind, model=self.model, attempts=attempt,
                      latency_ms=round((time.perf_counter() - start) * 1000, 1), prompt_chars=len(prompt),
                      input_tokens=getattr(usage, "prompt_token_count", None),
                      output_tokens=getattr(usage, "candidates_token_count", None))
            return response

    @staticmethod
    def _text(response: Any) -> str:
        try:
            text = response.text
        except Exception:
            text = None
        if not text:
            raise GeminiError("empty_response", "Gemini returned an empty response.")
        return text


def check_api_key(api_key: str, model: str) -> tuple[bool, str]:
    """Minimal live request to verify a key. Returns (valid, code). The key is never returned or logged."""
    try:
        GeminiService(api_key, model, max_retries=0).generate("Reply with the single word: ok", max_output_tokens=64)
        return True, "ok"
    except GeminiError as err:
        # An empty/truncated reply still proves the key works.
        return (True, "ok") if err.code == "empty_response" else (False, err.code)
    except Exception:
        return False, "unknown"
