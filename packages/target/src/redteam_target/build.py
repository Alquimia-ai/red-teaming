"""Build the Alquimia or replay target selected by ConnectorSpec.kind.

Credentials arrive resolved; this package does not depend on secret backends. New target kinds
require an explicit implementation and tests for failures and sessions."""

from __future__ import annotations

from collections.abc import Callable

from gaussia.core.target_assistant import TargetAssistant

from redteam_contracts.run_spec import ConnectorSpec
from redteam_target.alquimia import ALQUIMIA, build_alquimia
from redteam_target.replay import REPLAY, build_replay

Builder = Callable[[ConnectorSpec, str | None], TargetAssistant]

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
