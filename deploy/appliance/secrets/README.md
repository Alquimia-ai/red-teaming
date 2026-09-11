# Secrets on the appliance

Three Secrets, encrypted with [SOPS](https://github.com/getsops/sops) and
[age](https://github.com/FiloSottile/age), committed as `*.enc.yaml`, decrypted by `install.sh` on
the appliance and applied with `kubectl`. Nothing in plain text is ever committed; the `*.example.yaml`
files beside them are the shapes to fill in.

| Secret | Holds | Read by |
|---|---|---|
| `red-teaming-runner-secrets` | every key a run may name by reference: `TARGET_KEY`, `VLLM_API_KEY`, `OPENROUTER_API_KEY`, `ALQUIMIA_API_TOKEN`, `BRAIN_REGISTRY_CREDENTIALS` | each runner Job, one `secretKeyRef` per reference the run declared; the models chart, for the endpoints' key |
| `red-teaming-store-creds` | `REDTEAM_S3_ACCESS_KEY`, `REDTEAM_S3_SECRET_KEY` (and MinIO's own `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`) | the API, every runner Job, MinIO -- created by the chart when `minio.enabled`; encrypt one here only to override the chart's |
| `red-teaming-registry` | a `kubernetes.io/dockerconfigjson` for `ghcr.io` | the API's and the runner's service accounts, to pull the packages |

## First time

```bash
age-keygen -o /root/.config/sops/age/keys.txt        # on the appliance; keep the public key
# put the public key in ../.sops.yaml, then from a workstation that has the same key:
cp runner-secrets.example.yaml runner-secrets.enc.yaml && $EDITOR runner-secrets.enc.yaml
sops --encrypt --in-place runner-secrets.enc.yaml
cp registry-pull.example.yaml registry-pull.enc.yaml && $EDITOR registry-pull.enc.yaml
sops --encrypt --in-place registry-pull.enc.yaml
git add *.enc.yaml
```

`sops` encrypts only `data` and `stringData`; the Secret's name and namespace stay readable, which is
what lets a reviewer see *which* secret changed without seeing what it holds.

## Rotating

`sops secrets/runner-secrets.enc.yaml` opens the decrypted file in `$EDITOR` and re-encrypts on
save; commit, and `install.sh` applies it. A runner already running keeps the values it was created
with; the next run reads the new ones.
