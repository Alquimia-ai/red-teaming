# Get started

One machine, four steps: install the command line, serve the judge, bring the platform up, run an
attack. Everything below was run end to end on a DGX Spark (GB10, Ubuntu 24.04, arm64); the only
step that depends on the hardware is the judge.

```
redteam CLI ──▶ API :8080 ──▶ runner (one container per run) ──▶ mock assistant :8082
                   │                      │
                   └──▶ MinIO :9000       └──▶ judge model :8000 (vLLM)
```

## What the machine needs

| | |
|---|---|
| Linux | x86_64 or arm64 |
| Python 3.12 | on the `PATH` -- the command line is a zipapp that runs on it |
| Docker | with compose, and the user in the `docker` group |
| A GPU | only for step 2; without one, a run can grade with the stand-in judge |

## 1. The command line

```bash
curl -fsSL https://raw.githubusercontent.com/Alquimia-ai/red-teaming/main/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"     # add it to ~/.profile to keep it
redteam --version
```

It resolves the newest `cli-v*` release, checks the download against the checksum the release
published, and installs one file in `~/.local/bin`. Later, `redteam update` replaces it in place
and `redteam update --check` says whether there is anything newer.

## 2. The judge

The judge grades every exchange inside a run, so it is the one model the platform cannot do
without. Any server speaking the OpenAI API will do. On a DGX Spark, this is
[NVIDIA Nemotron 3.5 Lightning](https://recipes.vllm.ai/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16?hardware=dgx_spark_gb10)
with the recipe's GB10 settings:

```bash
docker run -d --name nemotron --restart unless-stopped \
  --gpus all --ipc=host -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:v0.28.0 \
  --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16 \
  --served-model-name nemotron-3.5-lightning \
  --mamba-backend flashinfer --mamba-cache-mode align \
  --enable-prefix-caching --max-num-batched-tokens 16384 \
  --moe-backend flashinfer_cutlass \
  --gpu-memory-utilization 0.7 \
  --reasoning-parser nemotron_v3
```

The first start downloads ~60 GB of weights. Watch it with `docker logs -f nemotron`, and know it
is ready when the model answers:

```bash
curl -s localhost:8000/v1/models | head -c 200
```

The recipe also lists `VLLM_USE_FASTOKENS=1` for this checkpoint. Leave it out on
`vllm/vllm-openai:v0.28.0`: the image carries no `fastokens` package, and vLLM exits on start with
`ImportError: The 'fastokens' package (>= 0.2.0) is required` -- with `--restart unless-stopped`,
that is a container restarting forever. It is a tokenizer optimisation, not correctness.

Three flags are the GB10's, not decoration: `--gpu-memory-utilization 0.7` leaves the host its
share of the 128 GB the CPU and the GPU share, `--mamba-cache-mode align` is what the recipe
measured, and `--moe-backend flashinfer_cutlass` is the BF16 checkpoint's MoE path. The BF16
checkpoint needs 72 GB; if you would rather spend 18 GB, serve the NVFP4 variant
(`...-30B-A3B-NVFP4`, add `--kv-cache-dtype fp8 --moe-backend marlin`).

## 3. The platform

```bash
redteam init                      # .redteam/ here: config.json, .env (0600), catalogues/, runs/
redteam local up                  # minio, api, seed, receiver, mock assistant
redteam local status
```

| Service | Where | What it is |
|---|---|---|
| `api` | http://localhost:8080 | the gate: accepts a run, freezes it, launches one runner |
| `minio` | http://localhost:9000 (console `:9001`) | the store: every probe, trace and manifest |
| `mock-target` | http://localhost:8082 | an assistant that misbehaves on purpose |
| `receiver` | http://localhost:8083 | keeps every webhook the platform delivered |

The runner is not a service: the API creates one container per run through the Docker socket, the
same lifecycle it uses for a Kubernetes Job.

## 4. A run

`spec.json` -- the mock assistant as the target, the model from step 2 as the judge:

```json
{
  "run_id": "redteam-run-001",
  "catalogues": ["assistant-baseline"],
  "plugins": [],
  "strategies": ["ask-identity", "ask-system-prompt", "act-for-another", "refuse-escalation"],
  "connector": {
    "kind": "alquimia",
    "endpoint": "http://mock-target:8080",
    "secret_ref": "TARGET_KEY",
    "options": {"assistant_id": "mock"}
  },
  "judge": {
    "model": "nemotron-3.5-lightning",
    "provider": "openai_compatible",
    "endpoint": "http://<this machine's IP>:8000/v1",
    "self_hosted": true
  },
  "context": {"language": "en", "domain": "an assistant under test"},
  "replicas": 2,
  "webhook_url": "http://receiver:8080/hook"
}
```

```bash
redteam run validate spec.json            # the gate alone; writes nothing
redteam run start spec.json --follow      # accept, freeze, launch, poll until it closes
redteam run result redteam-run-001        # the manifest
```

Two addresses, two readers: `endpoint` under `connector` and `webhook_url` are read by containers
on the stack's network, so they use service names; the judge's `endpoint` is read by the runner
container and points at the host, so it takes the machine's IP -- `localhost` there would be the
runner itself.

`"self_hosted": true` is what says this server is yours. Without it the gate refuses the run --
*"judge names provider 'openai_compatible' with no secret reference"* -- because a **hosted**
provider must carry the credential its spec declared rather than whatever the process happens to
hold. A server on your own network answers whoever reaches it, and the flag is also what the
manifest records as the judge's serving path.

`--follow` exits 0 when the run closes, 1 when it failed, 4 when it is stalled (`redteam run
resume <id>` relaunches it and it resumes from the difference), 5 on the deadline.

Give `--deadline` room when the judge reasons. Nemotron spends a few hundred tokens thinking
before each verdict, which puts a ten-unit run at roughly half an hour on one GB10 -- past the
default 1800s. The deadline only stops the watching: the runner keeps going, `redteam run status
<id>` picks the count back up, and the run closes on its own.

### When the judge reasons

The judge grades by reading the logprobs of a verdict token, and a reasoning model spends tokens
before it gets there. The default headroom is 4096; past it the verdict is truncated, retried, and
then **recorded as ungraded** -- the platform refuses to invent a grade it could not read. In the
manifest that shows up as `profile_n_ungraded` above zero with everything else healthy.

Nemotron reasons hard on the exchanges that are hardest to judge, so give it room:

```json
  "judge": {
    "model": "nemotron-3.5-lightning",
    "provider": "openai_compatible",
    "endpoint": "http://<this machine's IP>:8000/v1",
    "self_hosted": true,
    "reasoning_budget": 16384
  },
```

## What you get

```bash
redteam run result redteam-run-001        # coverage: planned, closed, failed
redteam receiver export redteam-run-001   # what the webhook was delivered
ls .redteam/runs/redteam-run-001/         # accepted.json, status.json, manifest.json
```

The manifest is what closes a run: digests, coverage per plugin and per strategy, and every
component it used. The store keeps the rest -- every probe, every conversation, every grade --
under `runs/<run_id>/` in MinIO, written once and never rewritten.

## When something is wrong

| Symptom | What it is |
|---|---|
| `redteam local up` cannot pull `ghcr.io/alquimia-ai/...` | the packages are public, so a refusal is a stale credential: `docker logout ghcr.io`, or log in again with a token that has `read:packages` |
| the run is `stalled` | the store says it is under way, the platform says no runner is alive: `redteam run resume <id>` |
| the judge 404s on `/v1/models` | vLLM is still loading weights; `docker logs -f nemotron` |
| vLLM exits on start | lower `--gpu-memory-utilization`, or serve the NVFP4 variant |
| the judge container says `Restarting` forever | read `docker logs nemotron`: a flag or an environment variable the image does not support exits before the server ever binds |
| `redteam` is not found | `~/.local/bin` is not on the `PATH` |

## Next

- [`docs/deploy/local.md`](deploy/local.md) -- the local stack in full
- [`docs/deploy/appliance.md`](deploy/appliance.md) -- k3s, SOPS and vLLM on one appliance
- [`docs/components/cli.md`](components/cli.md) -- every command
- [`docs/architecture/run.md`](architecture/run.md) -- what a run actually does
