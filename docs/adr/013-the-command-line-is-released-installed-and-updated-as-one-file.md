# ADR-013: The command line is released, installed and updated as one file

**Status:** Accepted
**Date:** 2026-09-14
**Tags:** cli, ci, releases, deploy

## Context

The two server applications have a delivery lifecycle: `develop` publishes an image under a moving
tag, `main` cuts a version with release-please, and a cluster pulls what it is told to pull. The
command line had a release step but no lifecycle. It was built as a zipapp and attached to its
release, and there it stopped. Whoever wanted it opened the releases page, worked out which of four
files matched their machine, downloaded it, remembered to `chmod +x`, and had no way to learn that a
newer one existed. Nothing checked the file against what the release published, and nothing checked
that the platform they picked was the platform they were on.

The command line is also the piece with the most operators and the least infrastructure. An image is
pulled by a scheduler that knows its tag; a zipapp is a file on a laptop. Its delivery has to be
`curl`-able, verifiable and self-renewing, or it drifts silently across a team while the API it talks
to does not.

One constraint shapes the whole thing: the repository releases three components under three tag
prefixes, so `releases/latest` is almost never the command line. Anything that resolves a release
has to resolve `cli-v*` specifically -- and the installer, the command line and the build matrix
each have to agree on which files a release carries, in shell, in Python and in YAML.

## Decision Drivers

- One command installs it on a machine that has nothing but `sh`, `curl` and Python 3.12.
- What is installed is what the release published, and the file says so on request.
- An operator learns about a newer command line from the command line itself.
- `develop` proves the whole delivery path without publishing anything; publishing is what a tag is
  for, exactly as it is for the images.
- The names that have to match across three languages cannot drift quietly.
- No new runtime dependency: the command line already carries an HTTP client.

## Considered Options

### Option A: A package on an index — Rejected

Publish `red-teaming-cli` to PyPI or a private index; install with `uv tool install` or `pipx`.

**Pros:** the ecosystem's own updater; no installer to maintain; version resolution is solved.

**Cons:** an index to own, credentials to hold, and a name to defend, for one command line whose
audience is the operators of this platform; a private index puts a credential in front of the first
install, which is the step that most needs to be one line. The workspace member it depends on would
have to be published too.

### Option B: A release asset and a documented download — Rejected

Keep the release attachment and write down how to pick, download and chmod the right file.

**Pros:** nothing to build.

**Cons:** every operator repeats a manual procedure that a script does better; nobody verifies a
digest by hand; nobody discovers a new version; the four asset names live only in prose, so the day
the matrix changes the documentation is wrong and nothing fails.

### Option C: An installer script and a self-replacing binary — Chosen

`install.sh` at the root of the repository, served from `main` over raw.githubusercontent, resolves
the newest `cli-v*` release, downloads the asset this platform's `uname` resolves to, verifies its
published `sha256` and installs one executable file. `redteam update` walks the same path from
inside the command line and renames the new file over the file it is running from. `redteam
--version` says what the file is. The build is one reusable workflow called by the pull-request
check, by `develop` and by release-please, and only the last one hands it a tag to publish to.

**Pros:** one line to install, one command to update, one digest checked on both paths; the release
lifecycle matches the images' -- verified on `develop`, published on a tag; a guard can hold the
three languages to one set of names.

**Cons:** an installer to maintain, written in POSIX shell because it is piped into an unknown `sh`;
a self-replacing file is a failure mode to get right; the platform table exists twice, once in shell
and once in Python.

## Decision

The command line is delivered as one file per platform, published only by its own `cli-v*` release
and reachable by two commands: `curl ... | sh` for the first install and `redteam update` for every
one after it. Both resolve the release, both verify the digest the release published, and both
refuse rather than guess. `develop` builds every platform a release publishes and publishes none.

## Consequences

### Positive

- An operator installs the command line with one line and never picks a file by hand.
- A command line reports its version and can say whether it is behind, which makes "which version
  are you on" a question with an answer.
- What is installed is checked against the release, on the first install and on every update.
- A release is never the first time the delivery path runs: `develop` builds every platform, runs
  the result and installs it with the same installer an operator uses.
- The asset names, the repository and the tag prefix are stated once each and held together by
  `tests/guards/test_cli_distribution.py`, which runs the installer and reads the workflows.

### Negative / Trade-offs

- `install.sh` is shell, and shell is where portability bugs live; it is checked by shellcheck in CI
  and exercised on every runner in the matrix, which is the mitigation, not a proof.
- The platform table is written twice, in two languages. The guard makes a disagreement fail a test
  rather than an operator's install.
- `redteam update` writes over the file it is running from. It writes beside it and renames, so an
  interrupted update leaves the previous command line intact, but it cannot update a file the
  operator may not write.
- A private repository needs a token in the environment for either path; the command line reads one
  environment variable for this and nothing else.

### Neutral

- `install.sh` carries no version and is in no component's `include-paths`: it is read from `main`,
  and what it installs is decided by the releases it finds. A change to it takes effect without a
  release, and cuts none.
- A checkout is unaffected: `uv run redteam` is the same command line, and `redteam update` says so
  instead of trying to replace an environment.

## Implementation Notes

- `apps/cli/src/redteam_cli/release.py`: the owner, the repository, the `cli-v` prefix, the
  platform-to-asset table, the releases client, the digest check, the atomic replace.
- `install.sh`: the same names in POSIX shell. `--print-asset` prints what a platform resolves to,
  which is what the guard compares against Python; `--from <file>` installs a locally built zipapp,
  which is what CI uses to verify the installer with no release in existence.
- `.github/workflows/build-cli.yml`: the one place a zipapp is built in CI. `runners` selects the
  matrix (one platform on a pull request, all four on `develop` and on a release); `release-tag`,
  given only by release-please, is what turns a build into a publication.

## Related ADRs

- Builds on [ADR-001](./001-uv-workspace-scoped-commits-per-app-releases.md)
