"""Durable per-scope generation counters recovered from the record stream.

Generation changes are represented by committed records, not by process-only
state.  Replaying the stream rebuilds both each scope generation and the global
configuration generation, so credentials invalidated by a parameter or
calibration change cannot come back after a restart.
"""

from __future__ import annotations

from collections.abc import Iterable

from line_control.store.meta import MetaStore
from line_control.store.records import Record

CONFIG_GENERATION_FIELD = "config_generation"


class GenerationLedger:
    """Generation numbers, counted as scopes and configuration are bumped."""

    __slots__ = ("_counters", "_values", "_configuration")

    def __init__(self, counters: MetaStore) -> None:
        self._counters = counters
        self._values: dict[str, int] = {}
        self._configuration = 0

    def recover(self, records: Iterable[Record]) -> None:
        """Rebuild every known generation from committed stream records."""
        values: dict[str, int] = {}
        configuration = 0
        for record in records:
            configuration = max(
                configuration, int(record.payload.get(CONFIG_GENERATION_FIELD, 0))
            )
            scope = record.payload.get("scope")
            if isinstance(scope, str) and scope:
                values[scope] = max(values.get(scope, 0), record.generation)
        self._values = values
        self._configuration = configuration

    def current(self, scope: str) -> int:
        """Return the generation a new artefact in ``scope`` would carry."""
        return self._values.get(scope, 0)

    def configuration(self) -> int:
        """Return the generation of the complete effective configuration."""
        return self._configuration

    def bump(self, scope: str) -> int:
        """Advance a scope and return the new generation."""
        updated = self.current(scope) + 1
        self._values[scope] = updated
        return updated

    def bump_configuration(self) -> int:
        """Advance the global configuration generation."""
        self._configuration += 1
        return self._configuration
