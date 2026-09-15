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
- **Nothing business-shaped ships with the platform.** The chart carries no catalogue and runs no
  seed ([ADR-014](../adr/014-catalogues-embed-strategy-execution-and-brain-requirements.md)): an
  installation publishes its own engagement. A contract that arrived with an install is a contract
  nobody agreed to, and it would read in the manifest exactly like one somebody did.
- **Pinned images, deliberate upgrades.** `values-appliance.yaml` names a release for both the API
  and the runner. `latest` would move an appliance under a run that was frozen against what was
  there yesterday.
- **The command line is not installed from this checkout.** It comes from its own `cli-v*` release,
  by `curl ... | sh`, and updates in place
  ([ADR-013](../adr/013-the-command-line-is-released-installed-and-updated-as-one-file.md)): the
  operators who drive an appliance are not the people who clone it.

## What the operator does

```bash
sudo deploy/appliance/install.sh          # idempotent: k3s, device plugin, secrets, models, platform
curl -fsSL https://raw.githubusercontent.com/Alquimia-ai/red-teaming/main/install.sh | sh
redteam init --api-url http://<ip>:30880
redteam catalogue publish my-catalogue.yaml   # the engagement; the appliance starts with none
```

See [`../../deploy/appliance/README.md`](../../deploy/appliance/README.md) for prerequisites, the
secrets, the weights and day-two operation, and [`models.md`](models.md) for what the card serves.
