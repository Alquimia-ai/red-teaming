# The API

`redteam_api`, a FastAPI application served by uvicorn on `:8080`. It validates, freezes, launches,
publishes and reads -- and does no work. It never reaches the assistant or a model; it does carry
the catalogue package so a bundle is validated and published synchronously.

## Routes

| Route | Answer |
|---|---|
| `GET /healthz` | `{"status": "ok"}` |
| `POST /runs` | 202 `{run_id, result_location, catalogue_versions, launched}`; 400 refused with the reason; 409 a different request under a frozen id, naming the fields; 422 catalogues that disagree on the contract; 503 the platform refused to launch or the store is not what publishing left it |
| `POST /runs:validate` | 200 `{run_id, catalogue_versions, contract_digest, secret_refs}`, nothing written |
| `GET /runs` | `{"runs": [ids]}` |
| `GET /runs/{id}` | `{run_id, phase, runner, stalled, planned, closed, failed, pending}`; 404 unknown |
| `GET /runs/{id}/result` | the manifest; 404 until the run closed |
| `POST /runs/{id}:resume` | 202 `{run_id, launched, runner}`; 409 already closed |
| `POST /catalogues` | 201 published `{name, version, key, digest, contract_digest, principles, delivered, created}`; 200 already the newest version; 400 malformed file; 422 a failed check |
| `POST /catalogues:validate` | 200 `{name, principles, strategies, needs_base, delivered}`, nothing written |
| `GET /catalogues` | `{name: [versions]}` |
| `POST /priors`, `GET /priors` | a natural-query prior published (201/200), and every prior's versions |
| `GET /probes/{digest}` | one probe set, by content |

The OpenAPI document is at `/docs` and `/openapi.json`.

## Modules

- `main.py`: the routes, the retry comparison (`_fields_that_differ`), the launch.
- `validation.py`: the gate, pure over data; what has to be read from the store is read by the
  wiring and handed in.
- `status.py`: the phase from the store's keys, the platform's liveness beside it, `stalled` when
  they disagree.
- `deps.py`: the wiring -- store, resolver, dispatcher with the runner's environment, which
  references travel, the effective selection at frozen versions, the shared contract.

## Configuration

`REDTEAM_*` only ([`redteam_settings`](../architecture/packages.md)): `STORE_BACKEND` and `S3_*`,
`DISPATCH_BACKEND` with `RUNNER_IMAGE`, `DOCKER_NETWORK` or the `K8S_*` knobs, `SECRETS_BACKEND`
with `SECRETS_ROOT`, `BRAIN_REGISTRY_*`. On docker and the subprocess the API resolves a run's
references itself and refuses one it cannot; on a cluster it hands the references to the platform's
Secret and refuses nothing it cannot see.
