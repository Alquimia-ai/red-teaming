"""The attackers a run binds, built by id from what the spec declared.

A catalogue names an attacker by id and never a model; the run binds the id to a model in
`RunSpec.attackers`, with its own credential reference and its own line in the provenance. This is
where the two meet: every id the plan's units are delivered through is built here, from the spec,
through the same model builder and the same resolver as every other model the run declared.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

from redteam_engine.attacker import Attacker
from redteam_judges.models import build_chat_model

if TYPE_CHECKING:
    from redteam_contracts.run_spec import RunSpec
    from redteam_engine.governed import SecretResolver


class AttackerUnbound(RuntimeError):
    """A live unit is delivered through an attacker id the spec binds no model to.

    The API's gate refuses this before a run is accepted; the engine refuses it again before the
    first turn rather than trusting that it did, because a spec written some other way would
    otherwise attack the assistant for every static unit and die at the first conducted one.
    """

    def __init__(self, unbound: Sequence[str]) -> None:
        super().__init__(
            f"the plan delivers units through attackers {sorted(unbound)} and the spec binds no "
            f"model under those ids; bind each in `attackers`"
        )


def attackers_for(
    spec: RunSpec, resolver: SecretResolver, named: Collection[str]
) -> dict[str, Attacker]:
    """The attackers the plan's units are delivered through, built from what the spec bound, by id.

    Every id the plan names, not only the ones this attempt's live units need: the manifest names
    the attackers that took part in the run, and one that steered a conversation an earlier attempt
    closed took part. A binding the plan never names costs nothing and is named nowhere. Each is
    built with the run's context so it writes in the language the assistant is addressed in.
    """
    needed = sorted(named)
    if not needed:
        return {}
    unbound = [name for name in needed if name not in spec.attackers]
    if unbound:
        raise AttackerUnbound(unbound)
    attackers: dict[str, Attacker] = {}
    for name in needed:
        model_spec = spec.attackers[name]
        api_key = resolver.resolve(model_spec.secret_ref) if model_spec.secret_ref else None
        attackers[name] = Attacker(build_chat_model(model_spec, api_key=api_key), spec.context)
    return attackers
