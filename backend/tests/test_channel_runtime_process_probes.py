from __future__ import annotations

from pathlib import Path

from northstar_api.workers.worker_process_probe import probe_process


def _write_process(proc_root: Path, module: str, *, pid: int = 1) -> None:
    process_dir = proc_root / str(pid)
    process_dir.mkdir(parents=True)
    process_dir.joinpath("cmdline").write_bytes(f"python\0-m\0{module}\0".encode())
    process_dir.joinpath("stat").write_text(
        f"{pid} (python worker) S 0 0 0 0\n",
        encoding="utf-8",
    )


def test_process_probe_accepts_channel_runtime_workers(tmp_path: Path) -> None:
    modules = (
        "northstar_api.workers.channel_event_consumer",
        "northstar_api.workers.job_dispatcher",
    )
    for index, module in enumerate(modules, start=1):
        _write_process(tmp_path, module, pid=index)
        healthy, message = probe_process(module, proc_root=tmp_path, pid=index)
        assert healthy is True
        assert message == "worker process is live (state=S)"


def test_channel_runtime_manifests_have_matching_readiness_and_liveness_probes() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    expected = {
        "channel-event-consumer.yaml": "northstar_api.workers.channel_event_consumer",
        "job-dispatcher.yaml": "northstar_api.workers.job_dispatcher",
    }

    for filename, module in expected.items():
        manifest = (repo_root / "kubernetes" / "base" / filename).read_text(encoding="utf-8")
        assert "readinessProbe:" in manifest
        assert "livenessProbe:" in manifest
        assert manifest.count("northstar_api.workers.worker_process_probe") == 2
        assert manifest.count(module) == 3  # container command + readiness + liveness
        assert manifest.count("--expect") == 2
        assert "allowPrivilegeEscalation: false" in manifest
        assert "readOnlyRootFilesystem: true" in manifest
