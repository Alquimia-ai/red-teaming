"""The key layout. The only place in the repo that knows how to build a key.

Two namespaces, because content addressing and resumption pull in opposite directions: resumption
needs the key *before* the content exists, and a digest is only known *after*. So traces go straight
to a deterministic path -- their key comes from the plan, and its existence answers the resume
question with no indirection -- while the probe set goes by digest, so two runs over the same
knowledge base and catalogue store one blob and the second skips the write. What spares a run its
own regeneration is `probes.json`, its pointer into that namespace.

Deduplicating traces would be meaningless: every conversation is unique by definition.

Each artifact is written at the moment it stops being able to change. That is the whole criterion,
and it is why traces are written one at a time as they close rather than in a batch at the end.
Nothing under a run's prefix is ever rewritten, and there is no cache that would need to be.
"""

from __future__ import annotations

import re
from typing import Final

BLOBS: Final = "blobs"
RUNS: Final = "runs"

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{32,64}$")


def _checked(kind: str, value: str) -> str:
    """Refuse anything that could climb out of its prefix or collide by normalisation.

    A key is a security boundary as much as an address: `..` in a run id is a path traversal, and
    two ids that differ only by case are one key on a store that folds case.
    """
    if not _SAFE.match(value):
        raise ValueError(f"unsafe {kind}: {value!r}")
    return value


def blob(digest: str) -> str:
    """Content, immutable and deduplicated."""
    if not _DIGEST.match(digest):
        raise ValueError(f"not a hex digest: {digest!r}")
    return f"{BLOBS}/{digest}"


CAPABILITIES: Final = "capabilities"


def store_probe() -> str:
    """The one key a backend writes about itself: the proof that it refuses a second write.

    Under its own root so no listing of runs or assets ever sees it. Written at most once per bucket
    -- the second attempt is the proof -- and never read, because what it holds is nothing; what
    matters is that it cannot be written again.
    """
    return f"{CAPABILITIES}/conditional-write"


# ---- versioned assets -------------------------------------------------------------------------

CATALOGUES: Final = "catalogues"
PRIORS: Final = "priors"

_VERSION_WIDTH = 5


def asset_prefix(root: str, label: str, name: str) -> str:
    return f"{root}/{_checked(f'{label} name', name)}"


def asset(root: str, label: str, name: str, version: int) -> str:
    """One published version of one asset.

    Versioned explicitly rather than through a `current` pointer, because the store only appends and
    a pointer cannot be moved. Zero-padded so a sorted listing puts the newest last, which lets "the
    newest version" be read off a listing rather than from a timestamp the interface does not
    expose.

    One shape for every published asset -- the catalogue bundles and the natural-query priors --
    because two copies of a key format is two chances for one of them to be padded differently and
    sort wrong.
    """
    if version < 1:
        raise ValueError(f"{label} versions start at 1: {version}")
    return f"{asset_prefix(root, label, name)}/v{version:0{_VERSION_WIDTH}d}.json"


def parse_asset(root: str, key: str) -> tuple[str, int] | None:
    """`(name, version)` for a key under `root`, or None when it is not one."""
    match = re.fullmatch(rf"{root}/([^/]+)/v(\d{{{_VERSION_WIDTH}}})\.json", key)
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def catalogues_prefix() -> str:
    return CATALOGUES


def catalogue_prefix(name: str) -> str:
    return asset_prefix(CATALOGUES, "catalogue", name)


def catalogue(name: str, version: int) -> str:
    """The catalogue itself: plugins and strategies. The version's commit key -- the sidecars land
    before it, so a half-written publication is never exposed as a complete version."""
    return asset(CATALOGUES, "catalogue", name, version)


def _sidecar(name: str, version: int, kind: str) -> str:
    if version < 1:
        raise ValueError(f"catalogue versions start at 1: {version}")
    return f"{catalogue_prefix(name)}/v{version:0{_VERSION_WIDTH}d}.{kind}.json"


def catalogue_contract(name: str, version: int) -> str:
    """The contract sidecar of one catalogue version: the principles its plugins charge.

    Versioned with the catalogue because a plugin names a principle by id, and a contract revised
    on its own would let a published catalogue charge a principle that no longer exists -- or
    grade a finished run against a rubric its author never saw. Not a catalogue key:
    `parse_catalogue_key` ignores it, so a listing still counts versions correctly.
    """
    return _sidecar(name, version, "contract")


def catalogue_grounding(name: str, version: int) -> str:
    """The grounding sidecar of one catalogue version: which strategies need a knowledge base.

    A strategy whose phrasing leans on a premise has nothing to lean on when the run declares no
    brain, and gaussia's no-knowledge-base path answers that by removing the `{premise}` slot --
    turning `"What does {premise} cover?"` into `"What does cover?"`. Which strategies are in that
    position is not derivable from anything gaussia models: `StrategySpec` has no field for it and
    drops an unknown key silently, so the declaration is data beside the catalogue, versioned with
    it.
    """
    return _sidecar(name, version, "grounding")


def catalogue_delivery(name: str, version: int) -> str:
    """The delivery sidecar of one catalogue version: how each strategy's probe reaches the target.

    One static turn, or a conversation an attacker steers -- a third axis beside the premise and the
    phrasing, and one `StrategySpec` has no field for. Declared beside the catalogue and versioned
    with it: a delivery over a strategy a later version renamed is a delivery of nothing.
    """
    return _sidecar(name, version, "delivery")


def parse_catalogue_key(key: str) -> tuple[str, int] | None:
    """`(name, version)` for a catalogue key, or None if it is not one -- the sidecars included."""
    return parse_asset(CATALOGUES, key)


def priors_prefix() -> str:
    return PRIORS


def prior_prefix(name: str) -> str:
    return asset_prefix(PRIORS, "prior", name)


def prior(name: str, version: int) -> str:
    """One published version of one natural-query prior -- the pool of phrasings the realism
    estimator measures a category against."""
    return asset(PRIORS, "prior", name, version)


def parse_prior_key(key: str) -> tuple[str, int] | None:
    return parse_asset(PRIORS, key)


# ---- one run ----------------------------------------------------------------------------------


def run_prefix(run_id: str) -> str:
    return f"{RUNS}/{_checked('run id', run_id)}"


def spec(run_id: str) -> str:
    """Written when the run is accepted. Immutable from that moment: what ran is what this file
    says, not what anyone remembers asking for."""
    return f"{run_prefix(run_id)}/spec.json"


def probes(run_id: str) -> str:
    """Written when generation closes, once. Points at a blob, so the set itself deduplicates, and
    records what generation reported about the set -- the catalogue versions it generated from, the
    engines that ran, what could not be built.

    Its existence is what pins the run's probe set: a runner that finds it reads the digest from
    here and never generates again, so a catalogue published between two launches of one run cannot
    change the plan.
    """
    return f"{run_prefix(run_id)}/probes.json"


def category(run_id: str, category_id: str) -> str:
    """One category the search evaluated, written as the search closes it."""
    return f"{run_prefix(run_id)}/categories/{_checked('category id', category_id)}.json"


def traces_prefix(run_id: str) -> str:
    return f"{run_prefix(run_id)}/traces"


def trace(run_id: str, attack_id: str, replica_idx: int) -> str:
    """Written as each conversation closes.

    JSONL + zstd: it is written incrementally, read as a stream, and gaining a field on the
    conversation does not force a schema change.
    """
    if replica_idx < 0:
        raise ValueError(f"replica index cannot be negative: {replica_idx}")
    return f"{traces_prefix(run_id)}/{_checked('attack id', attack_id)}/{replica_idx}.jsonl.zst"


def trace_failure(run_id: str, attack_id: str, replica_idx: int) -> str:
    """The marker that separates "never ran" from "failed without remedy".

    Listing the store says what is there, not why what is missing is missing. Without this marker
    the difference cannot tell the two apart, and a run that failed looks like a run that was never
    started.
    """
    if replica_idx < 0:
        raise ValueError(f"replica index cannot be negative: {replica_idx}")
    return f"{traces_prefix(run_id)}/{_checked('attack id', attack_id)}/{replica_idx}.failed"


def dataset(run_id: str) -> str:
    """The attack dataset, written when conduction closes: one session per replica, in one JSON
    array. Built from the traces and the control grades."""
    return f"{run_prefix(run_id)}/dataset.json"


def profile(run_id: str) -> str:
    """The weakness profile, written the moment profiling closes.

    A control artifact: how the run read the assistant in order to decide what to press on. Written
    before the search starts rather than at the end, so a process that dies during the search still
    leaves the profile it searched from.
    """
    return f"{run_prefix(run_id)}/profile.json"


def exploit(run_id: str) -> str:
    """The exploitation report, written the moment the search closes.

    A control artifact: the categories the search ranked, the queries that crossed its threshold,
    and which implementation of each substitutable piece produced them. Absent on a run that did
    not exploit; the manifest's components say why.
    """
    return f"{run_prefix(run_id)}/exploit.json"


def searched(run_id: str) -> str:
    """What the search reported about itself, written the moment it closes -- ran or failed.

    The report is `exploit`, and a search that failed leaves none; but it, too, sent generated
    queries at the assistant, so a resumed attempt must not search again either way. This marker is
    what says "the search was attempted", with what it said about itself, and it is read before an
    exploiter is built.
    """
    return f"{run_prefix(run_id)}/searched.json"


SESSIONS: Final = "sessions"


def sessions_prefix(run_id: str) -> str:
    return f"{run_prefix(run_id)}/{SESSIONS}"


def session(run_id: str, name: str) -> str:
    """One session of the attack dataset kept on its own, written the moment it exists.

    The search's session is written as soon as the search closes -- before the dataset, which is
    assembled later and would die with the process. A resumed attempt reads it back rather than
    searching again, which is the difference between resuming and re-attacking with generated
    queries.
    """
    return f"{sessions_prefix(run_id)}/{_checked('session name', name)}.json"


def conduction(run_id: str) -> str:
    """What conduction reported about itself, written beside the dataset when it closes.

    A resumed attempt that finds the dataset does not repeat the attack, and this is how it still
    carries the provenance -- which judge profiled, whether the search ran -- into the manifest.
    """
    return f"{run_prefix(run_id)}/conduction.json"


def manifest(run_id: str) -> str:
    """Written when the run closes, and only then. The one file a consumer has to read to know
    whether a run is usable and what it can be compared against.

    Its existence means COMPLETE. A failed attempt never writes here -- see `failure` -- because the
    store only appends, so whatever lands under this key is the run's last word.
    """
    return f"{run_prefix(run_id)}/manifest.json"


FAILURES: Final = "failures"


def failures_prefix(run_id: str) -> str:
    return f"{run_prefix(run_id)}/{FAILURES}"


def failure(run_id: str, attempt: str) -> str:
    """One attempt that died after the attack began, under its own key.

    Never `manifest.json`. That key means the run closed, and in a store that only appends a failure
    written there would be permanent: the resumed runner, the status endpoint and the job's exit
    code all read its existence as completion, and the only remedy would be a new run id -- which
    re-attacks the assistant. A failure record is evidence about one attempt; the next attempt
    resumes from the difference exactly as if the process had been killed.
    """
    return f"{failures_prefix(run_id)}/{_checked('attempt', attempt)}.json"


ATTEMPTS: Final = "attempts"


def attempts_prefix(run_id: str) -> str:
    return f"{run_prefix(run_id)}/{ATTEMPTS}"


def attempt(run_id: str, attempt: str) -> str:
    """The marker one attempt writes before it does anything else.

    A failure record says an attempt died; on its own it cannot say whether a later attempt has
    since begun. Without the marker the status reads `failed` for as long as the relaunch takes to
    close the run -- and a consumer's poll loop, which stops on `failed`, gives up exactly when the
    retry policy resumed. This is what makes "the newest attempt" readable off a listing: `failed`
    holds only while the newest attempt is the one that left a failure record, under the same id.
    """
    return f"{attempts_prefix(run_id)}/{_checked('attempt', attempt)}.json"


def parse_spec_key(key: str) -> str | None:
    """The run id a frozen spec belongs to, or None if the key is not one. Listing `runs/` and
    keeping these is how the runs a deployment accepted are enumerated without a table."""
    match = re.fullmatch(rf"{RUNS}/([^/]+)/spec\.json", key)
    return match.group(1) if match else None


def parse_attempt_key(key: str) -> tuple[str, str] | None:
    """`(run_id, attempt)` for an attempt marker, or None if it is not one."""
    match = re.fullmatch(rf"{RUNS}/([^/]+)/{ATTEMPTS}/([^/]+)\.json", key)
    if match is None:
        return None
    return match.group(1), match.group(2)


def parse_failure_key(key: str) -> tuple[str, str] | None:
    """`(run_id, attempt)` for a failure record, or None if it is not one. The attempt is the same
    id the marker carries, which is how a record is matched to the attempt that wrote it."""
    match = re.fullmatch(rf"{RUNS}/([^/]+)/{FAILURES}/([^/]+)\.json", key)
    if match is None:
        return None
    return match.group(1), match.group(2)


def parse_trace_key(key: str) -> tuple[str, str, int] | None:
    """`(run_id, attack_id, replica_idx)` for a trace key, or None if it is not one.

    The inverse of `trace`, and the reason resumption is a set difference: listing the prefix yields
    keys, and this turns them back into the plan's own coordinates.
    """
    match = re.fullmatch(rf"{RUNS}/([^/]+)/traces/([^/]+)/(\d+)\.jsonl\.zst", key)
    if match is None:
        return None
    return match.group(1), match.group(2), int(match.group(3))
