"""Guard: the charts render, and what they render is what the dispatcher and the seed expect.

The API creates a run's Job with a service account, a Secret, a ConfigMap and a store Secret it is
told the names of; the chart is what tells it. The two are held together here, along with the seed
the chart carries -- a copy of `deploy/seed`, because a chart can only read its own files -- and
the RBAC the dispatcher's verbs need. `helm` is not a Python dependency: without it on the PATH the
rendering tests skip, and CI installs it.
"""

from __future__ import annotations

import filecmp
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "deploy" / "charts" / "red-teaming-stack"
MODELS = ROOT / "deploy" / "charts" / "red-teaming-models"
CATALOG = ROOT / "deploy" / "catalog"
HELM = shutil.which("helm")

needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not on the PATH")


def _helm(*args: str) -> str:
    done = subprocess.run([str(HELM), *args], capture_output=True, text=True, check=False)
    assert done.returncode == 0, f"helm {' '.join(args)}:\n{done.stdout}\n{done.stderr}"
    return done.stdout


def _rendered(chart: Path, *values: Path, **sets: str) -> list[dict[str, object]]:
    args = ["template", "release", str(chart), "--namespace", "red-teaming"]
    for path in values:
        args += ["-f", str(path)]
    for key, value in sets.items():
        args += ["--set", f"{key}={value}"]
    return [doc for doc in yaml.safe_load_all(_helm(*args)) if doc]


def _one(docs: list[dict[str, object]], kind: str, name: str) -> dict[str, object]:
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]  # type: ignore[index]
    assert len(found) == 1, f"{kind}/{name}: {len(found)} rendered"
    return found[0]


def test_the_seed_the_chart_carries_is_the_seed() -> None:
    """A chart reads only its own files, so `files/seed` is a copy of `deploy/seed`; this is what
    keeps the copy honest."""
    source = ROOT / "deploy" / "seed"
    carried = STACK / "files" / "seed"
    for path in sorted(source.rglob("*")):
        if path.is_dir() or path.name.startswith("."):
            continue
        twin = carried / path.relative_to(source)
        where = twin.relative_to(ROOT)
        assert twin.is_file(), f"{where} is missing; copy deploy/seed into the chart"
        assert filecmp.cmp(path, twin, shallow=False), f"{where} differs from the seed"
    for path in sorted(carried.rglob("*")):
        if path.is_file():
            assert (source / path.relative_to(carried)).is_file(), f"{path} has no source"


@needs_helm
def test_both_charts_lint() -> None:
    _helm("lint", str(STACK))
    _helm("lint", str(MODELS), "-f", str(CATALOG / "models" / "qwen3-8b.yaml"))


@needs_helm
def test_the_api_is_told_what_the_dispatcher_needs_and_the_role_allows_it() -> None:
    docs = _rendered(STACK)
    config = _one(docs, "ConfigMap", "red-teaming-api-config")["data"]
    assert isinstance(config, dict)
    assert config["REDTEAM_DISPATCH_BACKEND"] == "k8s_job"
    assert config["REDTEAM_K8S_RUNNER_SECRET"] == "red-teaming-runner-secrets"
    assert config["REDTEAM_K8S_RUNNER_CONFIG_MAP"] == "red-teaming-runner-config"
    assert config["REDTEAM_K8S_STORE_SECRET"] == "red-teaming-store-creds"
    assert config["REDTEAM_K8S_SERVICE_ACCOUNT"] == "red-teaming-runner"
    assert config["REDTEAM_SECRETS_BACKEND"] == "env"
    _one(docs, "ConfigMap", "red-teaming-runner-config")
    _one(docs, "Secret", "red-teaming-store-creds")
    _one(docs, "ServiceAccount", "red-teaming-runner")

    role = _one(docs, "Role", "red-teaming-api")
    rules = role["rules"]
    assert isinstance(rules, list)
    jobs = next(r for r in rules if "jobs" in r["resources"])
    assert {"create", "get", "list", "watch", "delete"} <= set(jobs["verbs"])
    binding = _one(docs, "RoleBinding", "red-teaming-api")
    assert binding["subjects"][0]["name"] == "red-teaming-api"  # type: ignore[index]

    api = _one(docs, "Deployment", "red-teaming-api")
    spec = api["spec"]["template"]["spec"]  # type: ignore[index]
    assert spec["serviceAccountName"] == "red-teaming-api"
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert api["spec"]["template"]["spec"]["containers"][0]["envFrom"] == [  # type: ignore[index]
        {"configMapRef": {"name": "red-teaming-api-config"}},
        {"secretRef": {"name": "red-teaming-store-creds"}},
    ]


@needs_helm
def test_the_appliance_values_render_a_nodeport_and_a_kept_volume() -> None:
    docs = _rendered(STACK, ROOT / "deploy" / "appliance" / "values-appliance.yaml")
    service = _one(docs, "Service", "red-teaming-api")
    assert service["spec"]["type"] == "NodePort"  # type: ignore[index]
    assert service["spec"]["ports"][0]["nodePort"] == 30880  # type: ignore[index]
    claim = _one(docs, "PersistentVolumeClaim", "red-teaming-minio-data")
    assert claim["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"  # type: ignore[index]
    assert not [d for d in docs if d.get("kind") == "Ingress"]
    config = _one(docs, "ConfigMap", "red-teaming-api-config")["data"]
    assert config["REDTEAM_K8S_IMAGE_PULL_SECRET"] == "red-teaming-registry"  # type: ignore[index]
    seed = _one(docs, "ConfigMap", "red-teaming-seed")["data"]
    assert isinstance(seed, dict)
    assert "catalogues__assistant-baseline.json" in seed and "seed.py" in seed


@needs_helm
@pytest.mark.parametrize("cloud", ["eks", "gke"])
def test_the_cloud_values_render_an_ingress_and_no_minio(cloud: str) -> None:
    docs = _rendered(STACK, ROOT / "deploy" / "cloud" / f"values-{cloud}.yaml")
    kinds = {(d.get("kind"), d["metadata"]["name"]) for d in docs}  # type: ignore[index]
    assert ("Ingress", "red-teaming-api") in kinds
    assert ("Deployment", "red-teaming-minio") not in kinds
    service = _one(docs, "Service", "red-teaming-api")
    assert service["spec"]["type"] == "ClusterIP"  # type: ignore[index]
    config = _one(docs, "ConfigMap", "red-teaming-api-config")["data"]
    assert isinstance(config, dict)
    if cloud == "eks":
        assert "REDTEAM_K8S_STORE_SECRET" not in config, "IRSA, not a key"
        assert "REDTEAM_S3_ENDPOINT" not in config
        account = _one(docs, "ServiceAccount", "red-teaming-runner")
        assert "eks.amazonaws.com/role-arn" in account["metadata"]["annotations"]  # type: ignore[index]
    else:
        assert config["REDTEAM_S3_ENDPOINT"] == "https://storage.googleapis.com"


@needs_helm
def test_the_models_chart_serves_the_catalog_entries_on_the_hardware() -> None:
    docs = _rendered(
        MODELS,
        CATALOG / "models" / "qwen3-8b.yaml",
        CATALOG / "models" / "qwen3-embedding-0.6b.yaml",
        CATALOG / "hardware" / "l40s-48g.yaml",
        apiKeySecret="red-teaming-runner-secrets",
    )
    judge = _one(docs, "Deployment", "judge")
    embedder = _one(docs, "Deployment", "embedder")
    judge_args = judge["spec"]["template"]["spec"]["containers"][0]["args"]  # type: ignore[index]
    embedder_args = embedder["spec"]["template"]["spec"]["containers"][0]["args"]  # type: ignore[index]
    assert "--gpu-memory-utilization" in judge_args
    assert judge_args[judge_args.index("--gpu-memory-utilization") + 1] == "0.55"
    assert embedder_args[embedder_args.index("--gpu-memory-utilization") + 1] == "0.1"
    assert "--task" in embedder_args and "embed" in embedder_args
    assert "--task" not in judge_args
    assert judge["spec"]["template"]["spec"]["runtimeClassName"] == "nvidia"  # type: ignore[index]
    env = {e["name"]: e for e in judge["spec"]["template"]["spec"]["containers"][0]["env"]}  # type: ignore[index]
    assert env["HF_HUB_OFFLINE"]["value"] == "1"
    assert env["VLLM_API_KEY"]["valueFrom"]["secretKeyRef"]["name"] == "red-teaming-runner-secrets"
    _one(docs, "Service", "judge")
    _one(docs, "Service", "embedder")


@needs_helm
def test_the_models_chart_serves_nothing_by_default() -> None:
    assert _rendered(MODELS) == []


def test_the_catalog_names_no_model_in_code_but_every_entry_is_complete() -> None:
    for path in sorted((CATALOG / "models").glob("*.yaml")):
        entries = yaml.safe_load(path.read_text())["models"]
        for name, entry in entries.items():
            assert entry["path"] and entry["servedModelName"], f"{path.name}: {name} is incomplete"
            assert entry["task"] in ("generate", "embed")
    for path in sorted((CATALOG / "hardware").glob("*.yaml")):
        overlay = yaml.safe_load(path.read_text())["models"]
        assert {"judge", "embedder"} <= set(overlay), f"{path.name} does not size both models"
        for entry in overlay.values():
            assert 0 < entry["gpuMemoryUtilization"] < 1


def test_the_install_script_and_the_secret_shapes_agree_on_names() -> None:
    install = (ROOT / "deploy" / "appliance" / "install.sh").read_text()
    assert "helm upgrade --install red-teaming-models" in install
    assert "helm upgrade --install red-teaming " in install
    assert "sops --decrypt" in install
    for example in (ROOT / "deploy" / "appliance" / "secrets").glob("*.example.yaml"):
        doc = yaml.safe_load(example.read_text())
        assert doc["kind"] == "Secret" and doc["metadata"]["namespace"] == "red-teaming"
    values = yaml.safe_load((ROOT / "deploy" / "appliance" / "values-appliance.yaml").read_text())
    assert values["runner"]["secretName"] == "red-teaming-runner-secrets"
    assert values["images"]["pullSecret"] == "red-teaming-registry"
    assert json.loads(json.dumps(values["minio"]))["enabled"] is True
