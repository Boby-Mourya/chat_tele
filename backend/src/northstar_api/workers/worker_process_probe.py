from __future__ import annotations

import argparse
from pathlib import Path

_TERMINAL_STATES = {"X", "x", "Z"}


def probe_process(
    expected: str,
    *,
    proc_root: Path = Path("/proc"),
    pid: int = 1,
) -> tuple[bool, str]:
    """Verify that a container's main process is the expected live worker."""

    if not expected.strip():
        return False, "expected process identifier is empty"

    process_dir = proc_root / str(pid)
    try:
        raw_cmdline = (process_dir / "cmdline").read_bytes()
        stat = (process_dir / "stat").read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"process metadata unavailable: {type(exc).__name__}"

    command = raw_cmdline.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    if expected not in command:
        return False, "container main process does not match expected worker"

    _, separator, remainder = stat.rpartition(")")
    if not separator:
        return False, "process state metadata is malformed"
    fields = remainder.strip().split()
    if not fields:
        return False, "process state metadata is incomplete"
    state = fields[0]
    if state in _TERMINAL_STATES:
        return False, f"worker process is not live (state={state})"

    return True, f"worker process is live (state={state})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe the container's worker process")
    parser.add_argument("--expect", required=True, help="Expected module or process identifier in PID 1 cmdline")
    parser.add_argument("--pid", type=int, default=1, help="Process ID to inspect (default: container PID 1)")
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"), help=argparse.SUPPRESS)
    args = parser.parse_args()

    healthy, message = probe_process(args.expect, proc_root=args.proc_root, pid=args.pid)
    print(message)
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
