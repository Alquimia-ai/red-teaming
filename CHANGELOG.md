# Changelogs

Each app keeps its own changelog, written by release-please when a release is cut:

- [`apps/api/CHANGELOG.md`](apps/api/CHANGELOG.md)
- [`apps/runner/CHANGELOG.md`](apps/runner/CHANGELOG.md)
- [`apps/cli/CHANGELOG.md`](apps/cli/CHANGELOG.md)

The packages under `packages/` are not released on their own: a change to one of them is released
with every app whose dependency closure carries it. See [`docs/release.md`](docs/release.md).
