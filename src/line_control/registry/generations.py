"""Per scope generation counters kept for the lifetime of the process."""

from __future__ import annotations

from line_control.store.meta import MetaStore


class GenerationLedger:
    """Generation numbers, counted as scopes are bumped."""

    __slots__ = ("_counters", "_values")

    def __init__(self, counters: MetaStore) -> None:
        self._counters = counters
        self._values: dict[str, int] = {}

    def current(self, scope: str) -> int:
        """Return the generation a new artefact in ``scope`` would carry."""
        return self._values.get(scope, 0)

    def bump(self, scope: str) -> int:
        """Advance a scope and return the new generation."""
        updated = self.current(scope) + 1
        self._values[scope] = updated
        return updated
