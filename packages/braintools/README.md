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

Config via env: `BRAINTOOLS_BRAIN_DIR` (default `./brain`), `BRAINTOOLS_VITRUVIO_BIN`.
