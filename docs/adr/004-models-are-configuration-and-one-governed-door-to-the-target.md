# ADR-004: Models are configuration and one governed door to the target

**Status:** Accepted
**Date:** 2026-09-10
**Tags:** judges, target, knowledge, provenance

## Context

A run uses several models -- a control judge that grades every exchange, a generator that writes
premises, attackers that steer conversations, an embedder for the realism estimate -- and it
attacks one assistant through its real channel. Both facts shape what a result means. Two runs
graded by different judges are not comparable, and the same model exposes a token distribution
through one serving path and not through another. An assistant that can act -- book, pay, send --
fires real side effects when attacked, and the search sends far more exchanges than the profiler.

The platform runs on an appliance where models are served by vLLM on the local GPU, and in the
cloud where they come from a hosted router. It attacks assistants on the Alquimia runtime, and it
has to be rehearsable offline without credentials.

## Decision Drivers

- Every model that took part in a run is named in its provenance, with where it was served.
- No model id, provider URL or credential is ever bound in code or read off the process
  environment.
- One code path reaches the assistant; nothing can reach it without governance.
- A run can be rehearsed end to end with recorded answers and no network.
- Adding a transport is a design decision with tests beside it, not a plugin dropped in.

## Considered Options

### Option A: Default models and an open connector registry — Rejected

Module constants name a default judge and embedder; any package registers a `kind` with a factory;
the client library reads its key from the environment when none is passed.

**Pros:** convenient; a run needs to declare little.

**Cons:** a default model is a measurement nobody can attribute; an ambient key measures with a
credential the spec never declared; a registry the runner has to remember to populate is empty in
exactly the process where it matters; two factories under one `kind` leave the manifest unable to
say which transport reached the assistant.

### Option B: Models by role from the spec, a closed set of target adapters, governance in the engine — Chosen

The run spec declares each model by role -- id, provider, endpoint, credential reference, pacing,
reasoning budget -- and a provider registry builds it; a spec that names no provider is refused,
and a hosted provider handed no credential is refused before the client exists. Two providers ship:
a hosted router for the cloud and an OpenAI-compatible builder for the appliance's own servers,
which requires an endpoint and never lets the client read the environment. The control judge
requires usable logprobs and is retried when a verdict truncates, never silently downgraded to
sampling. The target is reached through exactly two adapters -- the Alquimia runtime and a replay
of recorded answers -- selected by a closed switch on `ConnectorSpec.kind`. An adapter reports
every transport failure as a typed record inside the response and never raises; a refusal to answer
is an answer. The adapter is never used raw: the engine wraps it in a governed door that enforces
the capability gate, the budget and the rate limit before the first turn. The knowledge base is
read through a single reader identity, pulled by digest into a temporary directory and discarded.

**Pros:** provenance is complete by construction; credentials travel only by reference; the
assistant is reachable one way; offline rehearsal is the same code path as a live run.

**Cons:** every run has to declare its models; a new transport is a change to this package; the
provider libraries are optional extras the image has to install.

## Decision

Adopt Option B. Models are configuration declared by role in the run spec and built by registered
providers; the code names providers, never models, and a guard scans for the opposite. The target is
one of two adapters chosen by name, reports failures as typed records, and is only ever reached
through the engine's governed door. The knowledge base is consumed read-only under one reader
identity.

## Consequences

### Positive

- The manifest's components say which model played which role and where it was served.
- A run against the appliance's vLLM and a run against a hosted router differ only in the spec.
- A rate limit, a refused credential and an outage are distinguishable in the evidence, and the
  engine's policy reads the kind rather than a class name.
- The replay adapter makes the whole pipeline testable without a model or an assistant.

### Negative / Trade-offs

- A spec is verbose: judge, generator, embedder and attackers each carry a model declaration.
- An OpenAI-compatible server that authenticates nobody still receives a placeholder key, because
  the alternative is the client reading the environment.
- Only the Alquimia runtime is attackable; another assistant runtime is a new adapter and a new
  decision.

## Implementation Notes

- `redteam_judges.models`: `register`, `build_chat_model`, providers `openrouter` and
  `openai_compatible`; `ProviderUndeclared`, `UnknownProvider`, `CredentialUndeclared`,
  `EndpointUndeclared`; pacing attached as a rate limiter; `TEMPERATURE = 0`.
- `redteam_judges.grading.grader_for`: the one rule for building a grader, with `ServingPath` in
  the answer; `RetryingGrader` over `LogprobGrader`; `FakeGrader` for fixtures.
- `redteam_target.build_target`: a closed switch over `alquimia` and `replay`;
  `redteam_target.failures.classify` maps exceptions to `TransportFailure` by status *name*;
  `CapabilityGate.assert_may_attack` is the safe-mode gate.
- `redteam_knowledge.boltzmann_kb`: reader identity `alquimia/red-teaming-runner`; `pulled_brain`
  pulls by digest and discards.
- Guards: `test_no_hardcoded_models.py`, `test_no_ambient_credentials.py`,
  `test_no_status_literals.py`.
