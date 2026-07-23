"""
llm_engine.py
Structured-output wrapper around the Google Gen AI SDK (`google-genai`).
Encapsulates prompt construction, schema-constrained generation, latency
measurement, and Pydantic v2 validation of the model's response.

Root causes fixed vs. the previous version (see audit notes in main.py):
  1. MODELS previously pointed at deprecated free-tier IDs
     ("gemini-2.0-flash", "gemini-1.5-flash"), which the API now rejects
     with 404 NOT_FOUND. It now defaults to the same current model
     Project A uses successfully ("gemini-3.5-flash"), configurable via
     st.secrets/env, with a same-generation fallback.
  2. There was no retry/backoff for *transient* failures (429 rate limit,
     503 overloaded) — a single hiccup immediately burned a fallback slot.
     Transient errors now get up to 3 attempts with exponential backoff +
     jitter on the *same* model before moving to the next model. Permanent
     errors (404 model not found, 400 bad request/invalid schema, auth)
     fail fast and move on immediately — retrying those just wastes time.
  3. The previous code manually re-validated `response.text` with
     `model_validate_json`, ignoring the SDK's own `response.parsed`.
     `response.parsed` (used by Project A) is populated natively by the
     SDK when `response_schema` is a Pydantic model and is more tolerant
     of minor formatting artifacts. We now prefer it and only fall back
     to manual (fence-stripped) parsing if `.parsed` is unexpectedly None.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types

try:
    from google.genai import errors as genai_errors
    _API_ERROR = genai_errors.APIError
except (ImportError, AttributeError):  # pragma: no cover - SDK version guard
    _API_ERROR = Exception

from app.schemas import StarSchemaResponse

logger = logging.getLogger(__name__)

# Current, non-deprecated free-tier model chain. Overridable so a stale
# hardcoded list never becomes the failure point again.
DEFAULT_MODELS = ["gemini-3.5-flash", "gemini-2.5-flash"]

# HTTP/gRPC-style status codes (and substrings) that indicate a *transient*
# condition worth retrying on the same model before giving up on it.
_TRANSIENT_MARKERS = ("429", "503", "500", "rate limit", "overloaded", "unavailable", "deadline")
# Markers that indicate a *permanent* condition — retrying won't help,
# move straight to the next model (or fail outright if it's the last one).
_PERMANENT_MARKERS = ("404", "400", "401", "403", "not_found", "invalid_argument", "permission_denied")

_MAX_ATTEMPTS_PER_MODEL = 3
_BASE_BACKOFF_SECONDS = 1.5


class SchemaGenerationError(Exception):
    """Raised when the LLM call itself fails (network, auth, quota, timeout, 404)."""


class SchemaValidationError(Exception):
    """Raised when the LLM response cannot be validated against StarSchemaResponse."""


SYSTEM_INSTRUCTION = """You are a senior data warehouse architect. Given a raw JSON payload \
from a source system (e.g. a Stripe webhook or a Shopify order), design a Kimball-style \
dimensional star schema for DuckDB. Produce exactly one fact table and one or more \
dimension tables. All table and column names must be lower_snake_case. Dimension tables \
must be prefixed 'dim_' and carry an integer surrogate key. The fact table must be \
prefixed 'fct_' and reference every dimension surrogate key as a foreign key. Emit fully \
executable DuckDB DDL using CREATE SEQUENCE plus DEFAULT nextval() for every surrogate \
key, and emit complete dbt Core staging models, mart models, and a schema.yml with \
unique, not_null, and relationships tests. Return only the JSON object described by the \
response schema — no prose, no markdown fences, no commentary."""


@dataclass
class LLMCallResult:
    response: StarSchemaResponse
    raw_text: str
    latency_seconds: float
    prompt_token_count: int
    candidates_token_count: int
    model_used: str
    attempts: int


def _classify(exc: Exception) -> str:
    """Returns 'transient', 'permanent', or 'unknown' for a raised exception."""
    blob = f"{type(exc).__name__} {exc}".lower()
    if any(m in blob for m in _TRANSIENT_MARKERS):
        return "transient"
    if any(m in blob for m in _PERMANENT_MARKERS):
        return "permanent"
    return "unknown"


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    return t.strip()


class StarSchemaGenerator:
    """Thin, testable wrapper around genai.Client() for structured star-schema generation."""

    def __init__(self, api_key: str, models: list[str] | None = None) -> None:
        if not api_key:
            raise SchemaGenerationError(
                "Missing Google AI Studio API key. "
                "Set st.secrets['GOOGLE_API_KEY'] or enter it in the sidebar."
            )
        self._client = genai.Client(api_key=api_key)
        self._model_chain = models or DEFAULT_MODELS

    def generate(self, raw_json_payload: str) -> LLMCallResult:
        start = time.perf_counter()
        last_exception: Exception | None = None
        total_attempts = 0

        for model in self._model_chain:
            for attempt in range(1, _MAX_ATTEMPTS_PER_MODEL + 1):
                total_attempts += 1
                try:
                    logger.info("Attempting generation with model=%s attempt=%d", model, attempt)

                    response = self._client.models.generate_content(
                        model=model,
                        contents=[
                            genai_types.Content(
                                role="user",
                                parts=[genai_types.Part.from_text(text=raw_json_payload)],
                            )
                        ],
                        config=genai_types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            response_mime_type="application/json",
                            response_schema=StarSchemaResponse,
                            temperature=0.1,
                            max_output_tokens=8192,
                        ),
                    )

                    if not response.text or not response.text.strip():
                        raise SchemaGenerationError(f"Model {model} returned an empty response body.")

                    # Prefer the SDK's native Pydantic parsing (same as the
                    # working reference project) — only fall back to a manual,
                    # fence-stripped parse if .parsed is unexpectedly absent.
                    validated: StarSchemaResponse
                    if getattr(response, "parsed", None) is not None:
                        validated = response.parsed  # type: ignore[assignment]
                    else:
                        cleaned = _strip_code_fences(response.text)
                        validated = StarSchemaResponse.model_validate_json(cleaned)

                    latency = time.perf_counter() - start
                    usage = response.usage_metadata
                    return LLMCallResult(
                        response=validated,
                        raw_text=response.text,
                        latency_seconds=latency,
                        prompt_token_count=usage.prompt_token_count if usage else 0,
                        candidates_token_count=usage.candidates_token_count if usage else 0,
                        model_used=model,
                        attempts=total_attempts,
                    )

                except (_API_ERROR, Exception) as exc:  # noqa: BLE001 broad by design
                    if isinstance(exc, (SchemaValidationError,)):
                        raise
                    last_exception = exc
                    category = _classify(exc)

                    if isinstance(exc, ValueError) and "validat" in str(exc).lower():
                        # Pydantic validation failures are structural, not
                        # transient — no point retrying the same model.
                        logger.warning("Model %s produced schema-invalid JSON: %s", model, exc)
                        break

                    if category == "transient" and attempt < _MAX_ATTEMPTS_PER_MODEL:
                        backoff = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                        backoff += random.uniform(0, 0.5)
                        logger.warning(
                            "Transient error on %s (attempt %d/%d): %s — retrying in %.1fs",
                            model, attempt, _MAX_ATTEMPTS_PER_MODEL, exc, backoff,
                        )
                        time.sleep(backoff)
                        continue

                    # Permanent error, unknown error, or transient error that
                    # exhausted its retries on this model — move to next model.
                    logger.warning(
                        "Giving up on model %s (%s): %s", model, category, exc
                    )
                    break

        raise SchemaGenerationError(
            f"All models in the fallback chain failed after {total_attempts} attempt(s). "
            f"Last recorded error: {last_exception}"
        ) from last_exception