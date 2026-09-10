"""The trace: a conversation, frozen.

A trace stops being work-in-progress and becomes evidence at exactly one moment -- when it is
written. Before that it is mutable state in the runner's memory; after, it is immutable and
citable. Nothing in this module carries a score: the grades the control judge produced while the
run steered itself are control, recorded beside the dataset, and the trace is the evidence they
were produced from.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from redteam_contracts.failure import TransportFailure


class Role(StrEnum):
    ATTACKER = "attacker"
    AGENT = "agent"


class Turn(BaseModel):
    """One utterance. Agent turns are what gets graded; attacker turns are context."""

    model_config = ConfigDict(frozen=True)

    idx: int = Field(ge=0)
    role: Role
    content: str
    failed: bool = False
    """Set when the exchange failed at the transport level.

    A refusal to answer is *not* a failure -- it is a legitimate response, and whether it violates a
    principle is the rubric's call. Only a broken exchange sets this, and a failed turn is recorded
    ungraded rather than scored as compliance.
    """
    failure_reason: str | None = None
    failure: TransportFailure | None = None
    """What the failure was, as a record: the kind, the status, what the target said."""


class TraceLabels(BaseModel):
    """Observational labels, 1:1 with the trace.

    Observational is the whole point: these describe how the attack was conducted and what it
    aimed at, never what the assistant's answer meant. A `Turn.failure` is a different axis: it
    types what the *channel* did, and says nothing about the assistant.
    """

    model_config = ConfigDict(frozen=True)

    orchestration_technique: str | None = None
    """How the exchange was delivered: one static turn, or a conversation an attacker steered."""

    turn_depth: int = Field(default=0, ge=0)
    """How many times the agent answered in this trace. One for a static delivery."""

    attacker: str | None = None
    """The id of the attacker that wrote the follow-up turns, as the catalogue named it. Never the
    model: which model played the id is the run's provenance, in the manifest's components."""

    session_id: str | None = None
    """The conversation as the target's own runtime named it, when it named one. What lets a trace
    be taken back to the target's own log of the exchange."""

    ended: str | None = None
    """Why a conducted conversation stopped where it did -- the attacker judged it done, the bound
    was reached, the target failed, the attacker failed, the budget ran out. Absent on a static
    delivery. A conversation shorter than its bound is still evidence; this says why it is
    shorter."""

    attacked_entity: str | None = None
    in_out_of_scope: bool | None = None

    plugin: str | None = None
    """The risk family the attack charged, as the catalogue named it. `None` for a control, or for
    a conversation the search generated beyond the plan."""

    strategy: str | None = None
    """How the probe was built, by the strategy's id."""

    principle: str | None = None
    """The principle of the contract the plugin charges. What the control judge graded this
    conversation against first; every principle is graded, this is the one the attack aimed at."""


class Trace(BaseModel):
    """One conversation with the agent, closed and immutable."""

    model_config = ConfigDict(frozen=True)

    trace_id: str
    run_id: str
    attack_id: str
    replica_idx: int = Field(ge=0)
    probe_id: str
    turns: tuple[Turn, ...]
    labels: TraceLabels

    @property
    def agent_turns(self) -> tuple[Turn, ...]:
        """The turns that get graded. The attacker's own words are never scored."""
        return tuple(t for t in self.turns if t.role is Role.AGENT)

    @property
    def has_ungraded_turns(self) -> bool:
        return any(t.failed for t in self.agent_turns)
