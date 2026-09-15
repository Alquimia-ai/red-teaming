# The appliance

One machine: an NVIDIA GPU, k3s, the models served by vLLM on the card, MinIO on the disk, the API
on a NodePort. The assistant under test is elsewhere -- an Alquimia runtime the appliance reaches
over the network -- and so, when a run declares one, is the brain registry.

```
                 ┌──────────────────────── appliance (k3s) ─────────────────────────┐
 redteam CLI ───▶│ :30880 api ──creates──▶ Job redteam-run-<id> (runner)              │
                 │                            │        │            │                │
                 │   minio (PVC) ◀── evidence ┘        │            └──▶ vLLM judge   │──▶ assistant
                 │                                     └──▶ vLLM embedder             │   (external)
                 └───────────────────────────────────────────────────────────────────┘
```

## What the host needs

| | |
|---|---|
| OS | any systemd Linux the NVIDIA driver supports; RHEL AI and Ubuntu LTS are what has been tried |
| GPU | one card; see `deploy/catalog/hardware/` for what fits where |
| Driver + toolkit | the NVIDIA driver and the NVIDIA container toolkit, so k3s's containerd has the `nvidia` runtime |
| Tools | `kubectl`, `helm`, `sops`, `age` (the install script checks) |
| Disk | the model weights under `/var/lib/red-teaming/models/<name>` (see `deploy/catalog/README.md`), and room for MinIO's volume (`local-path`, 100 GB by default) |
| Network in | 30880 (API), 30901 (MinIO console) from operators' workstations |
| Network out | the assistant under test; the brain registry when runs declare a knowledge base; `ghcr.io` to pull the packages unless they were loaded from media |

## 1. Install the platform

```bash
git clone https://github.com/Alquimia-ai/red-teaming && cd red-teaming
# 1. the operator's age key, and the secrets encrypted for it -- see secrets/README.md
# 2. the weights on disk -- see ../catalog/README.md
sudo deploy/appliance/install.sh
```

The script installs k3s if it is absent, applies the NVIDIA device plugin and the `nvidia` runtime
class, creates the namespace, decrypts and applies every `secrets/*.enc.yaml`, installs the models
chart with the catalog entries `MODELS` names on the hardware `HARDWARE` names, and installs the
platform chart. Run it again for an upgrade: every step is idempotent, and the MinIO volume is kept
(`helm.sh/resource-policy: keep`) even across `helm uninstall`.

`values-appliance.yaml` pins `images.api` and `images.runner` to a release. Keep it that way: an
appliance is upgraded on purpose, and `latest` is for a lab.

## 2. Install the command line

On the workstation that drives the appliance -- or on the node itself; it needs Python 3.12 and
nothing else:

```bash
curl -fsSL https://raw.githubusercontent.com/Alquimia-ai/red-teaming/main/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
redteam --version                                  # later: redteam update [--check]
redteam init --api-url http://<appliance-ip>:30880
```

The installer resolves the newest `cli-v*` release, checks the download against the checksum the
release published, and installs one file. Keep it within a minor of the API it talks to: the gate
refuses a spec it does not understand rather than guessing.

## 3. Publish a catalogue

**The appliance starts empty.** The chart carries no catalogue and runs no seed hook (ADR-014): a
production installation publishes its own engagement, and nothing business-shaped is implied by an
install. A catalogue is one schema-version-2 document -- the contract, the plugins and the
strategies, each declaring `requires_brain` and one interaction mode:

```bash
redteam catalogue validate my-catalogue.yaml       # every check publishing runs; writes nothing
redteam catalogue publish my-catalogue.yaml        # the next version, by the name inside it
redteam catalogue list                             # what this appliance has
redteam prior publish general-support prior.json   # only if a run names `realism_prior`
```

`deploy/seed/catalogues/*.json` are the local stack's fixtures and read as a worked example;
[`docs/architecture/catalogue.md`](../../docs/architecture/catalogue.md) is the grammar, and the
`/catalogue` skill authors one.

## 4. A run

A spec on the appliance points its roles at the cluster's own endpoints:

```json
"judge":    {"model": "qwen3-8b", "provider": "openai_compatible", "endpoint": "http://judge.red-teaming.svc:8000/v1", "secret_ref": "VLLM_API_KEY", "self_hosted": true},
"embedder": {"model": "qwen3-embedding-0.6b", "provider": "openai_compatible", "endpoint": "http://embedder.red-teaming.svc:8000/v1/embeddings", "secret_ref": "VLLM_API_KEY", "self_hosted": true},
"brain":    {"registry": "registry.example.com", "repository": "brains/support", "digest": "sha256:<64 hex>"}
```

```bash
redteam run start spec.json --follow
redteam run result <run_id>
```

`brain` is the whole reference, pinned by digest -- there is no `kb_ref` any more. Leave it out for
a run whose selected strategies all stand on their own; a run that selects one declaring
`requires_brain` without it is refused at the gate. When it is present, the runner pulls once and
hands the brain only to the strategies that asked for it, which is why a mixed catalogue no longer
has to choose.

## Upgrading

```bash
git pull                                           # the charts and the values live here
$EDITOR deploy/appliance/values-appliance.yaml     # images.api and images.runner -> the new release
sudo deploy/appliance/install.sh                   # both charts, idempotent
redteam update                                     # the command line, on the workstation
```

Published catalogues, priors and every run's evidence are in MinIO and survive all of it. Two things
a release can refuse afterwards, both on purpose: a catalogue document without `schema_version: 2`,
and an unfinished run frozen before the upgrade -- start it again under a new id rather than
resuming it across a breaking change.

## Operating

```bash
kubectl -n red-teaming get pods                                   # api, minio, judge, embedder
kubectl -n red-teaming get jobs -l app.kubernetes.io/name=red-teaming-runner
kubectl -n red-teaming logs job/redteam-run-<id>                  # a runner's log
kubectl -n red-teaming logs deploy/judge                          # vLLM
```

A run's Job is kept for a day after it finishes (`runner.ttlSecondsAfterFinished`), which is how a
runner that died can be read. The API reports such a run as `stalled` when the Job is gone and the
store still says the attack was under way; `redteam run resume <id>` creates a new Job that picks
the run up where the store left it.
