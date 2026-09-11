# Releases

Three things ship, each on its own cadence: the API image, the runner image, and the command line.
`develop` is where they integrate; `main` is where they are released.

## develop: images on every push

`.github/workflows/images-develop.yml` builds `ghcr.io/alquimia-ai/red-teaming-api` and
`ghcr.io/alquimia-ai/red-teaming-runner` for `linux/amd64` and `linux/arm64` on every push to
`develop`, under two tags each: `develop`, which always points at the newest, and `sha-<7>`, which
names the exact commit for a deployment that wants to pin what it runs. Nothing is versioned here;
`develop` is what the compose stack pulls when it is not built from a checkout.

The images are **packages of this repository** on GitHub's container registry: the workflow pushes
with its own token (`packages: write`), no registry credential lives in the repository, and every
image carries `org.opencontainers.image.source` pointing here, which is what files it under the
repository's packages. A package inherits the repository's visibility on its first push; a private
repository's images need a pull secret on the cluster (`docs/deploy/`), or the package made public
from its settings page.

## main: release-please

`.github/workflows/release-please.yml` runs on every push to `main` -- which only ever comes from a
promotion of `develop`. release-please reads the conventional commits since each component's last
tag and decides, per component, whether there is something to release:

| Commit | Effect on the components whose paths it touched |
|---|---|
| `feat(...)` | minor bump (`0.1.0` → `0.2.0`) |
| `fix(...)`, `perf(...)`, `refactor(...)` | patch bump, listed in the changelog |
| `build`, `docs`, `chore`, `ci`, `test` | no release, hidden from the changelog |
| `feat(...)!` or `BREAKING CHANGE:` | still a minor bump while the version is `0.x` (`bump-minor-pre-major`) |

Which components a commit touches is decided by `include-paths` in `release-please-config.json`:
each app's own directory, every workspace package in its dependency closure, and `uv.lock`. A fix in
the store package releases the API and the runner; a fix in the engine releases the runner alone;
the command line also ships `deploy/compose` and `deploy/seed`, so a change there releases it. A
guard (`tests/guards/test_release_closure.py`) holds those lists to the dependency graph.

For each component with something to release, release-please opens **one pull request**
(`chore(main): release api 0.2.0`) that bumps `apps/<app>/pyproject.toml`, updates
`apps/<app>/CHANGELOG.md` and `.release-please-manifest.json`. Merging that pull request cuts the
tag -- `api-v0.2.0`, `runner-v0.1.3`, `cli-v0.2.0` -- and the GitHub release, and the same workflow
then publishes what the component ships:

- **api**, **runner**: the image under its version (`ghcr.io/alquimia-ai/red-teaming-api:0.2.0`)
  and under `latest`, for `linux/amd64` and `linux/arm64`.
- **cli**: one zipapp per platform, attached to the release --
  `redteam-linux-x86_64.pyz`, `redteam-linux-aarch64.pyz`, `redteam-darwin-arm64.pyz`,
  `redteam-darwin-x86_64.pyz`. Each runs with the platform's own Python 3.12:
  `chmod +x redteam-darwin-arm64.pyz && ./redteam-darwin-arm64.pyz --help`.

Both workflows build through the same reusable one in this repository
(`.github/workflows/publish-image.yml`), so `develop` and a release cannot drift on how an image is
built: same Dockerfile, same platforms, same labels, a build cache per app.

## Promoting

```
develop ──(pull request)──▶ main ──(release-please opens release PRs)──▶ merge ──▶ tags, images, zipapp
```

A promotion is an ordinary pull request from `develop` to `main`, reviewed like any other. The
release pull requests release-please opens are the only commits that land on `main` any other way,
and commitlint ignores their subject (`chore(main): release ...`).

## The first release

Every app starts at `0.0.0` in its `pyproject.toml` and in `.release-please-manifest.json`, so the
first promotion releases each as `0.1.0`: the history is all `feat` commits, and `feat` bumps the
minor.

## Locally

```bash
scripts/build_pyz.sh dist          # dist/redteam-<os>-<arch>.pyz, from this checkout
dist/redteam-*.pyz --help
```

The script builds the command line and the contracts package as wheels first, because the command
line depends on a workspace member no index serves, and hands both to `shiv`.
