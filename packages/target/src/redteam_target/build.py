"""Which adapter a spec's `kind` resolves to, and how one gets built.

A closed switch rather than a registry. Two kinds exist and a third is a design decision, not a
plugin: adding one means deciding how it reports failures, how it threads sessions and how the
governed door retries it, and that belongs in this package with tests beside it.

**The credential arrives resolved, not as a reference.** Resolving a `secret_ref` is the secrets
package's job, and keeping it out of here is what stops this package from depending on the secrets
backend. The runner holds both and hands the value in. Same shape as the model factory, for the same
reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from redteam_target.alquimia import ALQUIMIA, build_alquimia
from redteam_target.replay import REPLAY, build_replay

if TYPE_CHECKING:
    from gaussia.core.target_assistant import TargetAssistant

    from redteam_contracts.run_spec import ConnectorSpec

Builder = Callable[["ConnectorSpec", "str | None"], "TargetAssistant"]

_BUILDERS: dict[str, Builder] = {
    ALQUIMIA: build_alquimia,
    REPLAY: build_replay,
}

KINDS: tuple[str, ...] = tuple(sorted(_BUILDERS))
"""Every kind a `ConnectorSpec` may name. Two, on purpose."""


class UnknownTarget(ValueError):
    """A `kind` this package does not ship. A typo, or a transport nobody wrote."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"no target adapter for kind {kind!r}. The kinds are: {', '.join(KINDS)}")
        self.kind = kind


def build_target(spec: ConnectorSpec, credential: str | None) -> TargetAssistant:
    """The raw adapter this spec names. Not governed -- see the package docstring.

    Raises:
        UnknownTarget: `spec.kind` is neither of the two shipped kinds.
        ValueError: The kind's own coordinates are missing from `spec.options`.
    """
    build = _BUILDERS.get(spec.kind)
    if build is None:
        raise UnknownTarget(spec.kind)
    return build(spec, credential)
