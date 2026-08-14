---
name: red-teaming-brain
description: Use when working with THIS repo's red-teaming Boltzmann brain — querying it, adding or capturing knowledge, deciding whether to seed/rebuild or pull, sharing it with the team, or when ./brain is missing, brain.lock, braintools, seed, or sparring come up.
allowed-tools: Bash(uv run braintools:*), Read, Grep, Glob
---

# Red-teaming brain

This repo's brain lives at `./brain` and is operated through **`braintools`** (`uv run
braintools ...`), which wraps vitruvio over that path. The brain returns **evidence, not
prose** — compose the answer yourself and cite `block_id`s.

**This is NOT the `ethicompass-brain` MCP.** That server is a different, unrelated
project. For this repo, always use `braintools`; never route these operations through
the ethicompass-brain MCP tools.

## When to do what

| Situation | Command |
|---|---|
| Need to query but `./brain` is missing/stale | `brain.lock` exists → `uv run braintools pull`; else → `uv run braintools seed` |
| Query the brain | `uv run braintools search "<q>" [--subject roastme\|sparring] [-n N] [--content]` |
| A source doc under `docs/sources/` was added/changed | `uv run braintools seed` (idempotent rebuild — the way knowledge enters) |
| Capture a sparring finding | `uv run braintools spar "<title>" --author <you>` → fill the file → `git commit` → `uv run braintools seed` |
| Get a teammate's published knowledge | `git pull` then `uv run braintools pull` |
| Share your additions via the registry | **PREPARE, then STOP** (see below) |

`seed` = rebuild from committed sources in `docs/sources/*` (each subdir is a subject).
`pull` = install the exact published version pinned in `brain.lock`, and verify it.
Prefer `seed` over ingesting single files, so the brain always matches the sources.

## Hard rules

- **Never publish to the registry yourself.** Publishing to ghcr is a **curator-only**
  step: it is outward-facing and needs credentials. When asked to share knowledge,
  PREPARE it (`seed`, commit the source docs / `brain.lock`) and then STOP and tell the
  human to run `uv run braintools publish vN` themselves. Do not run `publish`, `vitruvio
  dist push`, or `vitruvio registry login`.
- **Never commit `./brain/` or `vitruvio.toml` to git.** They are local state / data and
  are gitignored. Knowledge is shared through committed *source docs* + the registry.
- **Use `braintools`, not raw `vitruvio`,** for day-to-day brain ops in this repo (it
  targets `./brain` automatically). Fall back to `vitruvio --brain ./brain ...` only for
  operations `braintools` does not expose.

## Red flags — STOP

- About to run `braintools publish` / `vitruvio dist push` / `registry login` → that's
  the curator's job. Prepare and hand off.
- About to `git add ./brain` (or `vitruvio.toml`) → it's data, not code. Don't.
- Reaching for the `ethicompass-brain` MCP to search/pull/push → wrong project. Use
  `braintools`.
- Re-ingesting one file when sources changed → run `seed` instead for a consistent brain.
