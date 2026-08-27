"""Builds an Anthropic client from Sentinel's Settings.

Centralised so every section (basic request, streaming, caching, ...) constructs
the client the same way and handles both credential types identically.

Credential handling:
  * API key    -> anthropic.Anthropic(api_key=...). Header: x-api-key.
  * Auth token -> anthropic.Anthropic(auth_token=...). Header: Authorization:
                  Bearer <token>. OAuth subscription tokens additionally require
                  the beta header `oauth-2025-04-20`, which we add by default.
"""

from __future__ import annotations

import anthropic

from .config import Settings
from .failures import FailureKind, SentinelFailure


def map_api_exception(exc: Exception) -> SentinelFailure:
    """Translate an Anthropic SDK exception into a typed SentinelFailure.

    This is where 'integration' and 'configuration' failures are classified —
    the exercise's failure taxonomy applied to real SDK exception types. Order
    matters: most specific first.
    """
    if isinstance(exc, anthropic.AuthenticationError):
        return SentinelFailure(FailureKind.AUTH_ERROR,
                               "Authentication failed (bad or expired credential).",
                               detail=str(exc))
    if isinstance(exc, anthropic.PermissionDeniedError):
        return SentinelFailure(FailureKind.AUTH_ERROR,
                               "Credential lacks permission for this request.",
                               detail=str(exc))
    if isinstance(exc, anthropic.RateLimitError):
        return SentinelFailure(FailureKind.RATE_LIMIT,
                               "Rate limited by the API.", detail=str(exc))
    if isinstance(exc, anthropic.APITimeoutError):
        return SentinelFailure(FailureKind.TIMEOUT,
                               "Request timed out.", detail=str(exc))
    if isinstance(exc, anthropic.BadRequestError):
        # A 400 for exceeding the context window is a context-limit failure;
        # other 400s are generic bad requests we treat as API errors.
        text = str(exc).lower()
        if "context" in text or "too many tokens" in text or "prompt is too long" in text:
            return SentinelFailure(FailureKind.CONTEXT_LIMIT,
                                   "Request exceeded the model's context window.",
                                   detail=str(exc))
        return SentinelFailure(FailureKind.API_ERROR,
                               "Bad request rejected by the API.", detail=str(exc))
    if isinstance(exc, anthropic.APIConnectionError):
        return SentinelFailure(FailureKind.API_ERROR,
                               "Network/connection error reaching the API.",
                               detail=str(exc))
    if isinstance(exc, anthropic.APIStatusError):
        return SentinelFailure(FailureKind.API_ERROR,
                               f"API returned status {exc.status_code}.",
                               detail=str(exc))
    # Not an SDK error we recognise — re-wrap generically.
    return SentinelFailure(FailureKind.API_ERROR,
                           f"Unexpected error: {type(exc).__name__}", detail=str(exc))

# Required so a Claude *subscription* OAuth token is accepted by the Messages API.
_OAUTH_BETA = "oauth-2025-04-20"


def build_client(settings: Settings) -> anthropic.Anthropic:
    """Construct a synchronous Anthropic client for the given settings."""
    kwargs: dict = {}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url

    if settings.api_key:
        return anthropic.Anthropic(api_key=settings.api_key, **kwargs)

    # OAuth / auth-token path: Bearer auth + the oauth beta header.
    return anthropic.Anthropic(
        auth_token=settings.auth_token,
        default_headers={"anthropic-beta": _OAUTH_BETA},
        **kwargs,
    )


def build_async_client(settings: Settings) -> anthropic.AsyncAnthropic:
    """Async variant, used by the asynchronous-request example."""
    kwargs: dict = {}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url

    if settings.api_key:
        return anthropic.AsyncAnthropic(api_key=settings.api_key, **kwargs)

    return anthropic.AsyncAnthropic(
        auth_token=settings.auth_token,
        default_headers={"anthropic-beta": _OAUTH_BETA},
        **kwargs,
    )
