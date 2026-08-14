# braintools

Local tooling to curate the Alquimia red-teaming Boltzmann brain. Wraps the
[vitruvio](https://github.com/getsfumato/vitruvio) CLI. **Not deployed with the app** —
the red-teaming app never imports this package.

```bash
# vitruvio is not on PyPI — install with the official script (fetches release wheels):
curl -fsSL https://raw.githubusercontent.com/getsfumato/vitruvio/main/install.sh | sh

uv run braintools init --actor curator --actor-kind human
uv run braintools ingest ./policy.pdf --proposer anthropic
uv run braintools index
uv run braintools search "refund policy" -n 5
uv run braintools browse

# the data boundary with the app: ingest the app's findings artifact back as evidence
uv run braintools ingest-findings ./data/findings.json
```

## Capturing sparring as source

Interactive sparring / findings become reproducible, git-shared knowledge when written
as source docs under `docs/sources/sparring/` (subject `sparring`):

```bash
uv run braintools spar "prompt injection via tool args" --author leo --target alquimia-core
# fill in the scaffolded YYYY-MM-DD-<author>-<slug>.md, then commit and:
uv run braintools seed        # ingests docs/sources/*; each subdir is a subject
```

See `docs/sources/sparring/README.md` for the convention.

## Distributing the brain

The brain is data, not code — it is never committed to git. Two ways to share it:

```bash
# 1) rebuild from committed sources (deterministic, offline; needs pandoc for .tex)
uv run braintools seed

# 2) OCI registry (ghcr.io) — publish once, pull read-only
vitruvio registry login ghcr.io      # curator: GitHub PAT with write:packages
uv run braintools publish v1         # dist push + writes brain.lock (the committed pin)
uv run braintools pull               # collaborator: reads brain.lock, installs, verifies

# test the loop offline with a filesystem registry (no network/creds):
uv run braintools publish v1 --local /tmp/reg
uv run braintools pull --local /tmp/reg
```

Config via env: `BRAINTOOLS_BRAIN_DIR` (default `./brain`), `BRAINTOOLS_VITRUVIO_BIN`,
`BRAINTOOLS_REGISTRY` (default `ghcr.io/alquimia-ai/red-teaming-brain`),
`BRAINTOOLS_SOURCES_DIR` (default `packages/braintools/docs/sources/roastme`).
