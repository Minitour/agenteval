"""Provider registry / factory.

Adding a provider is a two-line change: implement a Provider subclass and
register it here (or call register() from your own module).
"""
from __future__ import annotations

import warnings
from typing import Any

from .base import Provider
from .claude import ClaudeProvider

_PROVIDERS: dict[str, type[Provider]] = {
    ClaudeProvider.name: ClaudeProvider,
}

# Names shipped with the framework. Overwriting one of these is almost always
# an accident (e.g. a user naming their provider "claude"), so we warn unless
# the caller explicitly opts in with force=True.
_BUILTINS = frozenset(_PROVIDERS)


def register(provider_cls: type[Provider], *, force: bool = False) -> None:
    name = provider_cls.name
    if name in _BUILTINS and not force and _PROVIDERS.get(name) is not provider_cls:
        warnings.warn(
            f"provider '{name}' shadows a built-in provider; the bundled "
            f"implementation will no longer be reachable. Rename your provider "
            f"or pass force=True to silence this warning.",
            stacklevel=2,
        )
    _PROVIDERS[name] = provider_cls


def available() -> list[str]:
    return sorted(_PROVIDERS)


def get_provider(name: str, config: dict[str, Any] | None = None) -> Provider:
    if name not in _PROVIDERS:
        raise KeyError(f"unknown provider '{name}'. available: {available()}")
    return _PROVIDERS[name](config or {})
