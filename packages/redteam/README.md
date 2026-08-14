# redteam (app)

The deployable red-teaming application. Probes Alquimia agents as black boxes and emits
findings. **Knows nothing about the Boltzmann brain** — it reads a knowledge bundle and
writes findings through data-artifact ports (`redteam.ports`), so the image ships to
k8s / OpenShift / Railway without any brain code.

```bash
uv run redteam check --knowledge ./data/knowledge.json   # validate the input boundary
uv run redteam roast                                     # [roadmap] run RoastMe, write findings
```

Config via env:
- `ALQUIMIA_AGENT_BASE_URL`, `ALQUIMIA_AGENT_TOKEN` — the agent under test
- `REDTEAM_KNOWLEDGE_PATH` (default `data/knowledge.json`) — input bundle (volume)
- `REDTEAM_FINDINGS_PATH` (default `data/findings.json`) — output artifact (volume)

## Boundary contract

Input `knowledge.json` — produced upstream (e.g. by `braintools` from the brain):

```json
{
  "documents": [{"id": "d1", "content": "POLICY-1 covers 30 days.", "structured": false}],
  "catalogue": { "plugins": [], "strategies": [] },
  "contract":  { "principles": [] }
}
```

Output `findings.json` — the FailureReport / RoastDataset, ingested back by
`braintools ingest-findings`.

## Docker

```bash
docker build -f packages/redteam/Dockerfile -t alquimia-redteam .   # from repo root
```
