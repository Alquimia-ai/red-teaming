# Releases

Three things ship, each on its own cadence: the API image, the runner image, and the command line.
`develop` is where they integrate; `main` is where they are released.

## develop: images under a moving tag, the command line proved and kept

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

The command line follows the same rule with the opposite conclusion: `.github/workflows/cli-develop.yml`
builds it for **every platform a release publishes** on every push to `develop`, runs it, and
installs it with `install.sh` -- and publishes nothing. A zipapp is a file somebody downloads and
runs; there is no `develop` tag for one, so what `develop` buys is the certainty that the release
step is not the first time anybody built it. Each build is kept as a workflow artifact for seven
days. A pull request builds the same way on one platform (`ci.yml`), which is what keeps the loop
short.

All three go through one reusable workflow each -- `publish-image.yml` for an image,
`build-cli.yml` for the command line -- so `develop` and a release cannot drift on how a thing is
built. The only difference between the two callers is that the release hands `build-cli.yml` a tag
to attach the files to, and a guard (`tests/guards/test_cli_distribution.py`) refuses any other
caller that does.

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
- **cli**: one zipapp per platform, each with its `.sha256` beside it, attached to the release --
  `redteam-linux-x86_64.pyz`, `redteam-linux-aarch64.pyz`, `redteam-darwin-arm64.pyz`,
  `redteam-darwin-x86_64.pyz`. Each runs with the platform's own Python 3.12:
  `chmod +x redteam-darwin-arm64.pyz && ./redteam-darwin-arm64.pyz --version`. This release is
  what `install.sh` and `redteam update` download; nothing else publishes a command line.

Both workflows build through the same reusable one in this repository
(`.github/workflows/publish-image.yml`), so `develop` and a release cannot drift on how an image is
built: same Dockerfile, same platforms, same labels, a build cache per app.

## Installing the command line

```bash
curl -fsSL https://raw.githubusercontent.com/Alquimia-ai/red-teaming/main/install.sh | sh
redteam --version
redteam update                 # the same thing, from inside the command line
```

The script is served from `main` and carries no version of its own: it resolves the newest `cli-v*`
tag -- never the repository's newest release, which usually belongs to an image -- downloads the
asset this platform's `uname` resolves to, checks it against the digest the release published, and
installs it as one executable file in `$HOME/.local/bin` (`--dir` elsewhere). `--version cli-v0.2.0`
pins one. A private repository needs `REDTEAM_GITHUB_TOKEN` in the environment; the same variable is
what `redteam update` reads.

| Want | Command |
|---|---|
| install, or reinstall | `curl -fsSL .../install.sh \| sh` |
| a particular release | `curl -fsSL .../install.sh \| sh -s -- --version cli-v0.2.0` |
| somewhere else | `curl -fsSL .../install.sh \| sh -s -- --dir /usr/local/bin` |
| what is available | `redteam update --check` |
| take it | `redteam update` |
| go back | `redteam update --tag cli-v0.1.0 --force` |
| a build from this checkout | `scripts/build_pyz.sh dist && sh install.sh --from dist/redteam-*.pyz` |

`redteam update` replaces the file it is running from, in place, and only after the download hashes
to what the release published: it writes the new file beside the old one and renames it over it, so
an update interrupted half way through leaves the command line it had. It refuses, with what to run
instead, when the command line is not one file -- a checkout or a wheel is updated by whatever
installed it.

Three pieces have to agree on the names for any of this to work: the installer in shell, the
command line in Python, and the build matrix in YAML. They are held together by
`tests/guards/test_cli_distribution.py`, which runs the installer for every platform and compares
what it resolves with what `redteam update` would download.

## Promoting

```
develop ──(pull request)──▶ main ──(release-please opens release PRs)──▶ merge ──▶ tags, images, zipapps
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
scripts/build_pyz.sh dist                          # dist/redteam-<os>-<arch>.pyz, from this checkout
dist/redteam-*.pyz --version
sh install.sh --from dist/redteam-*.pyz --dir ~/.local/bin   # install that one
sh install.sh --print-asset                        # which file this machine would download
```

The script builds the command line and the contracts package as wheels first, because the command
line depends on a workspace member no index serves, and hands both to `shiv`. It is the same script
CI runs, and the only place a zipapp is built.

## Initial bug-fix deliveries

Ship the fixes in two promotions, preserving separate implementation PRs:

| Delivery | Implementation groups | Release artifacts |
|---|---|---|
| First | Run allowance and atomic recovery (#13, #15, #16); consistent bundles and pinned priors (#14, #19) | Initial API, runner and CLI releases, including the existing develop baseline |
| Second | Frozen-request retries and terminal Kubernetes Job replacement (#17, #18) | API patch; retain the first delivery's compatible runner and CLI |

Promote the first delivery before integrating the second group. Merge release-please's generated
version PRs and verify versioned multi-platform images and CLI attachments before counting a
delivery as published. Synchronize main's version commits into develop before the next promotion.
Version numbers are determined by release-please; the expected initial versions are 0.1.0.

The first release notes must identify #17 and #18 as still pending. Include exact image digests
and a compatible API/runner/CLI version set. Publication is the endpoint of this plan; it does not
include deploying to a user's cluster. Default CI and mocked Kubernetes tests do not certify a real
cluster deployment.

Stop old runners and catalogue publishers before enabling these storage protocols in a deployment.
Legacy incomplete runs without trustworthy consumed allowance, required provenance, or a needed
pinned prior must retain their evidence and start under a new id. Existing manifests remain
readable. Do not roll an old writer back onto runs or reservations written by the new code; keep
the last compatible artifact versions pinned and publish a corrective patch if needed.

## Catalogue v2 and conditional brain delivery

Deliver the catalogue-v2 change through three ordered implementation pull requests:

| Pull request | Scope | Exit condition |
|---|---|---|
| Contract and runtime | The single catalogue document, `RunSpec.brain`, strategy brain requirements, transform descriptors and the three interaction modes | Contract, API, runner, probe and engine tests pass together |
| Packaging and operations | Schema-v2 seed documents, local seeding and removal of production Helm auto-seeding | Compose keeps its local fixtures and the production chart renders no seed Job |
| Adoption and release | ADR-014, operator and architecture documentation, migration notes | ADR validation passes and every example uses the v2 file grammar |

Merge them in order into `develop`, then promote `develop` to `main`. This is a coordinated
breaking release because old run specs and old catalogue documents are deliberately rejected.
Release-please determines the exact versions from repository history; expect a minor bump for API,
runner and CLI while they remain below 1.0. The release notes must call out the `kb_ref` to `brain`
migration, the one-file catalogue format, exact language matching and the removal of production
auto-seeding. Verify the API and runner image digests and every CLI archive checksum before marking
the release complete.
