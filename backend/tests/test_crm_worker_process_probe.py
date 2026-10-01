from __future__ import annotations

from pathlib import Path

from northstar_api.workers.worker_process_probe import probe_process


def _write_process(proc_root: Path, *, cmdline: bytes, state: str = "S", pid: int = 1) -> None:
    process_dir = proc_root / str(pid)
    process_dir.mkdir(parents=True)
    (process_dir / "cmdline").write_bytes(cmdline)
    (process_dir / "stat").write_text(f"{pid} (python worker) {state} 0 0 0 0\n", encoding="utf-8")


def test_probe_accepts_expected_live_worker(tmp_path: Path) -> None:
    _write_process(
        tmp_path,
        cmdline=b"python\x00-m\x00northstar_api.workers.crm_delivery_worker\x00",
    )

    healthy, message = probe_process(
        "northstar_api.workers.crm_delivery_worker",
        proc_root=tmp_path,
    )

    assert healthy is True
    assert message == "worker process is live (state=S)"


def test_probe_rejects_wrong_worker_identity(tmp_path: Path) -> None:
    _write_process(
        tmp_path,
        cmdline=b"python\x00-m\x00northstar_api.workers.crm_router_consumer\x00",
    )

    healthy, message = probe_process(
        "northstar_api.workers.crm_delivery_worker",
        proc_root=tmp_path,
    )

    assert healthy is False
    assert message == "container main process does not match expected worker"


def test_probe_rejects_terminal_process_state(tmp_path: Path) -> None:
    _write_process(
        tmp_path,
        cmdline=b"python\x00-m\x00northstar_api.workers.crm_webhook_consumer\x00",
        state="Z",
    )

    healthy, message = probe_process(
        "northstar_api.workers.crm_webhook_consumer",
        proc_root=tmp_path,
    )

    assert healthy is False
    assert message == "worker process is not live (state=Z)"


def test_probe_fails_closed_when_process_metadata_is_missing(tmp_path: Path) -> None:
    healthy, message = probe_process(
        "northstar_api.workers.crm_reconciliation",
        proc_root=tmp_path,
    )

    assert healthy is False
    assert message.startswith("process metadata unavailable:")


def test_probe_rejects_empty_expected_identifier(tmp_path: Path) -> None:
    healthy, message = probe_process("   ", proc_root=tmp_path)

    assert healthy is False
    assert message == "expected process identifier is empty"


def test_all_crm_worker_manifests_have_matching_readiness_and_liveness_probes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    expected = {
        "crm-delivery.yaml": "northstar_api.workers.crm_delivery_worker",
        "crm-router.yaml": "northstar_api.workers.crm_router_consumer",
        "crm-webhook-consumer.yaml": "northstar_api.workers.crm_webhook_consumer",
        "crm-reconciliation.yaml": "northstar_api.workers.crm_reconciliation",
        "crm-health-monitor.yaml": "northstar_api.workers.crm_health_monitor",
    }

    for filename, module in expected.items():
        manifest = (repo_root / "kubernetes" / "base" / filename).read_text(encoding="utf-8")
        assert "readinessProbe:" in manifest
        assert "livenessProbe:" in manifest
        assert manifest.count("northstar_api.workers.worker_process_probe") == 2
        assert manifest.count(module) == 3  # container command + readiness + liveness
        assert "--expect" in manifest
