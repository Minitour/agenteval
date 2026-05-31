"""Provider registry / factory.

Adding a provider is a two-line change: implement a Provider subclass and
register it here (or call register() from your own module).
"""
from __future__ import annotations

from typing import Any

from .base import Provider
from .claude import ClaudeProvider

_PROVIDERS: dict[str, type[Provider]] = {
    ClaudeProvider.name: ClaudeProvider,
}


def register(provider_cls: type[Provider]) -> None:
    _PROVIDERS[provider_cls.name] = provider_cls


def available() -> list[str]:
    return sorted(_PROVIDERS)


def get_provider(name: str, config: dict[str, Any] | None = None) -> Provider:
    if name not in _PROVIDERS:
        raise KeyError(f"unknown provider '{name}'. available: {available()}")
    return _PROVIDERS[name](config or {})
