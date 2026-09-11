# The local stack

Everything the platform needs on one machine, through docker compose: MinIO as the store, the API,
a seed that publishes the bundles under `deploy/seed/`, a webhook receiver that keeps every
delivery, and a mock assistant that speaks the Alquimia runtime's inference API and misbehaves on
purpose. The runner is not a service: the API creates one container per run through the Docker
socket, exactly as it creates one Job per run on a cluster.

## Once

```bash
uv sync --all-packages                     # or install the `redteam` command line on its own
redteam init                               # .redteam/ here: config.json, .env (0600), catalogues/, runs/
$EDITOR .redteam/.env                      # keys, if a run will name a hosted model or a real assistant
redteam local up --build                   # from a checkout; `redteam local up` pulls the published images
```

`local up` builds `red-teaming-runner:local`, brings the stack up, and the seed publishes the two
bundles and the prior into an empty store. Bringing the stack up again publishes nothing: an
identical bundle is answered with the version it already has.

| Service | Where | What it is |
|---|---|---|
| `api` | http://localhost:8080 | the gate: `POST /runs`, `GET /runs/{id}`, bundles, priors |
| `minio` | http://localhost:9000 (console :9001) | the store, `redteamadmin`/`redteamadmin` |
| `mock-target` | http://localhost:8082 | an assistant that discloses its instructions when pressed |
| `receiver` | http://localhost:8083 | keeps every webhook it acknowledges; `GET /received?run_id=` |

## A run

```bash
redteam catalogue validate my-bundle/                 # every check publishing runs; writes nothing
redteam catalogue publish my-bundle my-bundle/        # the next version, kept in .redteam/catalogues/
redteam run validate spec.json                        # the gate alone
redteam run start spec.json --follow                  # accept, freeze, launch; poll until it closes
redteam run result <run_id>                           # the manifest -> .redteam/runs/<run_id>/manifest.json
redteam receiver export <run_id>                      # what the receiver was delivered -> delivery.json
```

A spec against the mock, with no model anywhere:

```json
{
  "run_id": "redteam-run-first",
  "catalogues": ["assistant-baseline"],
  "strategies": ["ask-identity", "ask-system-prompt", "act-for-another", "refuse-escalation"],
  "connector": {
    "kind": "alquimia",
    "endpoint": "http://mock-target:8080",
    "secret_ref": "TARGET_KEY",
    "options": {"assistant_id": "mock"}
  },
  "judge": {"model": "stand-in"},
  "context": {"language": "en", "domain": "an assistant under test"},
  "replicas": 2,
  "webhook_url": "http://receiver:8080/hook"
}
```

The judge names no provider, so the run grades with the deterministic stand-in and the manifest
says so (`profile_judge_serving_path: fake`). The strategies are narrowed to the ones that stand
without a knowledge base and are delivered as one turn; the seed's conducted strategy
(`escalate-system-prompt`) needs an attacker model, bound in `attackers` with a key in `.redteam/.env`.

`--follow` exits 0 when the run closes, 1 when the attempt failed (the record is at
`.redteam/runs/<run_id>/status.json`), 4 when the run is **stalled** -- the store says it is under
way and the platform says no runner is alive -- in which case `redteam run resume <run_id>`
relaunches it and it resumes from the difference.

## Down

```bash
redteam local down          # stops the containers; the MinIO volume stays, and with it every run
redteam local logs api -f
```

`down` never removes volumes. The store is the evidence; a stack brought down and up again keeps
every run it accepted, and a relaunch of any of them resumes rather than re-attacks.

## In containers, end to end

`tests/e2e/test_compose.py` (tier `docker`) brings the stack up from this checkout and drives it
through the command line: it needs a daemon and takes a few minutes the first time, while the
images build.

```bash
uv run pytest -m docker tests/e2e/test_compose.py
```
