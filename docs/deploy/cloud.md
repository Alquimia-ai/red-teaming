# A managed cluster

The chart is the appliance's; the values change what a cloud does differently. `deploy/cloud/`
carries one file per provider tried and a README with the commands.

| | Appliance | EKS | GKE |
|---|---|---|---|
| Store | MinIO in the cluster | S3 | Cloud Storage via `storage.googleapis.com` (S3-compatible) |
| Store credential | the chart's Secret | none: IRSA on both service accounts | HMAC key pair in `red-teaming-store-creds` |
| API exposure | NodePort 30880 | ClusterIP + ALB ingress | ClusterIP + GCE internal ingress |
| Pull | `red-teaming-registry` | same | same |
| Models | vLLM on the card | hosted (`openrouter`), or the models chart on a GPU node group | same |

The store speaks S3 and nothing else, on purpose: one adapter, one conditional-write check at
startup (`S3ObjectStore.verify()`), and every provider tried honours `If-None-Match: *`.

A run on a managed cluster is the same Job as on the appliance. What the pod reaches the store with
is the platform's identity when the values annotate the service accounts, and a key otherwise; what
it reaches the assistant and the models with is always the run's own references into
`red-teaming-runner-secrets`.
