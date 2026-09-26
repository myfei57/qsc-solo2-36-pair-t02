"""Per scope generation and revision counters.

Every scope carries two counters:

* ``generation`` is the epoch.  It only moves when the scope is deliberately
  retired (``bump``).  Snapshots and calibration baselines are pinned to one
  epoch and become stale the moment the epoch moves.
* ``revision`` is the change count of everything an operator could have
  approved against.  It advances on every committed parameter write *and*
  whenever the epoch moves.  Confirmations are pinned to one revision, so any
  parameter change withdraws the confirmations that were issued before it.

Both counters are reconstructed by replaying the committed record stream, so a
process restart never lets an artefact that was invalidated before the crash
come back to life.
"""

from __future__ import annotations

from collections.abc import Iterable

from line_control.store.meta import MetaStore
from line_control.store.records import Record

META_PREFIX = "generation:"
REVISION_PREFIX = "revision:"

# Record kinds whose commit moves the revision of the scope named in their key.
_PARAM_KINDS = frozenset({"param.set", "param.restore"})


class GenerationLedger:
    """Generation and revision numbers, counted as scopes change."""

    __slots__ = ("_counters", "_generations", "_revisions", "_links")

    def __init__(self, counters: MetaStore) -> None:
        self._counters = counters
        self._generations: dict[str, int] = {}
        self._revisions: dict[str, int] = {}
        # scope -> scopes whose revision follows this one's parameter writes
        self._links: dict[str, tuple[str, ...]] = {}

    # ---------------------------------------------------------------- reading
    def current(self, scope: str) -> int:
        """Return the epoch a new artefact in ``scope`` would carry."""
        return self._generations.get(scope, 0)

    def revision(self, scope: str) -> int:
        """Return the change count a new confirmation in ``scope`` would carry."""
        return self._revisions.get(scope, 0)

    def scopes(self) -> list[str]:
        """Return every scope this ledger has ever counted."""
        return sorted(set(self._generations) | set(self._revisions))

    # --------------------------------------------------------------- mutation
    def bump(self, scope: str) -> int:
        """Retire an epoch: advance the generation and the revision together."""
        updated = self.current(scope) + 1
        self._generations[scope] = updated
        self._revisions[scope] = self.revision(scope) + 1
        self._persist(scope)
        return updated

    def mark_changed(self, scope: str) -> int:
        """Count one parameter change in a scope and return the new revision."""
        updated = self.revision(scope) + 1
        self._revisions[scope] = updated
        self._persist(scope)
        for linked in self._links.get(scope, ()):
            self._revisions[linked] = self.revision(linked) + 1
            self._persist(linked)
        return updated

    def link(self, scope: str, *followers: str) -> None:
        """Make parameter changes in ``scope`` also advance follower revisions.

        Gate scopes hold no parameters themselves; linking lets a parameter
        write in the operating scope withdraw confirmations issued for the
        gate that guards it.
        """
        existing = self._links.get(scope, ())
        merged = tuple(sorted(set(existing) | {follower for follower in followers if follower}))
        self._links[scope] = merged

    # -------------------------------------------------------------- recovery
    def recover(self, records: Iterable[Record]) -> None:
        """Recompute every counter from the committed record stream."""
        self._generations.clear()
        self._revisions.clear()
        changed_scopes: set[str] = set()
        for record in records:
            payload_scope = str(record.payload.get("scope", ""))
            if record.kind == "param.epoch":
                scope = payload_scope or self._scope_from_key(record.key)
                if not scope:
                    continue
                # An epoch record supersedes earlier epochs of the same scope;
                # each epoch publication and each parameter write counts once.
                self._generations[scope] = record.generation
                self._revisions[scope] = self.revision(scope) + 1
                changed_scopes.add(scope)
            elif record.kind in _PARAM_KINDS and payload_scope:
                self._revisions[payload_scope] = self.revision(payload_scope) + 1
                changed_scopes.add(payload_scope)
                for linked in self._links.get(payload_scope, ()):
                    self._revisions[linked] = self.revision(linked) + 1
                    changed_scopes.add(linked)
        for scope in changed_scopes:
            self._persist(scope)

    # -------------------------------------------------------------- internals
    def _persist(self, scope: str) -> None:
        self._counters.write(META_PREFIX + scope, self.current(scope))
        self._counters.write(REVISION_PREFIX + scope, self.revision(scope))

    @staticmethod
    def _scope_from_key(key: str) -> str:
        parts = key.split(":")
        # epoch:<scope>... -> everything after the leading kind
        return ":".join(parts[1:]) if len(parts) > 1 else ""
