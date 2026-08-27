"""Environment-based configuration for Sentinel.

Loads settings from a .env file (via python-dotenv) and the process
environment. Nothing here hardcodes a secret — the API key only ever comes from
the environment, and .env is gitignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file:
# src/sentinel/config.py -> project root). override=False means a real
# environment variable always wins over the file, which is what you want in CI.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=False)

# Where the incident text files live.
INCIDENTS_DIR = _PROJECT_ROOT / "incidents"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or malformed.

    This is our first 'typed failure': a *configuration* failure, distinct from
    anything the API or the model does. Catching this separately lets the app
    tell the user 'your setup is wrong' instead of 'the request failed'.
    """


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of Sentinel's runtime configuration.

    Sentinel accepts EITHER credential type the Anthropic SDK understands:

      * api_key    -> a console.anthropic.com key (sk-ant-...), billed per token.
      * auth_token -> an OAuth token from a Claude subscription (`claude
                      setup-token`). Sent as `Authorization: Bearer` plus the
                      `anthropic-beta: oauth-2025-04-20` header; no API credit
                      needed, uses the subscription instead.

    If both are set, the API key wins (matches the SDK's own precedence).
    """

    api_key: str | None
    auth_token: str | None
    model: str
    max_tokens: int
    base_url: str | None

    @property
    def auth_kind(self) -> str:
        return "api_key" if self.api_key else "auth_token"

    @property
    def credential(self) -> str:
        return self.api_key or self.auth_token or ""

    @property
    def masked_key(self) -> str:
        """A safe-to-print version of the credential (never log the real thing)."""
        cred = self.credential
        if len(cred) <= 12:
            return "***"
        return f"{cred[:8]}...{cred[-4:]} ({self.auth_kind})"


def load_settings(*, require_key: bool = True) -> Settings:
    """Read and validate configuration from the environment.

    Args:
        require_key: If True (the default), missing credentials raise ConfigError.
            Set False for code paths that only need the model/max_tokens
            (e.g. printing config) and won't actually call the API.

    Raises:
        ConfigError: if a credential is required but absent, or max_tokens is
            invalid.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip() or None
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None

    if require_key and not (api_key or auth_token):
        raise ConfigError(
            "No credential found. Copy .env.example to .env and set ONE of:\n"
            "  ANTHROPIC_API_KEY=sk-ant-...     (from https://console.anthropic.com)\n"
            "  ANTHROPIC_AUTH_TOKEN=...         (from `claude setup-token`, uses your subscription)"
        )

    # Default to Haiku 4.5: it's the model a subscription OAuth token can reach
    # on the direct Messages API. With a real API key you can override this to
    # claude-opus-5 / claude-sonnet-5 via SENTINEL_MODEL in .env.
    model = os.environ.get("SENTINEL_MODEL", "claude-haiku-4-5").strip()

    raw_max = os.environ.get("SENTINEL_MAX_TOKENS", "8000").strip()
    try:
        max_tokens = int(raw_max)
        if max_tokens <= 0:
            raise ValueError
    except ValueError as exc:
        raise ConfigError(
            f"SENTINEL_MAX_TOKENS must be a positive integer, got {raw_max!r}"
        ) from exc

    return Settings(
        api_key=api_key,
        auth_token=auth_token,
        model=model,
        max_tokens=max_tokens,
        base_url=base_url,
    )


def read_incident(name: str) -> str:
    """Load an incident brief by file stem, e.g. read_incident('inc-104')."""
    path = INCIDENTS_DIR / f"{name}.md"
    if not path.exists():
        raise ConfigError(f"No incident file at {path}")
    return path.read_text(encoding="utf-8").strip()
