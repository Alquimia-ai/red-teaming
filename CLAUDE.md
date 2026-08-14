# CLAUDE.md — Alquimia Red Teaming

Guidance for working in this repository. Read this before touching code.

## What this project is

AI **red teaming for Alquimia agents**: probe already-deployed Alquimia agents as
black boxes, find the *categories* of realistic interaction that make them violate
their behavioral contract **reproducibly**, and store every finding as **verifiable
evidence** in a Boltzmann brain.

The guiding principle comes from the brain itself: **"the brain returns evidence,
never prose."** A red-teaming result here is not an opinion — it is a graded outcome
with provenance, reproducible against an immutable snapshot.

## Two packages, one hard boundary

This is a **uv workspace** with two members that **never import each other**:

```
packages/redteam/     the deployable APP (k8s / OpenShift / Railway).
                      Probes agents, emits findings. Knows NOTHING about the brain.

packages/braintools/  LOCAL brain-curation tooling (wraps the vitruvio CLI).
                      Never deployed with the app.
```

**Why the split:** `redteam` ships as a container to a Kubernetes-style platform, so it
must stay light and free of brain/vitruvio code. `braintools` is a developer/pipeline
tool that runs where the brain lives. Keeping brain mechanics out of the app is a
**hard rule**, enforced structurally by the package boundary — see "Rules" below.

### They meet only at a data boundary

The app reads a **knowledge bundle** and writes a **findings artifact** through ports
(`redteam.ports`) with file-backed adapters. It does not know what is on the other
side. `braintools` is what sits on the other side, against the brain:

```
                     knowledge.json                       findings.json
   ┌────────────┐   (documents, cat.,   ┌───────────┐   (FailureReport,   ┌────────────┐
   │   brain    │──▶  contract)      ──▶ │  redteam  │──▶ RoastDataset)  ──▶│   brain    │
   │            │   braintools export    │   (app)   │   FileFindingsSink   │            │
   └────────────┘                        └───────────┘                      └────────────┘
        ▲ braintools ingest-findings ◀───────────────────────────────────────────┘
```

- **In**: `redteam.ports.FileKnowledgeSource` reads `knowledge.json` (a mounted volume
  / ConfigMap). Upstream, `braintools` produces it from the brain.
- **Out**: `redteam.ports.FileFindingsSink` writes `findings.json`. Downstream,
  `braintools ingest-findings` puts it back into the brain as evidence.

The boundary is **data**, never a code dependency. `catalogue` and `contract` cross it
as opaque JSON so the app doesn't couple to gaussia's schema either.

## The pieces (know where they live)

| Piece         | What it is                              | Where |
|---------------|-----------------------------------------|-------|
| **redteam**   | The deployable red-teaming app          | `packages/redteam/` |
| **braintools**| Brain-curation CLI (wraps vitruvio)     | `packages/braintools/` |
| **vitruvio**  | Boltzmann Brain runtime **CLI** (v0.3.x, third party) | https://github.com/getsfumato/vitruvio |
| **pyboltzmann** | Boltzmann Protocol **SDK** (Python)   | https://github.com/gaussia-labs/pyboltzmann |
| **gaussia / RoastMe** | Eval framework + adversarial search | `/Users/leonardoleenen/projects/gaussia/code/pygaussia` (branch `develop`) |
| **Alquimia agents** | Targets under test (HTTP API)     | `alquimia-core` / `alquimia-runtime` |

## Setup

```bash
uv sync                              # both packages (dev)
uv sync --extra roast                # + RoastMe (heavy: torch, sentence-transformers)

# vitruvio is used by braintools only. It is NOT on PyPI — install with the official
# script (fetches release wheels, does `uv tool install`, lands at ~/.local/bin):
#   curl -fsSL https://raw.githubusercontent.com/getsfumato/vitruvio/main/install.sh | sh
#   vitruvio --version   # expect 0.3.x
```

Python **3.13**, managed with **uv**. Do not use pip/poetry.

> Known gap: the `roast` extra points at gaussia's `roastme` extras, which the released
> `gaussia` on PyPI (1.0.0) does not expose — those live in the `pygaussia` `develop`
> branch. Resolve the source when implementing `roast` (install gaussia from that repo).

## The two CLIs

### `redteam` (the app) — `packages/redteam/`

```bash
uv run redteam check --knowledge ./data/knowledge.json   # validate input boundary
uv run redteam roast                                     # [roadmap] run RoastMe, emit findings
```

Env: `ALQUIMIA_AGENT_BASE_URL`, `ALQUIMIA_AGENT_TOKEN` (agent under test),
`REDTEAM_KNOWLEDGE_PATH` (in), `REDTEAM_FINDINGS_PATH` (out). No brain env exists here.

### `braintools` (curation) — `packages/braintools/`

```bash
uv run braintools init --actor curator --actor-kind human
uv run braintools ingest ./policy.pdf --proposer anthropic   # ONE file
uv run braintools index
uv run braintools search "refund policy" -n 5
uv run braintools browse
uv run braintools ingest-findings ./data/findings.json       # the boundary, brain side
```

Env: `BRAINTOOLS_BRAIN_DIR` (default `./brain`, → vitruvio's `--brain`),
`BRAINTOOLS_VITRUVIO_BIN`.

Every data command runs vitruvio with `--json` and parses its **envelope**
(`{"ok", "data", "warnings", "error", ...}`). vitruvio reports failures *inside* the
envelope (`ok: false`) while exiting 0, so success is decided by `ok`, not the exit
code: on `ok: false` the wrapper raises with `code: message` + `hint`; on success it
emits `data` and echoes `warnings` to stderr.

## Layout

```
red-teaming/
├── CLAUDE.md
├── pyproject.toml                 # uv workspace root (virtual; builds nothing)
├── packages/
│   ├── redteam/                   # the deployable app
│   │   ├── pyproject.toml         # alquimia-redteam; `roast`/`roast-rl` extras
│   │   ├── Dockerfile             # builds ONLY this package
│   │   └── src/redteam/
│   │       ├── cli.py             # check + roast
│   │       ├── ports.py           # KnowledgeSource / FindingsSink + file adapters
│   │       ├── targets.py         # TargetAssistant HTTP adapter (Alquimia agent)
│   │       └── config.py          # agent endpoint + boundary paths (NO brain)
│   └── braintools/                # brain-curation tooling
│       ├── pyproject.toml         # alquimia-braintools
│       └── src/braintools/
│           ├── cli.py             # brain commands + ingest-findings
│           ├── vitruvio.py        # subprocess wrapper over the vitruvio CLI
│           └── config.py          # brain dir + vitruvio bin
└── brain/                         # brain DATA (gitignored; `braintools init`)
```

## Rules

- **The app never touches the brain.** `packages/redteam/` must not import `braintools`,
  `pyboltzmann`, or reference vitruvio/brain paths. The only way in/out is
  `redteam.ports`. If you feel the urge to add brain logic to the app, you are on the
  wrong side of the boundary — put it in `braintools` and pass data across.
  Quick check:  `grep -rniE 'vitruvio|braintools|boltzmann' packages/redteam/src`
  should match only comments that say the app doesn't use them.
- **uv for everything**: `uv run redteam …`, `uv run braintools …`, `uv run pytest`,
  `uv run ruff check .`.
- **Evidence, not prose**: commands emit structured JSON. Human formatting is a
  presentation layer, never the source of truth.
- **vitruvio is the boundary to the brain** (inside braintools): all brain mutations go
  through the vitruvio CLI; surface its errors, don't swallow them.
- **Targets are black boxes**: the agent is reached only through `redteam.targets`.
  Config from env; never hardcode endpoints.
- **Contracts & catalogues are inputs, not constants.** RoastMe ships neither on
  purpose — a shipped one would become a standard nobody chose. They enter the app as
  part of the knowledge bundle.

## Testing

```bash
uv run pytest            # both packages; no brain, network, or vitruvio needed
uv run ruff check .
```

`braintools` tests drive the vitruvio wrapper against a fake subprocess runner.
`redteam` tests exercise the ports with temp files. End-to-end brain flows are verified
manually with a scratch brain.

## Safety & scope

This is **authorized defensive security work**: red teaming Alquimia's own agents to
find and document failures before release. RoastMe numbers are **judge-only
measurements** — one model's estimate of whether another misbehaved — so read a
violation rate as *evidence to look at*, never as a calibrated error rate.
