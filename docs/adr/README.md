# Architecture Decision Records

This folder records the architectural decisions behind the red-teaming platform. ADRs are
immutable: once accepted they are not rewritten in place; they are superseded by a new ADR.

## Index

| # | Decision | Status | Tags |
|---|----------|--------|------|
| [001](001-uv-workspace-scoped-commits-per-app-releases.md) | One uv workspace, scoped commits and per-app releases | ✅ Accepted | repo, ci, releases |
| [002](002-stateless-api-and-one-runner-per-run.md) | A stateless API and one runner process per run | ✅ Accepted | api, runner, dispatch, store |
| [003](003-append-only-store-and-content-identity.md) | Append-only store and content-derived identity | ✅ Accepted | store, contracts, evidence |
| [004](004-models-are-configuration-and-one-governed-door-to-the-target.md) | Models are configuration and one governed door to the target | ✅ Accepted | judges, target, knowledge, provenance |
| [005](005-catalogue-bundles-name-constructions-the-runtime-builds.md) | Catalogue bundles name constructions the runtime builds | ✅ Accepted | catalogue, probes, contracts |
| [006](006-strategies-say-what-deliveries-say-how.md) | Strategies declare what a probe says and deliveries declare how it reaches the target | ✅ Accepted | engine, catalogue, contracts, evidence |
| [007](007-control-signal-as-control-artifacts-and-typed-transport-failures.md) | Control signal persists as control artifacts and transport failures never close a unit | ✅ Accepted | engine, store, contracts, evidence |
| [008](008-helm-charts-sops-and-vllm-for-the-appliance.md) | Helm charts with SOPS secrets and vLLM served models for the appliance | ✅ Accepted | deploy, dispatch, settings |
| [009](009-durable-call-reservations-and-atomic-recovery.md) | Durable call reservations and atomic stage recovery | ✅ Accepted | engine, store, runner |

**Status legend:** ✅ Accepted · 📝 Proposed · 🚫 Deprecated · ↩️ Superseded by ADR-NNN

## Conventions

ADRs follow a single canonical structure. New ADRs are generated from
[`TEMPLATE.md`](./TEMPLATE.md) with the `/adr` skill, which computes the next number, fills the
frontmatter and appends a row to this index. `scripts/validate_adrs.py` enforces the rules below,
locally and in CI.

### File and naming

- Filename: `NNN-kebab-slug.md` (three-digit zero-padded number, contiguous numbering).
- Title: `# ADR-NNN: <short decision phrase>` — single line, no em-dashes, no parentheses, no
  version numbers.

### Frontmatter (required)

```markdown
**Status:** <Proposed | Accepted | Deprecated | Superseded by ADR-NNN>
**Date:** YYYY-MM-DD
**Tags:** <optional, comma-separated>
```

### Section order (required when present)

1. `## Context`
2. `## Decision Drivers`
3. `## Considered Options` — each option as `### Option <Letter>: <Name> — Chosen|Rejected`
   with `**Pros:**` / `**Cons:**`
4. `## Decision`
5. `## Consequences` — with `### Positive` / `### Negative / Trade-offs` (and optional `### Neutral`)
6. `## Implementation Notes` *(optional)*
7. `## Related ADRs` *(optional)* — `Supersedes / Superseded by / Refines / Complements /
   Builds on [ADR-NNN](./NNN-slug.md)`

### Style rules

- `##` for top-level sections, `###` for subsections. Never numbered headings.
- One blank line between sections; no `---` separators.
- Mermaid diagrams allowed inline; multi-line node labels use `<br/>`, never `\n` or `\`.
- No emoji in ADR bodies. Emoji status lives only in this index.
- Cross-references are always linked: `[ADR-NNN](./NNN-slug.md)`.

### Lifecycle

- ADRs are **immutable** once accepted. Edits are limited to typos, broken links, or appending a
  `Superseded by` notice.
- To change a decision, write a new ADR that supersedes the previous one and update the previous
  ADR's status.
