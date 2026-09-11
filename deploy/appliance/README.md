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

## Install

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

Pin the images on an appliance (`values-appliance.yaml`, `images.api`/`images.runner`) to a
release; `latest` is for a lab.

## Then

```bash
redteam init --api-url http://<appliance-ip>:30880
redteam catalogue list                 # what the seed published
redteam run start spec.json --follow
```

A spec on the appliance points its roles at the cluster's own endpoints:

```json
"judge":    {"model": "qwen3-8b", "provider": "openai_compatible", "endpoint": "http://judge.red-teaming.svc:8000/v1", "secret_ref": "VLLM_API_KEY", "self_hosted": true},
"embedder": {"model": "qwen3-embedding-0.6b", "provider": "openai_compatible", "endpoint": "http://embedder.red-teaming.svc:8000/v1/embeddings", "secret_ref": "VLLM_API_KEY", "self_hosted": true}
```

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
