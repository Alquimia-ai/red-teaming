# ADR-001: One uv workspace, scoped commits and per-app releases

**Status:** Accepted
**Date:** 2026-09-10
**Tags:** repo, ci, releases

## Context

The platform is several deployable applications (an HTTP API, a per-run runner, an operator CLI)
built on a dozen small libraries that share domain types, a storage layout and a set of
invariants. The libraries are not meaningful on their own: a change to the plan model reaches the
API, the runner and the CLI in the same pull request. The applications, however, ship separately
-- an image each, a zipapp for the CLI -- and consumers pin them by version.

Two forces pull apart. Code review, refactoring and testing want one repository, one environment
and one lockfile. Release management wants to say precisely which application changed, and to cut
a version for that one alone.

## Decision Drivers

- One command installs, lints, types and tests the whole codebase.
- A commit is attributable to the component it changes without reading the diff.
- Each application is versioned and released independently, with its own changelog.
- The integration branch produces deployable images without producing releases.
- Nothing about the layout is bespoke: a new engineer recognises it from any uv workspace.

## Considered Options

### Option A: One repository per application — Rejected

Libraries published to a private index, applications depending on pinned versions.

**Pros:** clear ownership boundaries; independent CI per repository.

**Cons:** a domain change becomes three or four coordinated releases; the shared invariants are
guarded nowhere; local development needs several checkouts kept in step by hand.

### Option B: One uv workspace with unscoped commits — Rejected

A single `uv.lock`, applications and libraries as workspace members, free-form conventional
commits.

**Pros:** one environment, one lockfile, atomic cross-cutting changes.

**Cons:** a commit without a scope cannot be attributed to a release; per-app changelogs fill
with unrelated entries or miss relevant ones.

### Option C: One uv workspace, mandatory commit scopes, per-app Release Please — Chosen

A virtual workspace root declares the members and every tool's configuration once. Commits
follow Conventional Commits with a scope drawn from an enum of the members plus a few
cross-cutting scopes. Release Please runs on `main` only, one component per application, with
each component's `include-paths` equal to that application's dependency closure. `develop`
builds and pushes images tagged `develop`; it never releases.

**Pros:** one environment; every commit attributable; each app versioned on its own; the
integration branch stays cheap.

**Cons:** the scope enum and the release closures must be kept in step with the workspace --
which is why both are guarded by tests.

## Decision

Adopt Option C. The repository is a uv workspace rooted at a virtual `pyproject.toml`; commits
carry a mandatory scope enforced by commitlint; Release Please cuts per-application releases from
`main`; pushes to `develop` publish `develop`-tagged images and nothing else.

## Consequences

### Positive

- `uv sync --all-packages` gives one environment for everything; one lockfile to reason about.
- Ruff, mypy and pytest are configured once at the root; members carry no tool configuration.
- Release notes per application are generated from the commits that touched it.
- The workspace layout, the scope enum and the release configuration are each checked by a guard.

### Negative / Trade-offs

- Every commit needs a scope; a contributor learns the enum or the hook rejects the message.
- Release closures are hand-maintained lists; the guard catches drift but not intent.
- One lockfile means one resolution: a heavy dependency of one app is resolved for all.

### Neutral

- Python 3.12 is the single interpreter version across the workspace and the container images.

## Implementation Notes

- Root `pyproject.toml`: `[tool.uv.workspace] members = ["apps/*", "packages/*"]`, shared
  `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`, dev dependency group.
- `commitlint.config.js`: `scope-enum` and `scope-empty: never`; the only ignored pattern is
  Release Please's own `chore(main): release` commits.
- `tests/guards/test_scopes.py` fails when a member has no scope; a release-closure guard lands
  with the first application.
