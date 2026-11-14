from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _resources(path):
    return [document for document in yaml.safe_load_all(path.read_text()) if document]


def test_eod_archive_and_api_share_a_durable_archive_claim():
    resources = _resources(ROOT / "k8s/base/archive-storage.yaml")
    claim = next(item for item in resources if item["kind"] == "PersistentVolumeClaim")
    assert claim["metadata"]["name"] == "eod-archive-storage"
    assert claim["spec"]["accessModes"] == ["ReadWriteMany"]

    api = next(item for item in _resources(ROOT / "k8s/base/fastapi.yaml") if item["kind"] == "Deployment")
    cron = next(item for item in _resources(ROOT / "k8s/base/eod-cronjob.yaml") if item["kind"] == "CronJob")
    for pod in (api["spec"]["template"]["spec"], cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]):
        assert {volume["persistentVolumeClaim"]["claimName"] for volume in pod["volumes"]} >= {
            "eod-archive-storage"
        }
        container = pod["containers"][0]
        assert any(mount["mountPath"] == "/app/data" for mount in container["volumeMounts"])


def test_kubernetes_producer_has_one_dedicated_collector_deployment():
    resources = _resources(ROOT / "k8s/base/producer.yaml")
    deployment = next(item for item in resources if item["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["template"]["spec"]["containers"][0]["command"] == [
        "python", "-m", "app.producer_runner"
    ]

