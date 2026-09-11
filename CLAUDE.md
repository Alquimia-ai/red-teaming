# CLAUDE.md

Red teaming for Alquimia assistants: generate adversarial probes anchored in a knowledge base,
conduct governed multi-turn conversations against a live assistant, record every conversation as
immutable evidence, and deliver the attack dataset, the weakness profile, the exploitation report
and a manifest that says exactly what was planned, what closed and what failed.

## Status

The repository is being built in phases, one pull request each. Landed so far: the foundations
(workspace, conventions, CI, guards, skills), the IO-free core -- `contracts`, `settings`,
`secrets`, `store` -- the model-facing packages -- `judges` (providers `openrouter` and
`openai_compatible`, the logprob grader), `knowledge` (read-only brain client), `target` (the
Alquimia runtime adapter and replay) -- generation: `catalogue` (bundles, the construction
registry, validation and publishing) and `probes` (one run's probe set, pulled brain, content
address) -- and conduction: `engine` (the governed door to the target with budget, pacing, retry
policy and safe mode; conversations an attacker steers inside one exchange; every conversation
recorded as one trace the instant it closes; closed units replayed on a relaunch; the weakness
profile and the exploitation report kept as control artifacts; the attack dataset per replica;
`attack` composing all of it for one run) -- and the first app: `dispatch` (one runner per run
through docker, a kubernetes Job or a local subprocess, each answering `status()`), `delivery`
(the bounded, idempotent webhook), `apps/runner` (`redteam-runner run <id>`: generation in
process, the attack, the manifest, the webhook; exit 1 on a failed attempt so the platform
relaunches) and `scripts/render_dockerfiles.py` (each app's Dockerfile from its workspace
closure) -- and the gate: `apps/api` (`POST /runs` validates, freezes and launches; `POST
/runs:validate` dry-runs the gate; `GET /runs/{id}` derives the phase from the store and the
liveness from the platform, and reports `stalled` when they disagree; `POST /runs/{id}:resume`
relaunches; `POST /catalogues` and `/catalogues:validate` publish and check bundles; `/priors`;
`GET /probes/{digest}`), with the in-process end-to-end (`tests/e2e/test_run_in_process.py`)
driving the API, the runner, the memory store and recorded answers in one process -- and the
operator's side: `apps/cli` (`redteam init | local up|down|status|logs | catalogue validate|publish
| prior publish | run validate|start [--follow]|status|result|list|resume | receiver export`, a
`.redteam/` workspace, the API as its only door) and `deploy/compose` (minio, the API, the seed, a
receiver that keeps what it acknowledges, a mock assistant speaking the runtime's inference API;
the runner created per run through the socket), with `tests/e2e/test_compose.py` (tier `docker`)
driving the containers through the command line -- and delivery: every push to `develop`
publishes `ghcr.io/alquimia-ai/red-teaming-{api,runner}` -- packages of this repository -- as
`develop` and `sha-<7>`; on `main`,
release-please opens one release pull request per app (`api`, `runner`, `cli`), tags
`<app>-vX.Y.Z`, publishes the images under the version and `latest`, and attaches the command
line as a zipapp per platform (`scripts/build_pyz.sh`). The command line is parsed with the
standard library and rendered with rich; it carries no click. Deployment charts and the final
documentation land next. Keep this file honest: describe what exists, mark what is planned.

## Repository structure

```
apps/            deployables: api (HTTP gate), runner (one process per run), cli (`redteam`)
packages/        libraries, import names `redteam_<name>`, distributions `red-teaming-<name>`
deploy/          compose (local), charts (Helm), catalog (model x hardware), cloud, appliance
docs/            adr/ (why), architecture/ (what), components/ (how), deploy/ (operate)
tests/guards/    tests that protect the architecture, not a feature
scripts/         repository tooling (ADR validator, Dockerfile renderer)
.claude/skills/  commit, pr, adr, catalogue
```

Packages and their allowed imports (`tests/guards/test_isolation.py` enforces the graph; a package
not in its table cannot be imported by anyone):

```
contracts, settings, secrets, delivery -> nothing
store -> contracts                          dispatch -> contracts, settings, secrets
knowledge -> contracts   (the only importer of pyboltzmann)
judges -> contracts      target -> contracts
catalogue -> contracts, store
probes -> contracts, store, catalogue, knowledge, judges       probes never imports target
engine -> contracts, store, catalogue, target, judges          engine never imports knowledge or probes
api -> contracts, settings, secrets, store, dispatch, catalogue
runner -> composes probes and engine (the only place both meet)
cli -> contracts
```

## Commands

```bash
uv sync --all-packages                                  # one environment for the workspace
uv run ruff check . && uv run ruff format --check .
uv run mypy packages apps tests
uv run pytest -q -m "not live and not docker and not k8s" # default tier, includes tests/guards
python3 scripts/validate_adrs.py                        # what CI runs on docs/adr
uv run python scripts/render_dockerfiles.py             # regenerate apps/*/Dockerfile (--check in CI)
uv run redteam-runner run <run_id> [--dry-run]          # one run, against the configured store
uv run redteam-api                                      # the gate on :8080
uv run pytest -q tests/e2e                              # the platform in one process
uv run redteam init && uv run redteam local up --build  # the local stack (docs/deploy/local.md)
uv run pytest -m docker tests/e2e/test_compose.py       # the stack in containers, via the cli
scripts/build_pyz.sh dist                               # the cli as one file: dist/redteam-<os>-<arch>.pyz
npm ci && pre-commit install --hook-type commit-msg      # commitlint on every commit
```

Test tiers: default (nothing needed) · `docker` (daemon) · `k8s` (cluster) · `live` (real
assistant or model provider; costs money).

## Invariants

- **The API never reaches the assistant or a model.** It validates, freezes, launches, reads.
- **The runner is one process per run.** Two runners on one run would attack the assistant twice;
  the platform's unique naming refuses the second.
- **Generation never reaches the assistant; conduction never reads the knowledge base.** Package
  boundary, guarded by imports. The runner is where they are composed.
- **The store is append-only.** Every key under `runs/{run_id}/` is written once, when the thing
  it records can no longer change. There is no `delete`, and no cache is rewritten in place.
- **Identity derives from content.** A probe's id from what built it; an attack's id from the
  probe and its parameters; the probe set's digest from the sorted set. Nothing in an identity
  depends on when it ran, or resumption silently repeats the whole run.
- **Never the same piece generates and judges.** The control judge that steers conduction is not
  the generator, and neither one is the assistant.
- **Models are configuration, never code.** Model ids arrive in the run spec by role; the code
  names providers, never models.
- **Credentials travel by reference.** A spec carries `secret_ref` names; the API resolves them
  and forwards only what the spec declared. Names starting with `REDTEAM_` are reserved.
- **A transport failure is a typed record, never a closed unit.** A failed exchange is recorded
  with its kind and retried or given up by policy; it is never graded as an answer.

## Vocabulary

Use these words, in this sense, everywhere -- code, docs, commits:

| Term | Meaning |
|---|---|
| **run** | One accepted request, frozen as `spec.json`, executed by one runner. |
| **catalogue** | A versioned bundle: `catalogue.json` (plugins and strategies) with its sidecars `contract.json`, `grounding.json`, `delivery.json`. |
| **plugin** | A risk family: what is tested, and which principle of the contract it charges. |
| **strategy** | How a probe is built: entity kind, construction (transform), documented or invented premise, phrasing. |
| **construction** | The code a strategy's `transform` key resolves to: deterministic (`swap_token`, `shift_figure`, `shift_date`) or model-driven (`contextual_sibling`). |
| **delivery** | How a probe reaches the assistant: one turn, or a conversation an attacker steers. |
| **contract** | The behavioural contract the assistant is held to: principles with weights and rubrics, plus verdict tokens. Travels inside the catalogue bundle. |
| **principle** | One rule of the contract, graded by the control judge. |
| **knowledge base** | The Boltzmann brain a run's probes are anchored in, pinned by OCI digest. Read-only. |
| **probe** | One generated query with its knowledge hook (documented or invented, and the block it cites). |
| **work unit** | One replica of one attack: the smallest thing that produces a complete trace. |
| **attack** | A probe with its attack parameters; `attack_id` is their hash. |
| **replica** | The n-th execution of an attack; the denominator of every count. |
| **trace** | The immutable record of one conducted conversation, all turns included. |
| **attacker** | The model that writes the follow-up turns of a conducted conversation. |
| **control judge** | The grader that scores exchanges inside the run to steer it; its output is a control artifact. |
| **profile** | The weakness profile the Profiler returns; persisted as `profile.json`. |
| **exploitation report** | The Exploiter's ranked categories and threshold queries; persisted as `exploit.json`. |
| **dataset** | The attack dataset assembled per replica from traces and control grades. |
| **manifest** | The single file that closes a run: digests, coverage (planned, closed, failed), components used. |
| **target** | The assistant under test, reached only through the governed door. |

## Conventions

- Commits: Conventional Commits with a mandatory scope (`commitlint.config.js`); use `/commit`.
  No attribution trailers of any kind. A `feat` bumps an app's minor version, a `fix` its patch;
  what a commit touches decides which apps it releases (`release-please-config.json`,
  `include-paths` held to the dependency closure by a guard).
- Pull requests target `develop`; use `/pr`. `main` receives promotions from `develop` only, and
  release-please runs there alone (`docs/release.md`).
- Decisions that cannot be inferred from code are ADRs (`/adr`); CI validates their shape.
- Python 3.12, `uv` for everything, ruff and mypy strict configured once at the root.
- Tests live beside their package (`packages/<name>/tests/`) or under `tests/` for cross-cutting
  tiers (`guards/`, `e2e/`, `live/`).

## Guards

| Guard | Protects |
|---|---|
| `tests/guards/test_vocabulary.py` | The repository's vocabulary: unrelated project names never appear in content or paths |
| `tests/guards/test_scopes.py` | Every workspace member has a commit scope |
| `tests/guards/test_isolation.py` | The import graph above; `pyboltzmann` is imported only by `knowledge` |
| `tests/guards/test_no_delete.py` | The store interface has no `delete` and nothing calls one |
| `tests/guards/test_no_hardcoded_models.py` | No model id or provider URL is bound in code; models arrive in the spec |
| `tests/guards/test_no_ambient_credentials.py` | The model-facing surface never reads the process environment |
| `tests/guards/test_no_status_literals.py` | No HTTP status is compared to a number; failures are classified by name |
| `tests/guards/test_inference_only.py` | The training stack is absent; the exploiter's search cannot train |
| `tests/guards/test_dockerfiles.py` | Every app's Dockerfile is exactly what its workspace closure renders to |
| `tests/guards/test_image_closure.py` | What an image carries is a property of the graph: the runner serves no HTTP; the API reaches no assistant, model or brain |
| `tests/guards/test_release_closure.py` | A component's `include-paths` are its dependency closure; the manifest and the pyprojects agree on versions |
| `packages/contracts/tests/test_plan_determinism.py` | Work-unit keys derive from the plan alone, across processes |

## Skills

| Skill | Use when |
|---|---|
| `/commit` | Changes are ready to be committed |
| `/pr` | A branch is ready for review against `develop` |
| `/adr` | A decision about the system was made |
| `/catalogue` | Authoring or fixing a catalogue bundle (plugins, strategies, contract, grounding, delivery) |
