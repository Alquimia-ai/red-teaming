---
name: adr
description: Create a new Architecture Decision Record under docs/adr/ following this repo's ADR conventions. Use when a non-trivial architectural decision has been made or is about to be made.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# Create an ADR

Scaffold an Architecture Decision Record under `docs/adr/`, following
[`docs/adr/README.md`](../../../docs/adr/README.md) and
[`docs/adr/TEMPLATE.md`](../../../docs/adr/TEMPLATE.md). CI validates every ADR against those
conventions (`.github/workflows/validate-adrs.yml`).

## When to use this skill

- A choice about the system was made that future engineers cannot infer from the code alone:
  a storage model, a process topology, a wire contract, a deployment shape, a boundary between
  packages.

Do **not** use it for feature descriptions or operating procedures — those live in
`docs/components/` and `docs/deploy/`.

## Steps

1. **Confirm the input.** Title (5–10 words, no version numbers, no parentheses, no em-dashes),
   Status (`Proposed` by default, or `Accepted`, `Deprecated`, `Superseded by ADR-NNN`), optional
   comma-separated lowercase tags, and enough context/decision to fill the required sections. Ask one
   focused question if the decision itself is unclear.
2. **Compute the next number:**

   ```bash
   ls docs/adr | grep -E '^[0-9]{3}-' | sort | tail -1
   ```

   Next = last + 1, zero-padded to three digits.
3. **Build the slug**: lowercase kebab-case from the title, dropping articles. `NNN-<slug>.md`.
4. **Use today's date:** `date +%Y-%m-%d`. Never invent a date.
5. **Write the file** from the template: `# ADR-NNN: <Title>`, frontmatter, `## Context`,
   `## Decision Drivers`, `## Considered Options` (each `### Option <Letter>: <Name> — Chosen|Rejected`
   with `**Pros:**`/`**Cons:**`), `## Decision`, `## Consequences` (`### Positive`,
   `### Negative / Trade-offs`, optional `### Neutral`), optional `## Implementation Notes` and
   `## Related ADRs`. Remove unused optional sections; leave no placeholders.
6. **Add the index row** to `docs/adr/README.md` (`# | Decision | Status | Tags`), using the status
   emoji map: `✅ Accepted`, `📝 Proposed`, `🚫 Deprecated`, `↩️ Superseded by ADR-NNN`.
7. **If superseding**, set the predecessor's `**Status:**` to `Superseded by ADR-NNN`, add
   `- Supersedes [ADR-XXX](./XXX-slug.md)` under `## Related ADRs`, and update its index row.
8. **Validate** before reporting: filename `NNN-<slug>.md`; title line exact; canonical status; ISO
   date; no placeholders; no emoji in the body; all cross-references linked; index row present;
   numbering contiguous.

## Conventions reference

- `##` for sections, `###` for subsections; never numbered headings.
- One blank line between sections; no `---` separators.
- Mermaid allowed inline; multi-line labels use `<br/>`.
- ADRs are immutable once accepted: write a new one that supersedes rather than editing.

## Output

Report the file path, number, title and slug, the index row added, and the suggested commit
message `docs(docs): add ADR-NNN <slug>` (commit with `/commit`).
