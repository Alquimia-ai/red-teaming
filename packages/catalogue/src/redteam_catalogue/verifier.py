"""Confirming a hook's `doc` label against the brain, twice over.

gaussia's `NearMissVerifier` answers the question its own construction cannot: a premise absent
from the boundary can still be *indistinguishable* from something present, and an assistant handed
one retrieves the real entity, answers about it correctly, and gets charged with fabricating. Its
thresholds were calibrated over 136 Spanish product names, which is this domain.

What it cannot do is prove presence. It checks membership in whatever the enumerator returns, and
that is a set comparison. A brain can do better: `proves_membership` is an inclusion proof against
the snapshot, so a `doc = 1` label rests on a hash rather than on a lookup succeeding. Composing
the two is what lets both labels mean something -- absence defended against near misses, presence
against a stale or partial read of the base.

**Nobody is dropped.** A hook whose label did not hold still becomes a probe, and
`KnowledgeHook.verified` carries the verdict. Silently shrinking a probe set reports a smaller
denominator as though the whole thing had been measured, and that is the failure this file exists
to catch rather than to commit.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from gaussia.core.hook_verifier import HookVerifier
from gaussia.generators.roastme.probes.verification import NearMissVerifier

if TYPE_CHECKING:
    from gaussia.core.entity_enumerator import EntityEnumerator
    from gaussia.schemas.roastme import Document, KnowledgeHook

    from redteam_contracts.kb import KnowledgeBase


class BrainHookVerifier(HookVerifier):  # type: ignore[misc]  # gaussia ships no stubs
    """The near-miss check, with the brain's inclusion proof behind the presence half.

    Args:
        kb: The base, for `proves_membership`. An inclusion proof rather than a search, which is
            what lets `doc = 1` mean "the base carries this" rather than "we found it".
        enumerator: How the boundary is read. The same object the engine derived its labels from,
            so the verifier checks the view the label came from rather than a second reading that
            could disagree with it.
        name_like_kinds: The kinds the near-miss check applies to. Naming them is the normal case:
            the thresholds fit short names and misfire on sentence-shaped entities, where a whole
            statement scores above the ratio against its own one-digit flip -- so an unnamed kind
            would have every legitimate falsification rejected.
    """

    def __init__(
        self,
        kb: KnowledgeBase,
        enumerator: EntityEnumerator,
        name_like_kinds: Iterable[str] = (),
    ) -> None:
        self._kb = kb
        self._near_miss = NearMissVerifier(enumerator, name_like_kinds)
        self._name_like = frozenset(name_like_kinds)

    def verify(self, hook: KnowledgeHook, documents: list[Document]) -> bool | None:
        """Whether the label holds, or None when nothing could check it.

        None is a real answer and never `False`: reporting an unperformed check as a wrong label is
        the same overclaim as reporting an untested variable as compliant.
        """
        if hook.doc == 1:
            # Presence is the half a hash can settle, so it is settled with one rather than with a
            # second membership test that would only restate what the engine already believed.
            proved: bool = self._kb.proves_membership(hook.kind, hook.references)
            return proved
        if hook.kind not in self._name_like:
            return None
        verdict: bool | None = self._near_miss.verify(hook, documents)
        return verdict

    def collision(self, hook: KnowledgeHook, documents: list[Document]) -> str | None:
        """What an absence premise collided with, so a report names it instead of counting it.

        The difference between "7 probes could not defend their label" and a list somebody can read
        and act on.
        """
        if hook.doc == 1 or hook.kind not in self._name_like:
            return None
        collided: str | None = self._near_miss.collision(hook, documents)
        return collided
