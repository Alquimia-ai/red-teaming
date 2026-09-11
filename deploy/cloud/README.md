# A managed cluster

The same chart as the appliance, with what a cloud changes: the store is the provider's, the API
sits behind an ingress, identities come from the platform rather than from keys, and the models are
either hosted (`provider: openrouter`) or served by the models chart on a GPU node group.

| | EKS (`values-eks.yaml`) | GKE (`values-gke.yaml`) |
|---|---|---|
| Store | S3, no key: IRSA on both service accounts | Cloud Storage through `storage.googleapis.com` with HMAC keys in `red-teaming-store-creds` |
| API | ClusterIP behind an ALB ingress | ClusterIP behind a GCE internal ingress |
| Pull | `red-teaming-registry` (ghcr.io) | `red-teaming-registry` (ghcr.io) |
| Runs' secrets | `red-teaming-runner-secrets`, managed out of band | same |

```bash
kubectl create namespace red-teaming
kubectl -n red-teaming create secret docker-registry red-teaming-registry \
  --docker-server=ghcr.io --docker-username=<user> --docker-password=<token with read:packages>
kubectl -n red-teaming create secret generic red-teaming-runner-secrets \
  --from-literal=OPENROUTER_API_KEY=... --from-literal=TARGET_KEY=...
helm upgrade --install red-teaming deploy/charts/red-teaming-stack \
  --namespace red-teaming -f deploy/cloud/values-eks.yaml --wait
```

## Models

Hosted: a spec names `provider: openrouter` with `secret_ref: OPENROUTER_API_KEY` for the judge,
the generator and the attackers, and an embeddings endpoint for the embedder. Nothing to deploy.

Self-hosted: a GPU node group (an `nvidia.com/gpu` capacity and the NVIDIA device plugin), the
weights on a volume the models chart mounts -- set `modelsHostPath` to where the node group's image
places them, or replace the `hostPath` volume with a PVC in an overlay -- and the chart with the
catalog:

```bash
helm upgrade --install red-teaming-models deploy/charts/red-teaming-models --namespace red-teaming \
  -f deploy/catalog/models/qwen3-8b.yaml -f deploy/catalog/hardware/l40s-48g.yaml \
  --set apiKeySecret=red-teaming-runner-secrets
```

## Runs

The API creates one Job per run in its namespace; the runner's pod carries the runner service
account, whose platform identity is what reaches the store. A run's own credentials -- the target's
token, a model's key -- are `secretKeyRef`s into `red-teaming-runner-secrets`, one per reference the
spec declared; the Job's spec shows the key names and never a value.
