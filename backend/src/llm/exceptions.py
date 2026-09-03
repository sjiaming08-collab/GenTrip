"""LLM request and structured-response exceptions."""


class LLMError(Exception):
    """LLM failure carrying telemetry-safe metadata."""

    def __init__(self, message: str, *, meta: dict | None = None) -> None:
        super().__init__(message)
        self.meta = dict(meta or {})


class LLMParseError(LLMError):
    """The provider response could not satisfy the JSON contract."""


def failure_meta(operation: str, exc: Exception) -> dict:
    meta = dict(getattr(exc, "meta", {}) or {})
    meta.update({"operation": operation, "status": "failed", "fallback_used": True})
    meta.setdefault("error_code", "invalid_schema" if isinstance(exc, LLMParseError) else "llm_error")
    return meta
