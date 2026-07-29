from __future__ import annotations


class LlmError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        provider_error_code: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.provider_error_code = provider_error_code
        self.retry_after_seconds = retry_after_seconds


class LlmClientError(LlmError):
    """Compatibility base class for existing routing services."""


class LlmAuthenticationError(LlmClientError):
    pass


class LlmPermissionError(LlmClientError):
    pass


class LlmRateLimitError(LlmClientError):
    pass


class LlmBadRequestError(LlmClientError):
    pass


class LlmStructuredOutputError(LlmClientError):
    pass


class LlmTimeoutError(LlmClientError):
    pass


class LlmConnectionError(LlmClientError):
    pass


class LlmProviderError(LlmClientError):
    pass
