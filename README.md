# Alquimia Red Teaming

Verifiable adversarial testing of Alquimia agents. Probe deployed agents as black
boxes, and store what breaks them as **evidence** in a Boltzmann brain — reproducible,
with provenance, not prose.

See [`CLAUDE.md`](./CLAUDE.md) for the full architecture.

## Two packages (uv workspace)

They **never import each other**; they meet only at a data boundary (knowledge in,
findings out).

| Package | What | Deployed? |
|---------|------|-----------|
| [`packages/redteam`](./packages/redteam) | The red-teaming **app**. Probes agents, emits findings. Knows nothing about the brain. | Yes — ships to k8s / OpenShift / Railway |
| [`packages/braintools`](./packages/braintools) | Brain-curation CLI (wraps [vitruvio](https://github.com/getsfumato/vitruvio)). | No — local/pipeline tool |

```
brain ──(braintools export)──▶ knowledge.json ──▶ redteam app ──▶ findings.json ──(braintools ingest-findings)──▶ brain
```

## Setup

```bash
uv sync                 # both packages
uv sync --extra roast   # + RoastMe pipeline (heavy)

# vitruvio (used by braintools only; not on PyPI):
curl -fsSL https://raw.githubusercontent.com/getsfumato/vitruvio/main/install.sh | sh
```

## Usage

```bash
# app
uv run redteam check --knowledge ./data/knowledge.json
uv run redteam roast                                       # [roadmap]

# brain curation
uv run braintools init --actor curator --actor-kind human
uv run braintools ingest ./policy.pdf
uv run braintools search "refund policy" -n 5
uv run braintools ingest-findings ./data/findings.json
```

## Develop

```bash
uv run pytest
uv run ruff check .
```
