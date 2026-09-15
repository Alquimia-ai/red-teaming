# ADR-006: Strategies declare what a probe says and deliveries declare how it reaches the target

**Status:** Superseded by ADR-014
**Date:** 2026-09-10
**Tags:** engine, catalogue, contracts, evidence

Superseded by [ADR-014](./014-catalogues-embed-strategy-execution-and-brain-requirements.md).

## Context

A probe used to be one exchange: the query was sent, the answer was read, the trace held two turns.
Some failures of an assistant only appear across turns -- an escalation that builds toward the
instructions it was given, a pressure that mounts after a first refusal -- and a catalogue has to be
able to say that a strategy is a conversation rather than a question. The catalogue is data; the
model that writes the follow-up turns is the run's decision; gaussia's Profiler sends one query per
probe and grades one answer, and the recorder and the resuming target map the k-th exchange to the
k-th unit of the plan.

Three places could own the conversation loop: the catalogue, by shipping the follow-up turns as
data; the conduction loop, by calling the target several times per probe; or the governed door, by
running the whole conversation inside one `send`.

## Decision Drivers

- The catalogue stays data and never names a model.
- gaussia is not forked: the Profiler sees one exchange per probe, whatever the delivery.
- Every turn of a conversation is charged to the budget and paced like any other call.
- The whole conversation is one trace under the unit's one key, so resumption is unchanged.
- A conversation that stops early is still evidence, and the record says why it stopped.

## Considered Options

### Option A: Scripted follow-ups in the catalogue — Rejected

The strategy carries the follow-up turns as text; the loop sends them in order.

**Pros:** deterministic; no model to bind.

**Cons:** a follow-up written before the assistant answered cannot react to what it said, which is
the whole point of an escalation; a catalogue that carries prose for every turn is a script, not a
taxonomy.

### Option B: A loop in conduction calling the target N times — Rejected

Conduction calls `send` once per turn and hands the Profiler the last answer.

**Pros:** the door stays a single call.

**Cons:** N exchanges surface for one unit, so the positional mapping the recorder and the resuming
target rely on shifts every unit after it by one; the Profiler's own loop is gaussia's, and driving
it turn by turn means forking it.

### Option C: The delivery sidecar declares the shape and the door conducts it — Chosen

A strategy declares what it says: entity kind, construction, premise, phrasing. The catalogue's
`delivery.json` declares how each strategy reaches the target: one turn, or many turns steered by an
attacker named by **id** with a bound on the agent's turns. The run binds each id to a model in
`RunSpec.attackers`, with its own credential reference, and the API refuses a run whose catalogues
name an id the spec does not bind. The governed door reads the k-th planned delivery for the k-th
live exchange and, for a conducted one, runs the conversation inside one `send`: the opening goes
out, the attacker writes the next user turn from the transcript and the plugin's objective, every
turn passes through the same budget, pacing and retry policy, and gaussia grades the final answer --
what the escalation obtained. The recorder writes the whole conversation as one trace under the
unit's key, with labels for the technique, the depth, the attacker id, the session and why it ended.
Exchanges past the plan -- the search's own -- are static.

**Pros:** the catalogue stays data; gaussia is untouched; the budget sees every call; resumption and
coverage are unchanged because a unit is still one key.

**Cons:** the sidecar is a second file to keep in step with the catalogue; an attacker model is one
more instrument the spec has to declare; a conversation's length is bounded by declaration rather
than measured.

## Decision

Adopt Option C. Delivery is a third axis of a strategy, declared beside the catalogue and versioned
with it; the attacker is an id in the catalogue and a model in the run; the conversation happens
inside the governed door, and a trace carries all of it.

## Consequences

### Positive

- An escalation reacts to the assistant's actual answers, in the run's declared language and
  register.
- A conducted unit costs N calls and is charged N times; the budget is honest about load.
- The trace says how the conversation was delivered, how deep it went, who steered it and why it
  stopped -- the attacker's judgement, the bound, the target failing, the attacker's provider
  failing, the budget.
- A relaunch replays the last answer of a closed conversation, which is the one that was graded.

### Negative / Trade-offs

- A conversation that closes early because the attacker's provider failed is shorter than declared
  and is still counted as closed; the manifest reports how many ended that way.
- Two catalogues delivering one strategy id differently are refused at the gate rather than
  reconciled.
- The attacker's "done" is a judgement the run does not audit; it ends conversations and is never a
  grade.

## Implementation Notes

- `redteam_store.delivery`: the sidecar's shape, `Delivery`, `Objective`, `merged`,
  `attackers_named`, `objectives`.
- `redteam_engine.planned`: `PlannedDelivery`, `Conversation`, `conduct_many`, the `ENDED_BY_*`
  reasons, `planned_deliveries`, `attackers_named_by`, `delivery_provenance`.
- `redteam_engine.governed.GovernedTarget.send`: the k-th live exchange gets the k-th planned
  delivery; past the plan is static.
- `redteam_engine.attacker.Attacker`: the method is the only prose the platform owns; objective,
  approach and register come from the catalogue and the run.
- `redteam_contracts.trace.TraceLabels`: `orchestration_technique`, `turn_depth`, `attacker`,
  `session_id`, `ended`.

## Related ADRs

- Builds on [ADR-004](./004-models-are-configuration-and-one-governed-door-to-the-target.md)
- Complements [ADR-005](./005-catalogue-bundles-name-constructions-the-runtime-builds.md)
