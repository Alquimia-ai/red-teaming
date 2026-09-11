# Operating the platform

| Where | Document | Shape |
|---|---|---|
| A workstation | [`local.md`](local.md) | docker compose: MinIO, the API launching a runner container per run, a seed, a receiver, a mock assistant |
| Any cluster | [`kubernetes.md`](kubernetes.md) | the `red-teaming-stack` chart: what it installs and how a run becomes a Job |
| The appliance | [`appliance.md`](appliance.md) | one node with a GPU: k3s, SOPS/age, the models on the card, the API on a NodePort |
| A managed cluster | [`cloud.md`](cloud.md) | EKS and GKE values: the provider's store, an ingress, platform identities |
| The models | [`models.md`](models.md) | the `red-teaming-models` chart, the catalog of models and hardware, hosted alternatives |

Releases -- images and the command line -- are in [`../release.md`](../release.md).
