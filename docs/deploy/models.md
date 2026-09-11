# The models

A run declares its models by role -- the control judge, the generator, the attackers, the embedder
-- and each `ModelSpec` says where it is served. The platform's code names no model; what serves
one is a deployment's choice, and there are two.

## Served on the cluster: `red-teaming-models`

`deploy/charts/red-teaming-models` runs one vLLM Deployment and Service per entry of its `models`
map, on the GPU, from weights on the node's disk (`modelsHostPath`, mounted at `/models`), offline
(`HF_HUB_OFFLINE`), behind an OpenAI-compatible endpoint on `:8000` that asks for `VLLM_API_KEY`
when `apiKeySecret` names a Secret. An entry names a path, what to serve it as, its task (`generate`
or `embed`), and how much of the card it may take.

`deploy/catalog/` supplies the entries and their fit: `models/*.yaml` add entries, `hardware/*.yaml`
size them for a card, and helm merges both because `models` is a map. See
[`../../deploy/catalog/README.md`](../../deploy/catalog/README.md).

A spec then points its roles at the cluster's endpoints:

```json
"judge":    {"model": "qwen3-8b", "provider": "openai_compatible",
             "endpoint": "http://judge.red-teaming.svc:8000/v1", "secret_ref": "VLLM_API_KEY", "self_hosted": true},
"embedder": {"model": "qwen3-embedding-0.6b", "provider": "openai_compatible",
             "endpoint": "http://embedder.red-teaming.svc:8000/v1/embeddings", "secret_ref": "VLLM_API_KEY", "self_hosted": true}
```

The judge needs usable logprobs, which vLLM exposes; the grader refuses to fall back to sampling,
so a serving path without them fails the run and says so rather than measuring something else.

## Hosted

A spec names `provider: openrouter` with a `secret_ref` into the runner Secret, and no chart is
needed. The manifest records the provider and the serving path either way, so two runs graded
through different paths are never compared by accident.

## Sharing one card

Two pods requesting `nvidia.com/gpu: 1` on a node with one card need the device plugin configured
to share it (time-slicing) or a card that partitions (MIG). The hardware overlays size the two
models to fit together in memory; sharing the allocation is the node's configuration.
