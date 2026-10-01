"""Run the offline extraction regression suite, including provider contract checks."""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_hybrid_extraction.py",
            "tests/test_extraction_api.py",
            "-q",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )
    raise SystemExit(result.returncode)
