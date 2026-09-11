# ADR-008: Helm charts with SOPS secrets and vLLM served models for the appliance

**Status:** Accepted
**Date:** 2026-09-11
**Tags:** deploy, dispatch, settings

## Context

The platform has to run in three places with one set of images: a workstation, an appliance -- one
machine with an NVIDIA GPU, no egress worth relying on, operated by someone who is not the platform's
author -- and a managed cluster. The runner is one process per run and the platform's coordination
is the platform's: on Kubernetes that is a Job, created by the API with the run's credentials by
reference. The models a run declares -- a control judge that needs logprobs, a generator, attackers,
an embedder -- have to be served on the appliance's card and reached at a stable address.

The appliance's operator commits configuration to this repository and has to be able to rotate a
credential without a plain-text secret ever landing in it.

## Decision Drivers

- One deployment description for the appliance and the clouds, differing by values only.
- Nothing in plain text that is a credential is ever committed; rotation is an edit and a push.
- The appliance installs and upgrades with one idempotent command.
- The evidence survives an upgrade and an uninstall.
- Which model plays which role stays the run's decision; the deployment only serves models.

## Considered Options

### Option A: Raw manifests per environment — Rejected

A directory of Kubernetes manifests for the appliance and another per cloud.

**Pros:** nothing to learn beyond `kubectl`.

**Cons:** three copies of the same topology; a fix to the runner's Job wiring has to land three
times; secrets are either committed in plain text or kept out of the repository and out of review.

### Option B: Helm charts, SOPS with age, vLLM on the card — Chosen

Two charts: `red-teaming-stack` installs the API, its RBAC, the two service accounts, the wiring
the API stamps on every Job it creates, MinIO on the appliance or nothing in the cloud, and a seed
hook; `red-teaming-models` installs one vLLM Deployment and Service per model entry, from weights on
the node's disk, offline, with the catalog under `deploy/catalog/` composing models and hardware
through helm's map merge. Secrets on the appliance are committed encrypted with SOPS for the
operator's age key and decrypted on the appliance by `install.sh`, which also installs k3s and the
NVIDIA device plugin and runs both charts idempotently. The API is a NodePort on the appliance and
an Ingress in the cloud. The MinIO claim is kept across uninstall.

**Pros:** one chart, values per environment; encrypted secrets under review; one install command;
the store outlives the release; the models chart knows no role.

**Cons:** Helm and SOPS are two tools the operator has to have; the seed is copied into the chart
because a chart reads only its own files (a guard holds the copy to the source); vLLM's memory
sharing on one card depends on the node's device-plugin configuration.

### Option C: A Kubernetes operator — Rejected

A controller reconciling a `RedTeamingPlatform` resource.

**Pros:** upgrades and drift handled by the cluster.

**Cons:** a controller to write, test and operate for a platform whose state is one object store;
the appliance's operator would debug a reconciler where a chart is readable.

## Decision

Adopt Option B. Two Helm charts with values per environment, secrets committed encrypted with SOPS
and age, models served by vLLM from the node's disk and composed from a catalog, one idempotent
install script for the appliance, and a store volume that outlives the release.

## Consequences

### Positive

- The Job the API creates on the appliance is the Job it creates on EKS; only the store's identity
  and the API's exposure differ, and both are values.
- A rotated credential is a commit a reviewer can see without seeing the value.
- `helm lint`, `helm template` with every values file and a guard over the rendered objects run in
  CI, so the wiring the dispatcher expects cannot drift from what the chart tells the API.
- The models chart serves whatever the catalog names; a new model is a values file and weights on
  disk, never a code change.

### Negative / Trade-offs

- The seed lives twice: in `deploy/seed` and copied into the chart's `files/`, held equal by a
  guard.
- Two pods sharing one GPU need node configuration the chart cannot make.
- A private repository's packages need a pull secret on every cluster, managed like the others.

## Implementation Notes

- `deploy/charts/red-teaming-stack`: `templates/{api,rbac,serviceaccounts,configmaps,secrets,minio,seed,receiver}.yaml`, `files/seed/`.
- `deploy/charts/red-teaming-models`: `templates/models.yaml` over `models: {name: entry}`.
- `deploy/catalog/models/*.yaml`, `deploy/catalog/hardware/*.yaml`, composed with `-f`.
- `deploy/appliance/{install.sh,values-appliance.yaml,values-models-appliance.yaml,.sops.yaml,secrets/}`.
- `deploy/cloud/{values-eks.yaml,values-gke.yaml}`.
- `redteam_settings`: `k8s_store_secret`, `k8s_image_pull_secret`; `K8sJobDispatcher` sets `envFrom`
  and `imagePullSecrets` on the Job from them.
- Guards: `tests/guards/test_charts.py`.

## Related ADRs

- Builds on [ADR-002](./002-stateless-api-and-one-runner-per-run.md)
- Builds on [ADR-004](./004-models-are-configuration-and-one-governed-door-to-the-target.md)
