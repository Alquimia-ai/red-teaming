# The appliance

The shape this platform is built to run in first: one machine with an NVIDIA GPU, k3s, the models
served by vLLM on the card, MinIO on the disk, the API on a NodePort, and the assistant under test
elsewhere on the network. `deploy/appliance/README.md` is the operator's runbook; this page is the
reasoning behind it.

## Decisions

- **k3s, single node.** The platform needs Jobs, Secrets, ConfigMaps and a Service -- a full
  distribution buys nothing here, and k3s installs in one command and runs on one machine.
- **Helm, not raw manifests.** The same chart serves the appliance and a managed cluster with
  values files; raw manifests would be two copies to keep in step.
- **SOPS with age for the secrets.** The runs' credentials and the registry pull secret are
  committed encrypted (`deploy/appliance/secrets/*.enc.yaml`), decrypted on the appliance by the
  operator's key, applied by the install script. A reviewer sees which Secret changed, never what it
  holds; nothing in plain text is ever committed.
- **NodePort, no ingress controller.** One node, one address: `http://<ip>:30880`. An ingress
  controller would be one more thing to run for one more hop.
- **vLLM on the card.** OpenAI-compatible, exposes logprobs -- which the control judge requires --
  and starts from weights on disk with no egress. Which model plays which role stays the run
  spec's decision; the chart serves what the catalog names.
- **The MinIO volume outlives everything.** `helm.sh/resource-policy: keep` on the claim: the store
  is the evidence, and an upgrade or an uninstall must not be able to take it.

## What the operator does

```bash
sudo deploy/appliance/install.sh          # idempotent: k3s, device plugin, secrets, models, platform
redteam init --api-url http://<ip>:30880
```

See [`../../deploy/appliance/README.md`](../../deploy/appliance/README.md) for prerequisites, the
secrets, the weights and day-two operation, and [`models.md`](models.md) for what the card serves.
