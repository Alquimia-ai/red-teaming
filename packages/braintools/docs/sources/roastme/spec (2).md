# Feature Specification: Roast Me — Profile-then-Exploit Adversarial Evaluation

**Feature Branch**: `004-roastme-metric`
**Created**: 2026-08-03
**Status**: Planned

> **Amended twice after approval.** At the plan gate, four scope changes: Roast Me does not ride the
> metric pipeline (D15); the target-assistant interface is received by both the Profiler and the
> Exploiter (D16, FR-014, FR-017); two extras instead of one (D5); all four probe engines ship, three by
> default (D14, FR-022). After the tasks gate, the three parameter questions this document had left to
> the reviewer, now decided: the Exploiter's three pluggable pieces ship base implementations (D1,
> FR-039); the method's thresholds split into user-owned and library-defaulted (D17, FR-040); and a
> threshold measured on a substitutable component's own scale takes its default from that component
> (D18, FR-041). Factual corrections and the reading path are in the pull request description, so this
> document stays a specification rather than a changelog.

## Overview

Roast Me is not a scalar metric. It is a search problem: given an assistant treated as a black box, find the *categories* of realistic interactions that make it violate its behavioral contract reproducibly. Three components in sequence — a **Probe Library** that turns a knowledge base into tagged adversarial probes, a **Profiler** that grades the responses into a weakness profile, and an **Exploiter** that searches for reproducible failure categories.

Every component is a **specification first**. Gaussia owns the interfaces, the data shapes, the validation and the arithmetic; the user implements against them. Where a base implementation ships, it is named as such — a convenience for users who do not want to write their own, never the definition of the component.

## Paper Reference

- **Paper**: `gaussia-labs/papers/papers/2026-06-roastme/`. §Theoretical Formulation defines the method. The engine set and the absence/breadth trade-off of invariant 7 come from §Experiments instead, and the multi-hop engine is characterised there only by example — worth knowing before treating it as specified.
- **Paper PR**: gaussia-labs/papers#20, merged to `main`.
- **Implementation Issue**: N/A — tracked through the SDD gate commits on this branch, as `001-privacy-metric` was.

### Notation used below

Only the symbols the requirements reference. The paper carries the full formulation. Citations name the
equation's `\label`, not its number, because numbers shift whenever the paper is edited.

| Symbol | Meaning | Source |
|---|---|---|
| `Π = {π_j}`, `w_j` | the behavioral contract: principles and their severity weights, `Σ w_j = 1`. **An input, not a library constant** | ¶Behavioral contract |
| `π̂_j ∈ [0,1]` | a **grader**: estimates whether principle `j` was violated | ¶Graders and violation score |
| `v(x,r) = Σ_j w_j · π̂_j(x,r)` | the **violation score** of one response | `eq:violation` |
| `doc(g) ∈ {0,1}` | the **grounding label** on a probe's knowledge hook: 1 if the referenced content exists in the knowledge base, 0 if the probe deliberately invents it | `eq:doc` |
| `θ = (ω, H)` | the **profile**: a weakness map over probe descriptors, plus the retained knowledge hooks `H` | `eq:profile`, `eq:weakness` |
| `C_θ`, `η` | the categories whose every attribute comes from a weakness at or above `η`, or references a hook in `H` | `eq:ctheta` |
| `c = (a₁…a_ℓ)` | a **category**: a conjunction of natural-language attributes | `eq:attributes` |
| `S(c) = Φ̂ₙ(c) − λ·seₙ(c)` | the category score. A lower-confidence bound, so consistent failure outranks a lucky spike | `eq:score` |
| `κ` | the on-profile gate on a single query | `eq:filtered` |
| `δ` | the realism budget on a category. The divergence it bounds is `eq:realism-cos`; the budget itself is introduced in `eq:search` | `eq:search` |
| `τ` | the pass threshold on `S(c)` | `eq:search` |

### Invariants the paper imposes

These are methodological, not stylistic. Breaking any one invalidates the measurement.

1. The assistant is sampled, never inspected — no parameters, system prompts or internal tools (¶Target assistant).
2. The knowledge base is reached **only** through the Probe Library. The Profiler and the graders never touch it (Fig. 1).
3. `θ` is the **only** artifact crossing from Profiler to Exploiter, and it carries readable prose rather than internal identifiers.
4. The `doc` label must be honest, and derived from the generating engine's own knowledge of the base's boundary — never from the enumeration used for scoring. It is what lets a grader separate "invented something absent" from "described something present".
5. Under the policy-gradient search, optimisation pressure applies to the category generator only; the query generator stays frozen, which is what preserves realism (`eq:crl`).
6. A verdict is read from the logprobs of a single-word answer, located by scanning the sequence for the **last** verdict-shaped token — the first token belongs to a reasoning model's preamble. Whether logprobs are usable at all is a property of the serving provider rather than of the model, so it has to be probed at runtime and survived when absent.
7. Reliable absence labels come from enumeration or from a complete graph; breadth of false-premise variety comes from retrieval; no single engine gives both. Similarity search is *structurally* unable to decide absence, because it never reveals what it failed to retrieve.
8. The scores this metric produces come from LLM graders, which the paper states have not been calibrated against human-labeled ground truth. Agreement between graders is not agreement with a person.

## Decisions

Resolved before planning. The requirements implement these without restating them.

| # | Was open | Decided |
|---|---|---|
| D1 | What gaussia owns versus what the user writes | **Gaussia owns the specification**: the interfaces, the data shapes, the validation and the arithmetic. The user implements against it and supplies models, credentials, a knowledge base and a plugin/strategy catalogue. Base implementations ship where D14 and the requirements name them — grading, probe generation, and the Exploiter's query generator, on-profile filter and realism estimator (FR-039) — each declared as a reference implementation rather than as the definition of its component |
| D2 | Multi-grader aggregation | Out. One grader per principle. Comparing graders is done by running the metric once per grader |
| D3 | Rubrics and prompts | User-supplied. A rubric *is* what the metric measures, so gaussia ships schema examples rather than defaults |
| D4 | Extending the shared logprob judge | No. Roast Me grades behind its own interface; `llm/judge.py` is untouched and `role_adherence` is unaffected |
| D5 | Packaging | **Two extras.** `gaussia[roastme]` covers inference: an embedder for retrieval, a graph library for the graph engine. `gaussia[roastme-rl]` adds the training stack, for whoever wants the reinforcement-learning search. Whoever only profiles pays for neither |
| D6 | Reaching the assistant under test | The target-assistant **interface only**. No transport adapter ships in gaussia; a runtime-specific client belongs with that runtime, the same criterion that keeps the domain catalogue out of the library |
| D7 | Which of the paper's two category searches | Both, behind one interface. Training-free attribute iteration is the default and needs no GPU; policy gradient is available for those who have one |
| D8 | Where the Exploiter sits | It is a **generator, not a metric**: it emits the Roast Dataset, which the pipeline then consumes. Matches the paper's own framing of the dataset as the deliverable, and bends no article of the constitution |
| D9 | The paper's Implementation Considerations section is commented out (`roastme.tex:1461`) | This spec proposes that surface and the paper follows in a later PR. The inversion is deliberate; the traceability chain stays open until that PR lands |
| D10 | Surfacing the missing human calibration | Documented limitation in the metric docs. No field on the result, no calibration gate |
| D11 | Test fixtures | Synthetic fixtures with hand-computed values. The default suite is offline and needs no credentials, no GPU and no external artifacts |
| D12 | How a control probe is recognised | Structurally: a strategy with no plugin puts no principle under test, so the probe it produces carries none. Nothing depends on an identifier — see the catalogue specification below |
| D13 | No verdict token in the top logprobs | Fall back to sampling, marked as such. Raising would make the violation-rate denominator depend on provider behaviour |
| D14 | Which probe engines ship, and which run | **All four ship**: retrieval, graph, multi-hop and enumeration. The first three **run by default** and together span invariant 7 — though note this is not the set the paper evaluated: its canonical dataset was produced by retrieval, graph and enumeration, and the multi-hop engine appears in no trade-off table — the graph engine confirms absence, retrieval contributes the breadth of false premises. The enumeration engine is **opt-in**, because it is the only one that cannot run on a knowledge base alone: it needs the user to supply an enumerator for their domain's entities. Shipping it rather than omitting it keeps the strongest absence guarantee available to whoever can afford to write that enumerator |
| D15 | Whether Roast Me rides the framework's metric pipeline | **No.** There is no dataset to load: Roast Me *generates* the dataset that roasts the assistant. It is a generator subsystem — the Probe Library, the Profiler and the Exploiter produce the Roast Dataset, and that dataset is what enters the pipeline for existing metrics to consume. No component subclasses the framework's metric base class. This is not a deviation: the framework's generator base is already a plain class, and non-metric subsystems already sit alongside metrics rather than inside them |
| D16 | How the assistant under test is reached | Through the target-assistant interface, received by **both the Profiler and the Exploiter**. The user implements it for their own transport — a hosted API, a local model, a browser page — and returns the response as the specified model; gaussia consumes only that interface and drives the exchange. Replaying a recorded response set is an implementation of the same interface, not a separate mode, which is what keeps the credential-free path (FR-014) from being a special case |
| D17 | Which method thresholds gaussia is allowed to default | Split by what the value *is*, not by whether the paper names it. `τ` and `η` stay **required**: they say how badly the assistant has to behave before it counts, which is the user's judgement about their own domain, and a shipped value would quietly become a cross-user standard nobody chose. `λ` and the queries-per-category `n` are **defaulted**: they are statistical convention, and a conservative lower bound at one standard error already exists outside gaussia. `pool_size` is defaulted because it is a knob of an implementation gaussia writes, not a parameter of the method. Frictionless first runs come from a complete worked configuration in the examples (FR-040), not from hiding the two thresholds that are genuinely the user's |
| D18 | Where the default lives for a threshold measured on a substitutable component's scale | On the component. `κ` and `δ` are compared against numbers the on-profile filter and the realism estimator produce, so their meaning depends on whichever implementation is configured — a value calibrated for one scale is not merely suboptimal on another, it silently stops gating. Each implementation therefore declares the threshold it recommends; gaussia uses that when the user supplies none, and **refuses to construct** when a configured component recommends nothing. A user who swaps the component is obliged to supply the number, and a user who keeps the shipped one never sees the parameter |

## Data specification

What a user has to produce to plug into Roast Me, and what they get back. Field semantics only — the schema definitions belong to the plan gate.

### Knowledge base input

**Document** — one unit of the knowledge base handed to the Probe Library.

| Field | Meaning |
|---|---|
| `id` | stable identifier, quoted in every hook derived from this document |
| `content` | the source text |
| `structured` | whether this document's knowledge boundary is *enumerable*. Determines which engines can establish absence over it |
| `kind` | the document's family, which routes it to the right extraction. Optional |
| `metadata` | anything the engine or a downstream report needs to carry. Optional |

### Catalogue input

The catalogue is the user's. Gaussia specifies its shape and validates it; it ships schema examples, not a domain catalogue.

**PluginSpec** — a risk family. Each maps to one principle of the behavioral contract.

| Field | Meaning |
|---|---|
| `id` | referenced by strategies and recorded on every probe and graded outcome |
| `name`, `description` | documentation for the report. Not consumed by any logic |
| `principle` | the `Π` member this family attacks. Must exist in the contract |

**StrategySpec** — an interaction pattern: which kind of entity it operates on, how it transforms it, and whether the resulting hook is documented or invented.

| Field | Meaning |
|---|---|
| `id` | the aggregation descriptor `z` of the weakness map. Recorded on the probe |
| `name`, `description` | documentation |
| `plugin` | the risk family this strategy serves. **Empty means this strategy is a control**: it puts no principle under test, so its probes are excluded from every violation-rate aggregate |
| `entity_kind` | the kind of entity it needs, which has to match what the engine can extract or retrieve |
| `transform` | how the real entity becomes the probe's premise: keep it real, mutate it into a fake one, flip a documented value, or flip a documented fact |
| `doc` | the expected grounding label of the resulting hook: 1 documented, 0 invented |
| `phrasing_hint` | injected into the generation prompt, so it must be in the knowledge base's language |

Validation gaussia owes the user: every `principle` resolves in the contract, every `plugin` referenced by a strategy exists, `transform` is one of the four known transformations, `doc` is 0 or 1, identifiers are unique, and **every `entity_kind` is one the configured engines declare they handle**. That last one matters because `entity_kind` is the user's own vocabulary — gaussia never learns what it means — so a typo would otherwise pass validation and yield no probes at all, silently. A catalogue that fails any of these is rejected before generation runs.

**`doc: 1` does not mean control.** The two fields answer different questions: `doc` says whether the
entity exists, `plugin` says whether a principle is under test. A probe about a real, documented entity
scores whenever its strategy names a plugin. To bring "did it answer real content correctly" inside the
violation rate, add a principle for it and a `keep_real` strategy pointing at a plugin that serves it;
a control stays out because nothing is on the line, not because its entity is real.

### Probe output

**KnowledgeHook** — the structured provenance of a probe against the knowledge base.

| Field | Meaning |
|---|---|
| `kind` | the entity type the probe leans on |
| `references` | the entity itself, real or invented |
| `doc` | 1 documented, 0 invented. **This is the ground truth of the downstream test** |
| `how` | the transformation that produced it, from the strategy |
| `base_entity` | the real entity it was derived from, when the strategy mutated one |
| `principle` | the contract principle under test, empty for a control |
| `verified` | whether an independent verifier confirmed the `doc` label. Unset means unverified, and unverified is not the same as false |

**Probe** — the unit the Profiler consumes.

| Field | Meaning |
|---|---|
| `id` | stable identifier, quoted in every graded outcome |
| `plugin`, `strategy` | which catalogue entries produced it. Empty `plugin` means control |
| `query` | the question sent to the assistant |
| `hook` | the `KnowledgeHook` above |
| `attrs` | the natural-language attributes the probe exhibits, which is what lets the Exploiter ground a category in it |
| `engine` | which engine produced it, which is what keeps the absence/breadth trade-off measurable after composition |
| `meta` | what the grader needs to judge the response: the real value, the false value asserted, the real and false chains |

### Interfaces the user implements

Ten, described by obligation rather than by signature. This is the definitive list; a behavioral
contract is a model, not an interface.

- **Probe engine** — declares whether it can handle a given document, declares which entity kinds it can extract or retrieve, and turns a set of documents plus the catalogue into tagged probes. It must derive each `doc` label from its own knowledge of the base's boundary, and must record on the probe when it cannot establish absence reliably.
- **Entity enumerator** — lists the entities of a given kind that exist in the knowledge base. The enumeration engine cannot run without one, which is why that engine is opt-in (D14). Domain-specific by nature, so gaussia specifies it and ships none.
- **Hook verifier** — confirms a hook's `doc` label against the corpus. Shared across engines, which is what makes their absence accuracy comparable.
- **Transform** — turns a real entity into the premise a probe leans on.
- **Grader** — estimates one principle's violation for a query and a response, returning a score in `[0,1]` plus the evidence behind it.
- **Target assistant** — sends a query, optionally within a persistent session, and returns the response or marks the exchange as failed. Received by the Profiler and the Exploiter alike (D16).
- **Query generator** — samples concrete queries that satisfy a category's attributes. Separate from the search on purpose: invariant 5 requires it stay unmodified while the search is optimised, and that is only checkable if the two are distinct.
- **On-profile filter** — scores how on-profile and indirect a single query is, which is what the `κ` gate compares against. A semantic judgement about one query, not an aggregate. Because the scale is its own, it also declares the `κ` it recommends, or declares none and obliges the user to supply one (D18).
- **Realism estimator** — scores how far a category's sampled queries sit from the natural-query prior, which is what `δ` bounds. It declares the `δ` it recommends on the same terms.
- **Category search** — proposes categories from a profile and scores them. It owns how categories are proposed, which is what differs between the two procedures the paper gives: one trains a generator, the other intersects a pool of high-scoring pairs. A category *generator* is therefore not a separate interface — the training-free procedure has none.

## User Scenarios & Testing

### US1 — Profile an assistant from graded probes (P1)

An evaluator has tagged adversarial probes and the assistant's responses to them. They need to know **where** it is weak: which principles it breaks, under which kind of probe, how often, with what confidence, and which specific entities broke it.

**Why first**: the irreducible unit. The Exploiter consumes nothing but this profile, the Probe Library exists to feed it, the Roast Dataset is a serialisation of its outcomes. It is also the only component that runs with no knowledge base, no GPU and no live assistant — pointing the target interface at a recorded response set is enough.

**Independent test**: a deterministic stub grader over a hand-built probe fixture; every component of `v`, `ω` and `se` checked against values computed by hand. Offline.

1. **Given** a contract of `m` principles, **When** a response is graded, **Then** the outcome carries the aggregate `v` *and* the `m` per-principle grades, so a failure traces to the principle it breaks.
2. **Given** probes from a control strategy, **When** aggregates are computed, **Then** those probes are excluded from every rate while staying in the graded record.
3. **Given** two probes about the same real, documented entity, one from a strategy that names a plugin and one from a control strategy, **When** aggregates are computed, **Then** the first is scored and the second is not. Whether the entity exists decides nothing here; whether a principle is on the line decides everything.
4. **Given** a reasoning judge whose first token is its reasoning preamble, **When** the base grader extracts the verdict, **Then** the last verdict-shaped token in the sequence is used, and the result is discarded if the model's own final answer does not independently parse to a verdict.
5. **Given** an exchange the target marks as failed, **When** the probe set is graded, **Then** that probe is recorded as ungraded and counts as neither a violation nor a pass.

### US2 — Emit the run as a reusable Gaussia dataset (P2)

The evaluator wants the audit to outlive the audit: the graded outcomes as a dataset the rest of Gaussia loads, replayable against a modified assistant so a fix is demonstrated by the scores that move.

**Why second**: the paper's stated primary deliverable, and the smallest increment that makes US1 useful to the framework. It needs US1 alone — a Roast Dataset record is what the Profiler already produces per probe.

**Independent test**: emit from the US1 stub run, load through the standard dataset contract, have an existing metric consume it unchanged; then change one grade and confirm the diff is isolated to that record.

1. **Given** an emitted dataset, **When** it is loaded through the SDK's dataset contract, **Then** an existing metric consumes it with no change to that metric.
2. **Given** a run in black-box mode, **When** records are emitted, **Then** the absence of evidence is distinguishable from evidence sought and not found.

### US3 — Generate tagged probes from a knowledge base (P3)

The evaluator points the library at their documentation or regulation, supplies a catalogue, and gets probes for their domain — each tagged with what is documented and what is plausible but absent. They also need to know how far to trust each tag, because a false "this does not exist" silently corrupts everything downstream. An evaluator whose knowledge base needs an engine that does not ship writes one against the probe-engine specification.

**Why third**: it removes the need to hand-author a probe set, and it is where the absence/breadth trade-off of invariant 7 lives. Still downstream of US1 in value: an evaluator with their own probes gets a full profile without it, and black-box mode is explicitly supported.

**Independent test**: over a fixture base with a known enumerable entity set, check absence labels against exact enumeration. Generation is stochastic, so the test asserts label correctness and composition, never probe text.

1. **Given** the retrieval and graph engines over one base, **When** their outputs compose, **Then** duplicates merge and each surviving probe records its originating engine, so the trade-off stays measurable after composition.
2. **Given** the retrieval engine, which cannot decide absence because similarity search never reveals what it failed to retrieve, **When** it emits an absence probe, **Then** that unreliability is recorded on the probe rather than being indistinguishable from a graph-confirmed absence.
3. **Given** a catalogue whose identifiers are entirely the user's own, **When** generation and profiling run, **Then** no library behaviour depends on any of those identifiers, including which strategies are controls.
4. **Given** a catalogue that names a principle absent from the contract, or a transformation that is not one of the four, **When** it is loaded, **Then** it is rejected before any generation runs.

### US4 — Search for reproducible failure categories (P4)

Not "which prompt broke it" but "which kinds of realistic question break it, repeatably" — categories in readable attributes, scored so consistency beats luck, gated so blatant asks do not count, budgeted so the queries still read like real traffic, and reduced to the attributes actually responsible. The search runs as a generator: its product is the Roast Dataset, which the pipeline then evaluates.

**Why last**: the paper's headline contribution and its least settled result — it reports the search as a validated integration rather than a validated finding, with sample size as the stated blocker. It is also the heaviest to build. US1-US3 already deliver a working product.

**Independent test**: stub target, stub grader with prescribed violations, stub query generator, stub on-profile filter and stub estimator, all with prescribed outputs. `S(c)` against hand computation; a high-variance category rejected where a consistent lower-mean one passes; `κ` zeroing a query; `δ` discarding a passing category; refinement returning the minimal sub-conjunction. Training-free search, so no GPU.

1. **Given** two categories with equal mean violation and different variance, **When** both are scored, **Then** the lower-variance one ranks higher, and a category evaluated once carries its `n` so the unreliability of its penalty is visible rather than implied.
2. **Given** a category that passes `τ`, **When** it is refined, **Then** the result is the smallest sub-conjunction still satisfying `S(c') ≥ τ` and `D ≤ δ`, and the dropped attributes are reported as incidental.
3. **Given** a run where no category passes `τ`, **When** results are reported, **Then** "no category broke it reproducibly" is distinguishable from "the assistant answered correctly", by also surfacing the individual queries that did reach `τ`.

### Edge cases

- A query citing no knowledge-base entity leaves the grader nothing to check against, so its score reflects the judge's own knowledge. Must be visible on the record, not silently averaged in.
- A descriptor resting on a handful of probes cannot distinguish "never failed" from "undersampled", which is why every rate travels with its sample size.
- A principle in `Π` with no grader bound must fail loudly at construction, never contribute a silent zero to `v`.
- A refusal to answer is a legitimate response, not a transport failure. Whether it violates a principle is the rubric's call, and the rubric is the user's.

## Requirements

### Functional Requirements

**Behavioral contract**

- **FR-001**: Gaussia MUST specify what a behavioral contract is — principles, their weights, their rubrics, their bound graders — and MUST validate an instance of it: weights non-negative and summing to `1 ± 1e-9`, identifiers unique, exactly one grader per principle.
- **FR-002**: The principles themselves MUST come from the user. Gaussia MUST NOT ship a contract, since the paper defines `Π` as an input.
- **FR-003**: A principle with no grader bound MUST fail at contract construction.
- **FR-004**: `v(x,r) = Σ_j w_j · π̂_j(x,r)` MUST be computed with the per-principle grades retained on the outcome.

**Grading**

- **FR-005**: Gaussia MUST specify the grader interface, and every grade MUST record the grader, the model and the verdict method that produced it. Graders MUST be substitutable without touching anything downstream.
- **FR-006**: Rubric text, verdict surface forms and reasoning budget MUST be user-supplied configuration.
- **FR-007**: A base grader MUST ship for users who do not want to write their own, declared as such. It takes the user's judge model, locates the verdict by scanning the full per-token sequence for the last match against the configured surface forms, and discards that verdict when the model's own final answer does not independently parse to one.
- **FR-008**: When logprobs are unusable or no verdict token appears among them, the base grader MUST fall back to sampling over `k` samples and mark the grades as fallback-derived.
- **FR-009**: This feature MUST NOT modify the framework's existing shared judge.

**Profile**

- **FR-010**: The Profiler MUST accept probes and tags only, with no access path to the knowledge base.
- **FR-011**: A probe produced by a control strategy MUST carry no principle under test, and MUST be excluded from every violation-rate aggregate while remaining in the graded record. No library behaviour may depend on a plugin, strategy or template identifier.
- **FR-012**: Weakness entries MUST be keyed by `(principle, descriptor)` and MUST carry the rate, its sample size and its standard error.
- **FR-013**: The profile MUST carry the retained hooks with their `doc` label, MUST express weaknesses as natural-language descriptors, and MUST be the only artifact passed to the Exploiter.
- **FR-014**: Grading a recorded set of responses MUST be possible without any credentials, and MUST be reached through the same target-assistant interface as a live run — an implementation that returns recorded responses instead of calling out. There is no separate frozen mode to select.
- **FR-015**: A graded outcome MUST record whether the grader had knowledge-base evidence to check the response against.
- **FR-016**: An exchange the target marks as failed MUST be recorded as ungraded and MUST count as neither a violation nor a pass.

**Target assistant**

- **FR-017**: Gaussia MUST specify the target-assistant interface — send a query, optionally within a persistent session, return the response as the specified model or mark the exchange failed — and it MUST be the only path by which this feature contacts the assistant under evaluation. **The Profiler and the Exploiter MUST both receive it**, so a user implements one adapter for their transport and both components drive it.
- **FR-018**: No transport adapter ships in gaussia. Recognising a transport-level failure — an error status, an empty body, a payload shaped like an error — is the implementation's obligation under FR-017, and the specification MUST state it.

**Probe generation**

- **FR-019**: Gaussia MUST specify every interface listed under "Interfaces the user implements" above, and the shapes of `Document`, `Probe` and `KnowledgeHook` as set out in the data specification.
- **FR-020**: Particularisation MUST be the only component with knowledge-base access, exposing results solely as tagged probes.
- **FR-021**: Each probe derived from a knowledge base MUST carry a hook whose `doc` label is derived from the generating engine's own knowledge of the base's boundary. The enumeration used for scoring MUST NOT be visible to the engine.
- **FR-022**: Four engines MUST ship as base implementations behind that interface — retrieval, graph, multi-hop and enumeration — composable over one knowledge base with duplicate merging, each surviving probe recording its originating engine. The first three MUST run by default; the enumeration engine MUST be opt-in and MUST declare that it cannot run until the user supplies an enumerator for their domain's entities.
- **FR-023**: An engine that cannot establish absence reliably MUST record that limitation on the probe, so an unreliable absence label is never indistinguishable from a confirmed one.
- **FR-024**: With no knowledge base, particularisation MUST return domain-agnostic probes with an empty hook through the same interface.

**Catalogue**

- **FR-025**: Gaussia MUST specify `PluginSpec` and `StrategySpec` as set out above, and MUST validate a catalogue before generation: every referenced principle resolves in the contract, every referenced plugin exists, `transform` is one of the four known transformations, `doc` is 0 or 1, identifiers are unique, and every `entity_kind` is declared as handled by at least one configured engine. A catalogue asking for an entity kind nothing can produce MUST be rejected rather than yielding an empty probe set.
- **FR-026**: A strategy with no plugin MUST be treated as a control. This is the only mechanism by which a control is recognised.
- **FR-027**: The catalogue MUST be user-supplied. Gaussia ships schema examples, not a domain catalogue.

**Category search**

- **FR-028**: A category MUST be an ordered conjunction of natural-language attributes, each traceable to the weakness entry or hook that induced it.
- **FR-029**: `S(c)` MUST be computed per `eq:score` and reported with its `n`.
- **FR-030**: A query below `κ` MUST contribute exactly 0 to its category's score.
- **FR-031**: The realism gap MUST be computed without querying the assistant, and a category over `δ` MUST be discarded regardless of `S(c)`. The estimator MUST be substitutable, since the search depends on it only through `δ`.
- **FR-032**: Refinement MUST return the minimal sub-conjunction satisfying both thresholds, reporting the dropped attributes.
- **FR-033**: Both search procedures MUST sit behind one interface, the training-free one as default. The query generator MUST be a separate injectable, and under the policy-gradient search it MUST remain unmodified. The policy-gradient search MUST receive the policy it samples from and the weight-update step it applies as injected collaborators, so its sampling, gating, reward and stopping behaviour is verifiable with neither a GPU nor a trained model.

**Outputs**

- **FR-034**: The Roast Dataset MUST carry one record per query — query, response, violation score, principles charged, grader rationale, and the supporting or contradicting evidence when knowledge-grounded — and MUST be loadable through the SDK's existing dataset contract and consumable by existing metrics unmodified.
- **FR-035**: A failure report MUST rank categories by `S(c)` with evaluation counts and representative samples, and MUST surface the individual queries at or above `τ` alongside the category verdict.
- **FR-036**: A category evaluation record MUST be auditable: the attributes proposed, the queries, the responses, the per-principle rationale, and the realism and on-profile checks.

**Packaging and documentation**

- **FR-037**: Every dependency this feature adds MUST sit behind one optional extra. Importing the rest of the framework MUST NOT require them, and the interfaces MUST be importable without the extra so a user can implement against them without installing what the base implementations need.
- **FR-038**: The metric documentation MUST state that no grader has been calibrated against human labels and that the figures it produces are a judge-only measurement.

**Method parameters and shipped defaults**

- **FR-039**: A base implementation MUST ship for the query generator, the on-profile filter and the realism estimator, each declared a reference implementation. Only the estimator's construction comes from the paper; the other two are gaussia's own and MUST say so, because the alternative is not neutrality — with none of them the Exploiter cannot run at all, and every user would reimplement the same two classes with no tests behind them. Every failure report MUST record which implementation of each produced it, so a weak result is attributable to the substitutable part.
- **FR-040**: `τ` and `η` MUST be required with no default. `λ`, the queries-per-category `n` and any parameter of a shipped search implementation MUST carry defaults the user can override. `n` MUST be at least 2: at `n = 1` the standard error is zero by construction, so `S(c)` silently degenerates to the raw mean and the inconsistency penalty stops existing. A complete worked configuration MUST ship in the examples, so the required values are copied from a visible reference rather than guessed.
- **FR-041**: `κ` and `δ` MUST be optional, and when unset MUST be taken from the configured on-profile filter and realism estimator respectively. A component that declares no recommended threshold and is used with none supplied MUST fail at construction, naming the component and the parameter. No configured combination may fall back to a value calibrated for a different component's scale.

### SDK Pipeline Fit

- **New base classes**: the ten interfaces listed above. None has an equivalent among the framework's existing abstractions, whose detector, guardian and embedder contracts are shaped for span prediction, bias classification and vector encoding. The framework's corpus connector, which does load documents, lives in its own module rather than in `core/` and is shaped for regulatory corpora.
- **New components**: none of the three is a metric. The **Probe Library, the Profiler and the Exploiter are generators** (D8, D15): they drive the target assistant and produce artifacts, the primary one being the Roast Dataset.
- **New schemas**: the data specification above.
- **New strategies**: grading, probe engines (composed rather than selected), the realism estimator, the category search, and the four catalogue transformations.
- **Existing patterns affected**: none. D4 leaves the shared judge untouched. The precedent `role_adherence` set — a scoring Strategy with a logprob path and a non-logprob fallback — is followed, not modified.
- **Pipeline**: Roast Me sits **upstream** of the metric pipeline rather than inside it. There is no dataset to load, so nothing subclasses the metric base class and no dataset-loading contract is consumed on the way in (D15). The Roast Dataset it produces is what the pipeline consumes, through the framework's ordinary loading path, for existing metrics to evaluate (FR-034). No article is bent: the framework's generator base is already a plain class rather than a metric, and non-metric subsystems already live alongside metrics.

## Success Criteria

- **SC-001**: Every component of `v`, `ω`, the per-descriptor rates and `se` reproduces to within `1e-9` of hand computation over a synthetic fixture. Correctness rests on hand computation rather than on re-running live graders, whose providers drift.
- **SC-002**: For a hand-built contract, a response violating only some of its principles yields exactly the weighted sum of those weights — so a partial violation can fall below a pass threshold that a naive count would clear.
- **SC-003**: Controls are excluded purely because their strategy has no plugin, and two probes about the same documented entity land on opposite sides of that line when one names a plugin and the other does not. No library code and no test references a plugin, strategy or template name.
- **SC-004**: Over a fixture base with a known entity set, the graph engine's absence labels are confirmed by exact enumeration and the retrieval engine's are not, and the retrieval engine's probes carry that unreliability on them.
- **SC-005**: A catalogue with a dangling principle, a dangling plugin, an unknown transformation, a `doc` outside `{0,1}`, a duplicate identifier, or an `entity_kind` no configured engine handles is rejected before generation.
- **SC-006**: A Roast Dataset emitted from a run is consumed end-to-end by `Toxicity` with no change to it — a metric that reads the assistant's answer alone, since the conversion leaves the expected-answer field empty.
- **SC-007**: `S(c)`, the `κ` gate, the `δ` budget and refinement all verify against hand-computed fixtures with stub target, grader and estimator.
- **SC-008**: A stub target that reports a failed exchange produces an ungraded outcome, and that outcome moves neither the numerator nor the denominator of any rate.
- **SC-009**: A stub grader whose provider exposes no usable logprobs still produces a graded outcome, marked as fallback-derived.
- **SC-010**: The default suite runs offline, with no target credentials and no GPU. Everything needing a network or a GPU is opt-in.
- **SC-011**: Every interface imports with the `roastme` extra uninstalled, and importing any other part of the framework still succeeds.
- **SC-012**: With the shipped filter and estimator and no thresholds supplied beyond `τ` and `η`, the Exploiter constructs and runs. Substituting a filter that recommends no `κ`, with no `κ` supplied, fails at construction naming both the component and the parameter — it does not run with the shipped filter's value.
- **SC-013**: `queries_per_category = 1` is rejected at configuration, and a hand-computed fixture shows why: at `n = 1` the penalised score equals the unpenalised mean.
- **SC-014**: The policy-gradient search's query sampling, `κ` and `δ` gating, reward computation and stopping condition all verify against hand computation with a stub policy and a stub update step, on CPU. The only uncovered surface is the third-party weight update itself.

## Assumptions

- The paper is the upstream source of truth for methodology. Where it was silent, the Decisions table records the call rather than leaving it implicit.
- Judge models are reached through providers the framework already integrates. Whether a provider exposes usable logprobs is probed at runtime, not encoded in an allowlist.
- Nothing in the formulation is language-specific, and FR-006 keeps every model-facing string in the user's hands.
