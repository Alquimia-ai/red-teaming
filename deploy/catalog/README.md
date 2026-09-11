# Model and hardware catalog

Values for the `red-teaming-models` chart, split along the two things that vary independently:
**which models** a deployment serves, and **what GPU** it serves them on. A deployment composes
one of each:

```bash
helm upgrade --install red-teaming-models deploy/charts/red-teaming-models \
  --namespace red-teaming --create-namespace \
  -f deploy/catalog/models/qwen3-8b.yaml \
  -f deploy/catalog/models/qwen3-embedding-0.6b.yaml \
  -f deploy/catalog/hardware/l40s-48g.yaml
```

`models/` files each add one entry to the chart's `models` map -- the model's path under the
node's model directory, what it is served as, its task. `hardware/` files touch nothing but the
memory each entry may take (`gpuMemoryUtilization`) and the context it may hold (`maxModelLen`),
so two models fit one card. Helm merges maps, so the files compose; a list would not.

| Model | Role in a run | Files |
|---|---|---|
| `Qwen3-8B` | control judge, generator, attackers | `models/qwen3-8b.yaml` |
| `Qwen3-Embedding-0.6B` | embedder for the realism estimate | `models/qwen3-embedding-0.6b.yaml` |

| Hardware | Memory | Fit |
|---|---|---|
| `hardware/ascent-gx10.yaml` | 128 GB unified | both models, generously |
| `hardware/l40s-48g.yaml` | 48 GB | both models: judge at 0.55, embedder at 0.10 |
| `hardware/rtx-24g.yaml` | 24 GB | both models, tightly: judge at 0.70 with a 4k context, embedder at 0.12 |

The catalog says nothing about which model a run uses for which role. That is the run spec's, per
run, and the platform's code names no model at all: a spec points at
`http://judge.red-teaming.svc:8000/v1` with `provider: openai_compatible` and the served model's
name, and the manifest records exactly that.

## Adding a model

1. Put the weights on every GPU node under the chart's `modelsHostPath`
   (`/var/lib/red-teaming/models/<name>`), downloaded once with a machine that has egress:
   `huggingface-cli download Qwen/Qwen3-8B --local-dir /var/lib/red-teaming/models/qwen3-8b`.
2. Add `models/<name>.yaml` with the entry.
3. Add its fit to each `hardware/*.yaml` it is expected to run on.

Weights are not in this repository and never will be: they are gigabytes, they have licences of
their own, and the appliance's install copies them from media rather than from the network.
