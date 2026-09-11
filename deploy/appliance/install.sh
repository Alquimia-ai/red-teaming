#!/usr/bin/env bash
# Install or upgrade the red-teaming platform on the appliance: one node, k3s, one GPU.
#
#   sudo deploy/appliance/install.sh                 # everything, idempotent
#   sudo deploy/appliance/install.sh --skip-k3s      # the cluster is somebody else's
#   MODELS="qwen3-8b qwen3-embedding-0.6b" HARDWARE=l40s-48g sudo deploy/appliance/install.sh
#
# Every step is safe to run again: k3s is installed only if absent, the device plugin is applied,
# the secrets are decrypted and applied, and both charts go through `helm upgrade --install`. The
# MinIO volume is kept across upgrades and even across an uninstall: it is the evidence.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
NAMESPACE="${NAMESPACE:-red-teaming}"
MODELS="${MODELS:-qwen3-8b qwen3-embedding-0.6b}"
HARDWARE="${HARDWARE:-l40s-48g}"
K3S_VERSION="${K3S_VERSION:-v1.31.4+k3s1}"
DEVICE_PLUGIN_VERSION="${DEVICE_PLUGIN_VERSION:-v0.17.0}"
SKIP_K3S=""
for arg in "$@"; do
  case "$arg" in
    --skip-k3s) SKIP_K3S=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "$1 is not installed; see README.md" >&2; exit 1; }; }

# ---- the cluster -----------------------------------------------------------------------------
if [ -z "$SKIP_K3S" ]; then
  if ! command -v k3s >/dev/null 2>&1; then
    say "installing k3s $K3S_VERSION"
    curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$K3S_VERSION" sh -s - \
      --write-kubeconfig-mode 644
  fi
  export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
fi
need kubectl
need helm
need sops

say "waiting for the node"
kubectl wait --for=condition=Ready node --all --timeout=180s

# ---- the GPU ---------------------------------------------------------------------------------
# The NVIDIA container toolkit registers the `nvidia` runtime class under k3s on its own once the
# host has the driver; the device plugin is what lets pods ask for `nvidia.com/gpu`.
say "nvidia device plugin $DEVICE_PLUGIN_VERSION"
kubectl apply -f "https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/${DEVICE_PLUGIN_VERSION}/deployments/static/nvidia-device-plugin.yml"
if ! kubectl get runtimeclass nvidia >/dev/null 2>&1; then
  kubectl apply -f - <<'RC'
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
RC
fi

# ---- the namespace and the secrets ------------------------------------------------------------
say "namespace $NAMESPACE"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

shopt -s nullglob
encrypted=("$HERE"/secrets/*.enc.yaml)
if [ ${#encrypted[@]} -eq 0 ]; then
  echo "no encrypted secrets under $HERE/secrets; see secrets/README.md" >&2
  exit 1
fi
for file in "${encrypted[@]}"; do
  say "applying $(basename "$file")"
  sops --decrypt "$file" | kubectl apply -n "$NAMESPACE" -f -
done

# ---- the models -------------------------------------------------------------------------------
say "models: $MODELS on $HARDWARE"
model_values=()
for model in $MODELS; do
  model_values+=(-f "$ROOT/deploy/catalog/models/$model.yaml")
done
helm upgrade --install red-teaming-models "$ROOT/deploy/charts/red-teaming-models" \
  --namespace "$NAMESPACE" \
  -f "$HERE/values-models-appliance.yaml" \
  "${model_values[@]}" \
  -f "$ROOT/deploy/catalog/hardware/$HARDWARE.yaml" \
  --wait --timeout 20m

# ---- the platform -----------------------------------------------------------------------------
say "the platform"
helm upgrade --install red-teaming "$ROOT/deploy/charts/red-teaming-stack" \
  --namespace "$NAMESPACE" \
  -f "$HERE/values-appliance.yaml" \
  --wait --timeout 10m

node_ip="$(kubectl get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')"
say "done: the API answers at http://${node_ip}:30880/healthz"
echo "from a workstation: redteam init --api-url http://${node_ip}:30880"
