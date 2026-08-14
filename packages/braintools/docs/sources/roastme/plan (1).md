# Implementation Plan: Roast Me — Profile-then-Exploit Adversarial Evaluation

**Branch**: `004-roastme-metric` | **Date**: 2026-08-06 | **Spec**: `specs/004-roastme-metric/spec.md`

## What changed since the version you reviewed

This file was substantially rewritten, so the diff is large. The changes, in one place:

- **Reversed**: an earlier draft argued for reusing the framework's statistical modes for the weakness
  map. They are no longer used at all — see "Why the framework's statistical modes are not used".
- **Reversed**: the Profiler had no target assistant and graded pre-collected responses. Both components
  now receive the target interface.
- **Resolved**: the open decision on which category searches ship. Both, with training behind its own
  extra.
- **Removed**: "Why the Profiler never receives a `TargetAssistant`", and the section re-litigating the
  extras decision.
- **Added**: the Testing Gate, which carries the one unchecked box in this document; "Why the query
  generator and the on-profile filter are separate interfaces"; "Why the enumeration engine ships but
  does not run by default"; "How optional dependencies fail"; the open decision below.
- **Grown**: interfaces from seven to ten, probe engines from two to four.

## What changed after approval

Three things were approved with open questions still in them. Closing them changed the design in one
place, which is why this is stated here rather than only in the sections below.

- **The three pluggable pieces ship** (spec FR-039). The earlier position — the estimator ships, the
  query generator and the filter do not — left the Exploiter unable to run out of the box, which meant
  the invention was going to happen anyway, in every user's code, untested. It ships as a tested class
  labelled a reference implementation instead, and the failure report records which implementations
  produced it.
- **Thresholds split three ways** (spec D17, FR-040) instead of all being required. `τ` and `η` remain
  the user's; `λ`, `n` and the shipped search's own knobs get defaults; `n = 1` is now rejected rather
  than allowed, because it silently disables the inconsistency penalty.
- **A threshold whose scale belongs to a substitutable component takes its default from that component**
  (spec D18, FR-041). An earlier draft of this change proposed that components declare their score
  *range* and that gaussia validate `κ` against it. That does not work: a `κ` calibrated for a `[0,1]`
  filter is inside a `[0,100]` filter's range too, so the check passes and the gate quietly admits
  everything. Recommending the threshold from the component catches exactly that case.
- **The policy-gradient search is now testable** (spec FR-033, SC-014), which removes the only unchecked
  gate box in this document. See "Why the policy-gradient search injects its policy and its optimiser".

## Summary

Translate the Roast Me methodology from `papers/2026-06-roastme/` into the SDK as a specification the
user implements against. Ten abstract interfaces land in `core/`; the Pydantic shapes land in
`schemas/roastme.py`; the Probe Library, the Profiler and the Exploiter land in `generators/roastme/` as
a generator subsystem that drives an injected target assistant and produces the Roast Dataset, which the
framework's existing pipeline then consumes (spec D15).

Base implementations ship for grading, for probe generation and for the Exploiter's three pluggable
pieces, each declared as a reference implementation rather than as the definition of its component
(spec D1, FR-039). The arithmetic gaussia owns — the violation score,
the weakness map with its standard errors, `S(c)`, the `κ` gate, the `δ` budget, refinement — is kept in
modules with no I/O so it is verifiable against hand-computed fixtures with no network and no GPU.

Nothing in this document is open. The three questions it previously left to the reviewer — which
pluggable pieces ship, and how the method's thresholds are supplied — are decided below and in spec D17
and D18.

## Technical Context

**Language/Version**: Python 3.11+, matching the existing stack.

**Primary Dependencies**: no new mandatory runtime deps. Two new extras:

```toml
roastme    = ["sentence-transformers>=5.0.0", "torch>=2.0.0", "networkx>=3.0"]
roastme-rl = ["gaussia[roastme]", "peft>=0.10.0", "accelerate>=0.25.0", "trl>=0.8.0"]
```

`roastme` covers inference: an embedder for the retrieval engine and the realism estimator, a graph
library for the graph engine. `roastme-rl` adds the training stack for the policy-gradient search. Both
stay **out** of the `metrics` aggregate and out of `all`, following the `privacy-*` precedent, so no
existing install grows. Per FR-037 the interfaces in `core/` import with no extra installed.

**Testing**: `uv run pytest`. Correctness rests on hand-computed fixtures with deterministic stubs for
every interface. No network, no GPU, no external artifacts in the default suite (SC-010).

**Project Type**: library extension, additive to `src/gaussia/`.

## Constitution Check

### SOLID Gate

- [x] **Single Responsibility**: `Profiler` drives the target, grades and aggregates. `ProbeLibrary`
  composes engines and merges duplicates. `Exploiter` composes a search, a query generator, a filter and
  an estimator. Each engine translates one retrieval mechanism. `searches/scoring.py` holds only
  arithmetic. `dataset.py` only converts at the output boundary. No class straddles two jobs.
- [x] **Open/Closed**: adding an engine, a grader, an estimator, a search, a query generator, a filter or
  a target adapter is a new file implementing the corresponding `core/` interface, with nothing else
  touched. **One exception, stated rather than hidden**: the transform set is closed by FR-025 to four
  members, so a fifth transformation requires editing `transforms.py` *and* relaxing that requirement.
  It is closed because `transform` is the one field whose value changes what a probe *means* — an
  unrecognised transformation would silently produce probes whose `doc` label nobody can trust. If that
  trade is wrong, FR-025 is where to change it.
- [x] **Liskov**: nothing subclasses a framework class, so there is no substitution surface to break.
  A target adapter that replays recorded responses is substitutable for one that calls a live assistant,
  which is what lets FR-014's credential-free path use the same code as a live run.
- [x] **Interface Segregation**: ten small interfaces instead of one god-object. A user writing a probe
  engine does not inherit grading, and a grader does not inherit knowledge-base access — which is what
  keeps invariant 2 structurally true rather than merely documented.
- [x] **Dependency Inversion**: every component depends on the `core/` abstractions and receives concrete
  implementations by construction. Nothing imports `graders.logprob` or a concrete engine.

### Pattern Gate

- [x] **No string-driven branching** — the one place it took work. The catalogue's `transform` field is a
  string the user writes, and it cannot be anything else: configuration is data. What the gate forbids is
  *branching* on it. Resolution: a `Transform` interface with four implementations and a registry that
  resolves the string **once**, during catalogue validation (FR-025). After that point behaviour is
  polymorphic and no `if transform ==` exists anywhere. The string is still carried on the hook's `how`
  field for auditing, which is a record rather than a dispatch.
- [x] **No conditional chains for behaviour selection**: engine selection is composition, not a cascade —
  every applicable engine contributes and their outputs merge (FR-022). Grader, search, query generator,
  filter and estimator selection is class identity at construction.
- [x] **Appropriate pattern identified**: Strategy for grader, engine, enumerator, verifier, transform,
  query generator, filter, estimator and search; Adapter for the target assistant and for the
  output-boundary conversion; Composite for `ProbeLibrary` over its engines; Registry only for resolving
  the four transforms.
- [x] **Composition over inheritance**: engines compose into the library; search, generator, filter,
  estimator and target compose into the exploiter; graders compose into the contract. The only
  inheritance anywhere is from the abstractions themselves.

### Simplicity Gate

- [x] **No speculative features**: the plan implements FR-001…FR-041 and nothing else. No plug-in
  discovery, no caching, no async fan-out, no retry policy beyond the sampling fallback FR-008 requires.
- [x] **No premature abstractions**: every interface has a real consumer in scope. A *category generator*
  is deliberately **not** an interface: the training-free search has none — it intersects a pool — so
  requiring one would force a fake implementation.
- [x] **Gaussia does not own a catalogue file format.** The spec asks it to *validate* a catalogue, not to
  read YAML. The user constructs the specs, or hands over data Pydantic validates.
- [x] **No over-engineered error handling**: a catalogue fails validation up front (FR-025), a principle
  with no grader fails at construction (FR-003), a failed exchange is recorded ungraded (FR-016).

### Testing Gate

- [x] Tests precede implementation, and every success criterion has a task that asserts it.
- [x] **`PolicyGradientSearch` is covered except for the weight update itself** (SC-014). An earlier draft
  left this box unchecked, on the argument that testing a training step on CPU asserts that the step runs
  rather than that the search searches. That is true and it answers the wrong question: the search is a
  loop that samples queries, gates them on `κ` and `δ`, scores them, turns the score into a reward and
  stops on a budget — and only the last step, applying the gradient, needs a GPU. Injecting the policy and
  the update step puts the other four under hand-computed coverage. What remains uncovered is one call
  into `trl`, third-party code this repo does not test anywhere else. The class stays marked
  `requires_gpu` for the end-to-end path, a marker the repo already defines.

### Pipeline Gate

- [x] **Roast Me sits upstream of the metric pipeline rather than inside it** (spec D15). It does not
  consume the dataset-loading contract, because there is no dataset to load. What enters the canonical
  flow is the output: the Roast Dataset, loaded the ordinary way for existing metrics to evaluate
  (FR-034). This is not a deviation — the framework's own generator base is a plain class rather than a
  metric, so producing datasets outside the metric pipeline is established.
- [x] **New schemas follow conventions**: all Pydantic, in `schemas/roastme.py`. The framework's `Batch`
  and `Dataset` appear only at the output boundary; `data-model.md` states what each of their required
  fields is filled with, so the conversion is buildable rather than assumed.
- [x] **Module boundaries respected**: `core/` gets abstractions only; `graders/` and
  `generators/roastme/` get concrete implementations; `schemas/` gets models with no business logic.
  Dependencies flow downward only, and `metrics/` is not touched.

## Architecture Decisions

### Why all ten interfaces live in `core/`

FR-037 requires them importable with the extra uninstalled, so a user can implement against them without
pulling an embedder or a graph library. `core/` carries no heavy imports, so placing them there satisfies
FR-037 structurally instead of by convention.

The existing organisation it follows, stated accurately: `core/` holds twelve abstractions today. Most are
one per file and re-exported from `core/__init__.py`, but two are not — `document_retriever.py` and
`contradiction_checker.py` hold several classes each and are **deliberately excluded** from the
re-export, because they require numpy. That file's own docstring says so. The rule is therefore
"abstractions with no heavy imports are re-exported; ones that would drag a dependency are imported
directly", and Roast Me's ten fall on the light side of it.

### Which pluggable pieces ship a working implementation

Which of the ten interfaces come with an implementation in the box, so a user can run without writing
code. The probe engines (D14, FR-022) and the logprob grader (FR-007) were settled at the spec gate. The
entity enumerator ships none, because enumerating a domain's entities is domain knowledge rather than a
technique.

**The Exploiter's three ship** (FR-039), and only one of them has the paper behind it:

| Piece | Provenance | Marked as |
|---|---|---|
| **Realism estimator** | the paper's own construction: expected cosine distance from a prior pool | reference implementation |
| **Query generator** | gaussia's; the paper names the role and gives no construction | reference implementation, stated as gaussia's own |
| **On-profile filter** | gaussia's; the paper leaves `f` abstract on purpose | reference implementation, stated as gaussia's own |

An earlier draft argued for shipping only the estimator, on the grounds that a shipped default for the
other two is an invention every user inherits. The flaw is that it does not avoid the invention, it only
moves it: with neither shipped the Exploiter refuses to run, so every user writes the same two
LLM-prompting classes by copying the example — the same invention, with no tests and no coverage behind
it. Level 3 is also the paper's headline contribution, and making it unrunnable out of the box is the
one outcome nothing in the spec asks for.

What keeps this honest rather than merely convenient: the docs say plainly that two of the three are
gaussia's construction and that substituting them changes what the search measures, and every
`FailureReport` records which implementation of each produced it. That last part is the one that matters
in practice — a mediocre shipped query generator would otherwise make the whole Exploiter look mediocre
with nothing pointing at the swappable part. It follows the recording convention already in the data
model: `Probe.engine` names the engine that produced a probe, `PrincipleGrade.grader` and
`PrincipleGrade.model` name the grader that produced a grade and the model it read it from.

### Why the query generator and the on-profile filter are separate interfaces

Both are things the paper names and an earlier draft folded into the search, which made two requirements
unimplementable.

Invariant 5 requires the query generator stay unmodified while the search is optimised. That is only
checkable if the two are distinct objects — if the search owns query generation internally, "it was not
modified" is an assertion about nothing.

The `κ` gate compares against a score of how on-profile and indirect a single query is. That is a
semantic judgement about one query, not arithmetic over values, so it cannot live in `scoring.py` with
the rest. Separating it lets `scoring.py` stay a pure-function module that takes the filter's output as a
number.

### Why a threshold's default lives on the component that defines its scale

`κ` and `δ` are the two thresholds gaussia compares against a number a *substitutable* component
produces. `τ` and `η` are not: they sit on rates gaussia computes itself, always in `[0,1]`.

That difference is the whole design. A filter returning `[0,1]` and one returning `[0,100]` are both
valid implementations of the same interface, and a `κ` of `0.6` gates sensibly against the first and
admits every query against the second. The failure is silent in the worst way: the run completes, the
report is populated, and the gate the paper relies on to keep blatant asks from counting was never
applied.

So the shipped filter and the shipped estimator each declare the threshold they recommend, `ExploiterConfig`
holds `κ` and `δ` as optional, and resolution happens once at Exploiter construction:

| Configured component | User supplied the threshold? | Result |
|---|---|---|
| ships with a recommendation | no | the component's value is used |
| ships with a recommendation | yes | the user's value wins, always |
| declares no recommendation | no | **construction fails**, naming the component and the parameter |
| declares no recommendation | yes | the user's value is used |

The rejected alternative, recorded because it looks correct: have components declare their score *range*
and validate the threshold against it. It fails on the exact case that motivates the mechanism — `0.6` is
inside `[0,100]`, so the check passes and nothing is caught. It also costs more code. Recommending the
threshold is both smaller and sound, because the recommendation is meaningless outside the scale it came
from and therefore cannot be inherited across a substitution.

This is the same shape as the `entity_kind` validation (FR-025): a component declares what gaussia cannot
infer, and gaussia refuses to run rather than producing a result that looks fine.

### Why the policy-gradient search injects its policy and its optimiser

The search is five steps in a loop: sample `k` queries from the policy, drop the ones failing `κ` or `δ`,
send the survivors to the target and grade them, turn the graded outcomes into a reward, apply the
update. Only the fifth needs a GPU.

Building the policy and the optimiser inside the class makes all five untestable together. Taking both as
constructor arguments makes the first four testable with a stub policy that returns fixed queries and
fixed log-probabilities, and a stub update step that records what it was asked to apply. The tests then
assert the things that can be silently wrong — that exactly `k` queries were requested, that the gates
dropped the right ones, that the reward matches hand computation, that the loop stopped on the budget.

The seam is not introduced for testing alone: the policy is a model the user supplies, which is the same
dependency-inversion the rest of the subsystem already applies to graders, engines and the target.

Two consequences worth stating, because both could be read as inconsistencies:

- **The two collaborator abstractions do not go in `core/`.** They stay in `policy_gradient.py`, so the
  interface count in the spec stays at ten. `core/` holds the specification a user implements against, and
  a user substituting the search wholesale never sees these — they are collaborators of one shipped
  implementation. This is the same line already drawn around a category *generator*, which the Simplicity
  Gate keeps out of the interface set for the same reason.
- **The RL stack is imported by `policy_update.py`, not by the loop.** Otherwise the CPU tests would need
  the `roastme-rl` extra installed to import the module they test, which would drag the training stack into
  the default suite and undo the point of the extra. The loop module imports nothing heavy; the single
  module that does is the one marked `requires_gpu`.

### Why the enumeration engine ships but does not run by default

It is the only engine that cannot work from a knowledge base alone: enumerating "every article that
exists" needs domain knowledge no general library has. So it takes an injected `EntityEnumerator`, which
gaussia specifies and ships none of.

Shipping the engine rather than omitting it keeps the strongest absence guarantee available to whoever
can afford to write that enumerator, while three engines still run out of the box. This is also what
gives `Document.structured` a consumer: it is the field the enumeration engine reads to know whether a
document's boundary can be enumerated at all.

### Why the framework's statistical modes are not used

`S(c) = Φ̂ₙ(c) − λ·seₙ(c)` needs a **standard error**, and the framework's dispersion utility returns a
mean absolute deviation. Those are different quantities, not differently-scaled ones.

Its rate estimator would have fit the weakness map, so the tempting design was to use the framework's
mode for `ω` and hand arithmetic for `S(c)`. That puts two statistical treatments inside one measurement,
where a reader cannot tell which number came from which. Roast Me computes its own rates and standard
errors, uniformly, in the module that also computes `S(c)`.

### Why there is no input-side `ProbeBatch`

With spec D15 there is no dataset on the way in, so there is nothing to subclass: the Profiler works on
`Probe` objects and the responses the target returns. A `Batch` subclass appears only on the **output**
side, where `data-model.md` specifies it and every field it fills.

One trap avoided: `Batch.weight` is the framework's own per-turn aggregation weight, unrelated to the
contract's principle weights `w_j`. Keeping principle weights on the contract, where FR-001 validates
them, keeps the two from ever being confused.

### Why the Profiler and the Exploiter both receive the target interface

The user implements one adapter for their transport and both components drive it. An assistant that only
exists as a page in a browser is still reachable: the user implements the interface, returns the response
as `TargetResponse`, and gaussia consumes nothing but that. Pushing the exchange onto the user instead
would mean every user writing their own probe-sending loop, which is the part gaussia is better placed to
own.

What it buys rather than costs: FR-014 asks that grading a recorded response set need no credentials.
That is now an *implementation* of the same interface — one returning recorded responses — rather than a
mode the Profiler can be in or out of. One code path serves both, and the credential-free case stops
being a special case that could rot.

The `failed` flag lives on the response model for the same reason: whoever writes the adapter is the only
party that can recognise a transport failure, and FR-016 obliges the Profiler to honour it.

### Why a new `Document` schema

The framework's corpus-connector document is a two-field dataclass with no identifier and no enumerability
flag, and lives in a different module with a different modelling style. `data-model.md` carries the
comparison.

### Why a new `graders/` module

The repo groups concrete implementations by the kind of thing they are, one directory per family:
`guardians/`, `rerankers/`, `embedders/`, `detectors/`. `graders/` follows that. To be explicit, since the
wording invited the opposite reading: **nothing selects a grader by a string.** `Grader` is an abstract
base class, users extend it freely, and the shipped logprob grader is one subclass among however many a
user writes.

### Why the exploiter's arithmetic is a separate module

`searches/scoring.py` holds `S(c)`, the `κ` comparison, the `δ` comparison, refinement and the weakness
map's rates and standard errors as functions over values, with no I/O and no model. SC-007 then verifies
the criterion that decides whether a category passes without constructing a search, a target or an
estimator. It is also what both searches share: the decision rule is one covered module, so switching
search procedure cannot change what counts as a failing category.

### How optional dependencies fail

The constitution forbids `try/except ImportError` and dynamic imports, so a missing extra must surface as
a plain `ImportError` at the import site of the module that needs it. Concretely:

- The framework already defines `LogprobsNotSupportedError` and `LogprobsExtractionError` for a provider
  that returns no usable logprobs. The base grader reuses them rather than inventing its own, which is why
  `core/exceptions.py` is not in the Modified Files table.
- `core/` and `schemas/roastme.py` import nothing heavy, so the interfaces and the models always import.
- `generators/roastme/__init__.py` re-exports `ProbeLibrary`, `Profiler` and `Exploiter` — none of which
  imports an engine. `probes/__init__.py` **must not** re-export `retrieval.py`, `graph.py` or `grag.py`;
  those are imported directly by the user, the way the framework already treats its numpy-dependent
  abstractions. Without that rule, `from gaussia.generators.roastme import Profiler` would pull an
  embedder and break FR-037 one level below where the plan guards against it.
- SC-011's task asserts this for the subsystem, not only for `core/`.

### Verification strategy

Deterministic stubs for all ten interfaces, and probe fixtures whose expected `v`, rates and standard
errors are computed by hand from the paper's equations (SC-001, SC-002). No fixture depends on a provider,
a network, a GPU or an external repository (SC-010). Three behaviours get dedicated doubles because they
are easy to get silently wrong: a target that returns recorded responses, a target that reports a failed
exchange (SC-008), and a grader whose provider exposes no usable logprobs (SC-009).

## New Files

| File | Purpose | Pattern |
|---|---|---|
| `src/gaussia/core/grader.py` | `Grader` (FR-005) | Strategy |
| `src/gaussia/core/probe_engine.py` | `ProbeEngine`, including the entity kinds it declares it handles (FR-019, FR-021, FR-025) | Strategy |
| `src/gaussia/core/entity_enumerator.py` | `EntityEnumerator`: the entities of a kind that exist in the base. Ships no implementation | Strategy |
| `src/gaussia/core/hook_verifier.py` | `HookVerifier` | Strategy |
| `src/gaussia/core/transform.py` | `Transform` | Strategy |
| `src/gaussia/core/target_assistant.py` | `TargetAssistant` (FR-017, FR-018) | Adapter |
| `src/gaussia/core/query_generator.py` | `QueryGenerator`: category → concrete queries (FR-033) | Strategy |
| `src/gaussia/core/on_profile_filter.py` | `OnProfileFilter`: how on-profile one query is, for the `κ` gate, plus the `κ` it recommends on its own scale (FR-030, FR-041) | Strategy |
| `src/gaussia/core/realism_estimator.py` | `RealismEstimator`, plus the `δ` it recommends (FR-031, FR-041) | Strategy |
| `src/gaussia/core/category_search.py` | `CategorySearch` (FR-033) | Strategy |
| `src/gaussia/schemas/roastme.py` | Every model in `data-model.md`, including `TargetResponse` and the two config models | Models |
| `src/gaussia/graders/__init__.py` | Re-exports the shipped grader | Module facade |
| `src/gaussia/graders/logprob.py` | `LogprobGrader` (FR-007, FR-008) | Adapter |
| `src/gaussia/generators/roastme/__init__.py` | Re-exports `ProbeLibrary`, `Profiler`, `Exploiter` — no engine imports | Module facade |
| `src/gaussia/generators/roastme/profiler.py` | Drives the target over a probe set, grades, aggregates (FR-010…FR-016) | Composition |
| `src/gaussia/generators/roastme/exploiter.py` | Composes search, query generator, filter, estimator and target; emits the dataset and the report (FR-034…FR-036) | Composition |
| `src/gaussia/generators/roastme/dataset.py` | The output-boundary conversion (FR-034) | Adapter |
| `src/gaussia/generators/roastme/probes/__init__.py` | Module init — **no engine re-exports** | Module facade |
| `src/gaussia/generators/roastme/probes/library.py` | `ProbeLibrary` (FR-020, FR-022, FR-024) | Composite |
| `src/gaussia/generators/roastme/probes/retrieval.py` | Retrieval engine; records that its absence labels are unreliable (FR-023) | Strategy |
| `src/gaussia/generators/roastme/probes/graph.py` | Graph engine; confirms absence from the complete graph | Strategy |
| `src/gaussia/generators/roastme/probes/grag.py` | Multi-hop engine; false premises spanning several entities | Strategy |
| `src/gaussia/generators/roastme/probes/enumeration.py` | Enumeration engine; opt-in, requires an injected `EntityEnumerator` (D14) | Strategy |
| `src/gaussia/generators/roastme/probes/particularisation.py` | The generation flow the four engines share, which they specialise in one step each (FR-021) | Template Method |
| `src/gaussia/generators/roastme/probes/transforms.py` | The four `Transform` implementations and the registry | Strategy + Registry |
| `src/gaussia/generators/roastme/probes/catalogue.py` | Catalogue validation, including `entity_kind` against the engines' declared kinds (FR-025, FR-026, SC-005) | Validator |
| `src/gaussia/generators/roastme/searches/__init__.py` | Module init | Module facade |
| `src/gaussia/generators/roastme/searches/scoring.py` | `S(c)`, the gates, refinement, rates and standard errors (FR-012, FR-029…FR-032) | Pure functions |
| `src/gaussia/generators/roastme/searches/evaluation.py` | Evaluating one proposed category: the `δ` check before any target call, the `κ` gate, grading, `S(c)`. Shared by both searches, which is what stops the procedure deciding what counts as a failure (FR-030, FR-031, FR-016) | Template Method |
| `src/gaussia/generators/roastme/searches/attribute_iteration.py` | The training-free search; the default | Strategy |
| `src/gaussia/generators/roastme/searches/realism.py` | Base realism estimator: expected cosine distance from a prior pool, using an injected embedder — the instantiation the paper gives for `δ` — and the `δ` it recommends (FR-039, FR-041) | Adapter |
| `src/gaussia/generators/roastme/searches/query_generation.py` | Base query generator: a category's attributes to concrete queries through the user's model. Gaussia's own construction, declared as such (FR-039) | Adapter |
| `src/gaussia/generators/roastme/searches/on_profile.py` | Base on-profile filter, and the `κ` it recommends. Gaussia's own construction, declared as such (FR-039, FR-041) | Adapter |
| `src/gaussia/generators/roastme/searches/thresholds.py` | Threshold resolution: component recommendation, user override, refusal (FR-041, SC-012) | Pure functions |
| `src/gaussia/generators/roastme/searches/policy_gradient.py` | The policy-gradient loop, and the two collaborator abstractions it samples from and applies through. Imports nothing heavy, so it runs in the default suite (FR-033, SC-014) | Strategy |
| `src/gaussia/generators/roastme/searches/policy_update.py` | The training-backed update step behind `roastme-rl`: the only module here that imports the RL stack, and the only one marked `requires_gpu` | Adapter |
| `tests/generators/roastme/test_profiler.py` | Grade retention (FR-004), control exclusion by empty plugin including the pair over one documented entity (SC-003), ungraded outcomes (SC-008) | Pytest |
| `tests/generators/roastme/test_dataset.py` | The conversion and its field fills; an existing metric consumes the result unchanged (SC-006) | Pytest |
| `tests/generators/roastme/test_catalogue.py` | Every rejection path (SC-005) | Pytest |
| `tests/generators/roastme/test_library.py` | Composition, duplicate merging, absence reliability (SC-004), the enumeration engine refusing to run without an enumerator | Pytest |
| `tests/generators/roastme/test_scoring.py` | `v`, rates, standard errors, `S(c)`, the gates, refinement (SC-001, SC-002, SC-007) | Pytest |
| `tests/generators/roastme/test_exploiter.py` | The report ranked by `S(c)` with the queries at or above `τ` surfaced (FR-035), an auditable evaluation record (FR-036), and the implementations recorded on the report (FR-039) | Pytest |
| `tests/generators/roastme/test_thresholds.py` | The four resolution paths, and `n = 1` rejected with the fixture showing the penalty vanishing (SC-012, SC-013) | Pytest |
| `tests/generators/roastme/test_policy_gradient.py` | Sampling, gating, reward and stopping with a stub policy and a stub update step, on CPU (SC-014) | Pytest |
| `tests/graders/test_logprob.py` | Last-token location, discard on unparsed answer, fallback marking (SC-009) | Pytest |
| `tests/generators/roastme/test_contracts.py` | Every double satisfies its `core/` interface, so a third-party implementation has an executable definition of conformance (FR-019) | Pytest |
| `tests/generators/roastme/test_expected_fixtures.py` | Every hand-computed literal re-derived from its closed form, so a fixture cannot drift into a snapshot of whatever the code produces (SC-001, SC-002) | Pytest |
| `tests/generators/roastme/test_import_isolation.py` | Each interface and the subsystem import with the extra's dependencies blocked (FR-037, SC-011) | Pytest |
| `tests/generators/roastme/test_hermeticity.py` | The default suite opens no socket, reads no credential and needs no GPU (SC-010) | Pytest |
| `tests/fixtures/roastme/` | Deterministic doubles for all ten interfaces plus hand-computed probe fixtures | Test doubles |
| `docs/advanced/roastme.mdx` | The subsystem page, alongside `generators` and `prompt-optimizer` (FR-038) | Docs |
| `examples/roastme/catalogue/` | Schema examples, **not** a domain catalogue (FR-027) | Example |
| `examples/roastme/jupyter/` | Runnable notebook: contract, catalogue, profile against a recorded target | Example |

Package `__init__.py` files for the new test directories are covered in `tasks.md`; every test directory
in this repo has one.

## Modified Files

| File | Change | Justification |
|---|---|---|
| `src/gaussia/core/__init__.py` | Import the ten abstractions and extend `__all__` | They carry no heavy imports, so they belong on the re-exported side of that file's own rule |
| `src/gaussia/schemas/__init__.py` | Docstring pointer only, no eager import | The file's docstring establishes that feature-specific schemas are imported from their module |
| `pyproject.toml` | Add the `roastme` and `roastme-rl` extras with the pins above | FR-037. Out of the `metrics` and `all` aggregates |
| `docs/docs.json` | Register `advanced/roastme` in the Advanced nav | An unlisted page is not published |
| `docs/docs-sync.json` | Register `sdks/python/advanced/roastme` in the Advanced group | A second navigation registry, the one that publishes to the docs site. Listing only the first would leave the page unpublished |

Five rows. `src/gaussia/metrics/__init__.py` is **not** among them, because nothing here is a metric: the
public surface is `from gaussia.generators.roastme import ProbeLibrary, Profiler, Exploiter`.

Three files deliberately **not** modified, worth stating because two are where this feature would most
plausibly have leaked:

- `src/gaussia/llm/judge.py` — FR-009 and spec D4. Roast Me grades behind its own interface. The shared
  judge reads the first generated token, which is wrong for a reasoning model, but fixing it there would
  change behaviour for `role_adherence`, which depends on it. That is a separate decision with its own
  blast radius. Note also what the shared judge does *not* do: it raises `LogprobsNotSupportedError` rather than
  falling back. The fallback that exists lives in `role_adherence`'s scoring strategy and goes to
  structured output, where FR-008 requires sampling — so the violation-rate denominator stays
  provider-independent.
- `src/gaussia/generators/__init__.py` eagerly imports concrete classes. Registering the engines there
  would make `import gaussia.generators` require an embedder, breaking FR-037.
- `CHANGELOG.md` is generated by python-semantic-release and must not be hand-edited.

## Complexity Tracking

No gate box is left unchecked and no decision is left open. Two additions to the surface are worth
naming, both bought deliberately:

- `OnProfileFilter` and `RealismEstimator` each carry a recommended threshold beyond their scoring method.
  One attribute apiece, in exchange for making a silent gate failure impossible (FR-041).
- `PolicyGradientSearch` takes two collaborators it could have constructed itself. That is what moves its
  loop from uncovered to covered (SC-014), and it matches the injection the rest of the subsystem uses.
