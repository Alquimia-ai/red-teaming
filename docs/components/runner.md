# The runner

`redteam_runner`, the job that takes one run from generation to manifest and exits. Not a
service: a run lasts hours, and there is exactly one process per run.

```
redteam-runner run <run_id> [--dry-run]
```

| Exit | Meaning |
|---|---|
| 0 | the run closed, or was already closed |
| 1 | this attempt failed; a failure record is in the store and the platform's retry policy relaunches |
| 2 | nothing to resume: the id is outside the rule, or the API never accepted the run |

## The pipeline

`pipeline.execute` reads the frozen spec; returns at once for a dry run or a run that already has a
manifest; announces the attempt; generates the probe set in process or reads the pinned one;
expands the plan; diffs it against the store; attacks through the engine's governed door with the
attempt's start on the budget's clock; writes the manifest with coverage read off the store and
the generation's provenance in `components`; delivers the webhook. Any exception after the attempt
began becomes a failure record under the attempt's key -- typed by the kind of transport failure
when the channel is what died -- and a `failed` webhook; a store that cannot take the record does
not hide the error that ended the attempt.

## Probe identity and existing runs

A generated probe's identity includes its base entity as well as its transformed premise.
Different source entities can converge on the same question (for example through `swap_token`),
but their knowledge hooks remain distinct. Each origin and replica must retain its own work unit;
discarding a repeated question would silently change the planned coverage.

Previously generated sets can contain duplicate identities and fail with
`ProfileOrderError: duplicate work-unit identity` before conduction starts. After deploying the
identity correction, start a **new run** to generate corrected probes. Resuming an existing run
reads its immutable `probes.json` and blob unchanged; it does not recalculate identities or rewrite
traces. Completed runs and their evidence remain untouched.

## What it composes

The only process where generation and conduction meet: `redteam_probes` (the pulled brain, the
constructions, the content-addressed set) and `redteam_engine` (the door, the attacker, recording,
resume, the control artifacts, the dataset). It resolves every credential through
`redteam_secrets` from references the API forwarded; it never reads one off its own environment by
name.

## Configuration

The same `REDTEAM_*` store settings as the API, `REDTEAM_SECRETS_BACKEND=env` (the API hands values
or references into the environment), and `REDTEAM_BRAIN_REGISTRY_*` for a private brain registry.
Injectable for tests: the store, the resolver, the target, the attackers, the knowledge base and
the webhook client.

## Judge reasoning envelopes

The control judge requires logprobs; it never silently substitutes sampled verdicts.
`redteam_judges.grading.ReasoningLogprobGrader` adapts the final-answer view when a provider returns
inline reasoning immediately followed by a verdict, such as `reasoning</think>NO`. It passes only
the text after the last closing tag to Gaussia's final-word validation. The original logprob
sequence, token positions and probability calculation remain unchanged.

The matching `</think>` token and a verdict token after it must both exist in the logprob sequence.
Without that boundary the response is rejected rather than borrowing a verdict from the reasoning.
An unclosed reasoning envelope or `finish_reason=length` is also rejected and follows the existing
bounded retry policy. Plain final answers and providers that already separate reasoning need no
normalization. The adaptation lives in red-teaming, not in an edited installed dependency; its
tests exercise the real Gaussia grader through `build_grader`.
