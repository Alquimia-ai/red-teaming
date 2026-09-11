"""The checks a run passes before it is accepted, and why they are all cheap.

None of them costs a conversation with the assistant. That is the design: everything expensive to be
wrong about is settled before the first turn -- a catalogue nobody published, an attacker nobody
bound, a construction with no generator to write it, a ceiling nothing enforces, a credential the
process would have read off its own environment. Each is refused with the reason, with nothing
frozen and nothing launched, and the message says what to change.

Pure over its inputs. What has to be read from the store -- which catalogues exist, what they
deliver through, what the run would generate -- is read by the wiring and handed in, so this module
can be tested with data alone.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from redteam_contracts.run_id import check
from redteam_contracts.run_spec import CONNECTOR_KINDS, ModelSpec, RunSpec
from redteam_contracts.serving import ServingPath
from redteam_settings.config import ENV_PREFIX


class ValidationFailure(ValueError):
    """Rejected at the gate. The consumer fixes the request; retrying unchanged changes nothing."""


def resolve_versions(spec: RunSpec, published: Mapping[str, int]) -> dict[str, int]:
    """The version each catalogue the run names generates from: the consumer's pin when it names
    one, else the newest published. **The one mapping**, used by every read the gate makes and then
    frozen into the spec.

    A name the store does not carry is left out rather than refused here: `_check_catalogues`
    refuses it by name, and a version for it would describe nothing.

    Raises:
        ValidationFailure: The consumer pinned a version nobody published.
    """
    versions: dict[str, int] = {}
    for name in spec.catalogues:
        if name not in published:
            continue
        pinned = spec.catalogue_versions.get(name)
        if pinned is None:
            versions[name] = published[name]
        elif pinned > published[name] or pinned < 1:
            raise ValidationFailure(
                f"catalogue {name!r} has no published version {pinned}; the newest is "
                f"{published[name]}"
            )
        else:
            versions[name] = pinned
    return versions


def validate(
    spec: RunSpec,
    *,
    known_catalogues: frozenset[str],
    attackers_named: frozenset[str] = frozenset(),
    model_driven: frozenset[str] = frozenset(),
) -> None:
    """Every check. Raises `ValidationFailure` naming the first one that failed.

    Args:
        known_catalogues: The names the store carries at least one version of.
        attackers_named: The attacker ids the strategies this run will generate are delivered
            through, per the catalogues' delivery sidecars at the frozen versions.
        model_driven: The construction keys the run's effective selection names that need the
            run's generator and context to be built.
    """
    _check_run_id(spec)
    _check_knowledge_base(spec)
    _check_catalogues(spec, known_catalogues)
    _check_attackers_bound(spec, attackers_named)
    _check_constructions_have_what_they_need(spec, model_driven)
    _check_connector(spec)
    _check_budget(spec)
    _check_model_credentials(spec)
    _check_secret_references(spec)


def _check_run_id(spec: RunSpec) -> None:
    """One rule for the id, applied here rather than as a model validator, so the spec stays
    representable and the refusal reads as a 400 that names the rule."""
    try:
        check(spec.run_id)
    except ValueError as refused:
        raise ValidationFailure(str(refused)) from refused


def _check_knowledge_base(spec: RunSpec) -> None:
    """Pinned by digest. A tag moves like a git branch, and longitudinal validity needs an oracle
    nobody can move out from under a finished run."""
    if spec.kb_ref is None:
        return
    if not spec.kb_ref.digest.startswith("sha256:"):
        raise ValidationFailure(
            f"kb_ref must be pinned by digest, got {spec.kb_ref.digest!r}. A tag moves, and a run "
            f"whose oracle can move cannot be compared with anything later."
        )


def _check_catalogues(spec: RunSpec, known: frozenset[str]) -> None:
    if not spec.catalogues:
        raise ValidationFailure("a run names at least one catalogue to generate from")
    missing = tuple(c for c in spec.catalogues if c not in known)
    if missing:
        raise ValidationFailure(
            f"unknown catalogues {missing}. Published: {sorted(known)}. Retrying will not help; "
            f"the request has to name a catalogue that exists."
        )


def _check_attackers_bound(spec: RunSpec, named: frozenset[str]) -> None:
    """Every attacker the run's catalogues will conduct with is a model the spec binds.

    A delivery sidecar names an attacker by id and the spec binds the id to a model. With free-form
    ids a typo is otherwise silent: the runner would reach the first conducted unit, find no model
    under the name, and die after the assistant had been attacked for every static unit before it.
    Refused here instead, by name, before anything is written.
    """
    unbound = sorted(named - set(spec.attackers))
    if unbound:
        raise ValidationFailure(
            f"the catalogues {sorted(spec.catalogues)} deliver strategies this run generates "
            f"through attackers {unbound}, and the spec binds no model under those ids. Bind each "
            f"in `attackers`, or narrow the run past the strategies that name them. An attacker id "
            f"is a requirement the catalogue states; the model is a choice the run makes."
        )


def _check_constructions_have_what_they_need(spec: RunSpec, model_driven: frozenset[str]) -> None:
    """A construction that writes premises with a model needs the run's generator and context.

    Refused here rather than at generation, where the same refusal costs a pulled brain and leaves
    a frozen spec no attempt can ever finish. A model asked to write premises with no language in
    front of it answers in the prompt's language, and the run then measures the assistant's handling
    of English questions about Spanish products.
    """
    if not model_driven:
        return
    missing = []
    if spec.context is None:
        missing.append("context")
    if spec.generator is None or not spec.generator.declares_provider():
        missing.append("generator")
    if missing:
        raise ValidationFailure(
            f"the run's selection names the constructions {sorted(model_driven)}, which write "
            f"premises with a model, and the spec declares no {' and no '.join(missing)}. Declare "
            f"them, or narrow the run past the strategies that name these constructions."
        )


def _check_connector(spec: RunSpec) -> None:
    """A kind something builds, a credential, and a safe mode compatible with what the target can
    do.

    An assistant that can act -- move money, book, send messages -- fires real side effects when
    attacked, and the search sends far more exchanges than the profiler does. Attacking one without
    a sandbox agreement is not a configuration mistake, so it is refused here.
    """
    if spec.connector.kind not in CONNECTOR_KINDS:
        raise ValidationFailure(
            f"connector kind {spec.connector.kind!r} names no adapter this platform ships; the "
            f"kinds are {', '.join(CONNECTOR_KINDS)}"
        )
    if not spec.connector.secret_ref:
        raise ValidationFailure("the connector needs a secret reference")
    if spec.connector.can_act and not spec.connector.safe_mode:
        raise ValidationFailure(
            f"the connector declares capabilities {list(spec.connector.declared_capabilities)} and "
            f"safe mode is off. Attacking a target that can act fires real side effects, so this "
            f"needs a sandbox agreement before the first turn."
        )


def _check_budget(spec: RunSpec) -> None:
    """A ceiling the run would not enforce is refused rather than accepted in silence.

    No target adapter sees the assistant's token usage, so no reader could ever charge against
    `max_tokens`. Accepting it would tell a consumer their run was bounded when it was not. The two
    ceilings that are enforced are named in the refusal.
    """
    if spec.budget.max_tokens is not None:
        raise ValidationFailure(
            "budget.max_tokens is not enforced: no target adapter reports the assistant's token "
            "usage, so a run could not be stopped on it. Drop it, or bound the run with "
            "budget.max_target_calls or budget.max_wall_seconds, which are enforced."
        )


def _check_model_credentials(spec: RunSpec) -> None:
    """Every hosted model carries a credential reference, or the run is refused naming the role.

    A hosted client handed no key reads the process's own -- a credential the spec never declared,
    measuring. The builder refuses that at wiring time, which under the runner is after the
    assistant was attacked; the gate refuses it here, before, and by role. A model naming no
    provider is the stand-in path and builds no client; a self-hosted one answers whoever reaches
    it.
    """
    for role, model in _declared_models(spec):
        hosted = model.declares_provider() and model.serving_path is ServingPath.HOSTED_API
        if hosted and not model.secret_ref:
            raise ValidationFailure(
                f"{role} names provider {model.provider!r} with no secret reference; a hosted "
                f"model builds only with the credential its spec declared, never with one the "
                f"process happens to hold"
            )


def _check_secret_references(spec: RunSpec) -> None:
    """No secret reference in the platform's own namespace, wherever the spec names one.

    The runner's own wiring travels in variables under `REDTEAM_`, and the dispatcher lays the run's
    secrets over them by name. A reference called `REDTEAM_S3_ENDPOINT` would be materialised as
    exactly that variable and repoint the runner's store.
    """
    named: list[tuple[str, str | None]] = [("connector", spec.connector.secret_ref)]
    named += [(role, model.secret_ref) for role, model in _declared_models(spec)]
    for role, ref in named:
        if ref and ref.startswith(ENV_PREFIX):
            raise ValidationFailure(
                f"{role} names secret reference {ref!r}, which is in the platform's own "
                f"{ENV_PREFIX}* namespace; materialised into the runner's environment it would "
                f"overwrite its wiring rather than hand it a credential"
            )


def _declared_models(spec: RunSpec) -> Iterator[tuple[str, ModelSpec]]:
    """Every model the spec declares, each with the role that names it."""
    for role in ("judge", "generator", "embedder"):
        model: ModelSpec | None = getattr(spec, role)
        if model is not None:
            yield role, model
    for attacker_id, model in spec.attackers.items():
        yield f"attackers[{attacker_id!r}]", model
