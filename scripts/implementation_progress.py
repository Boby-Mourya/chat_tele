"""Validate the audit register and distinguish estimates from acceptance evidence.

A valid register is not a release approval. --require-release fails while any
scenario, package, blocker or exact-SHA evidence requirement remains unresolved.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTER = ROOT / "docs/production-implementation-register.json"
PACKAGE_STATUSES = {"planned", "in progress", "implemented-unverified", "automated-verified", "environment-verified", "release-approved"}
SCENARIO_STATUSES = {"not run", "partial", "failed", "blocked", "passed"}
SHA = re.compile(r"[0-9a-f]{40}\Z")


def validate_register(data: dict[str, Any]) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported register schema")
    for key, prefix, count in (("packages", "B", 26), ("scenarios", "T", 84)):
        rows = data.get(key)
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError(f"{key} must contain exactly {count} entries")
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"{key} entries must be objects")
        ids = [row.get("id") for row in rows]
        if any(not isinstance(identifier, str) for identifier in ids) or set(ids) != {f"{prefix}{n:02}" for n in range(1, count + 1)}:
            raise ValueError(f"{key} IDs must be complete and unique")
        for row in rows:
            if not isinstance(row.get("title"), str) or not row["title"].strip():
                raise ValueError(f"{row.get('id')} needs a title")
            statuses = PACKAGE_STATUSES if key == "packages" else SCENARIO_STATUSES
            if row.get("status") not in statuses:
                raise ValueError(f"{row['id']} has an invalid status")
            evidence_key = "exit_evidence" if key == "packages" else "evidence"
            evidence = row.get(evidence_key)
            if not isinstance(evidence, list) or any(not isinstance(item, str) or not item for item in evidence):
                raise ValueError(f"{row['id']} has invalid evidence references")
            if key == "packages" and not isinstance(row.get("assessment"), str):
                raise ValueError(f"{row['id']} needs an assessment")
            if row["status"] in {"automated-verified", "environment-verified", "release-approved", "passed"}:
                if not evidence or not SHA.fullmatch(str(row.get("verified_sha", ""))):
                    raise ValueError(f"{row['id']} needs evidence and a verified SHA before completion")
                if not isinstance(row.get("environment"), str) or not row["environment"].strip():
                    raise ValueError(f"{row['id']} needs its verification environment")
    for row in data["packages"]:
        try:
            if not isinstance(row.get("implementation_credit"), str):
                raise ValueError(f"{row['id']} credit must be a decimal string")
            credit = Decimal(row["implementation_credit"])
        except (KeyError, InvalidOperation) as exc:
            raise ValueError(f"{row['id']} has an invalid credit") from exc
        if not credit.is_finite() or not Decimal(0) <= credit <= Decimal(1):
            raise ValueError(f"{row['id']} credit must be finite and between 0 and 1")
        if (credit == 1) != (row["status"] == "release-approved"):
            raise ValueError(f"{row['id']} full credit requires full exit evidence")
    if not isinstance(data.get("release_blockers"), list) or any(not isinstance(item, str) or not item for item in data["release_blockers"]):
        raise ValueError("release_blockers must be a list of descriptions")
    for field in ("audit_baseline_sha", "implementation_baseline_sha"):
        if not SHA.fullmatch(str(data.get(field, ""))):
            raise ValueError(f"{field} must be a full commit SHA")


def summarize(data: dict[str, Any], *, sha: str | None = None) -> dict[str, Any]:
    validate_register(data)
    if sha is not None and not SHA.fullmatch(sha):
        raise ValueError("--sha must be a full lowercase commit SHA")
    credit = sum((Decimal(row["implementation_credit"]) for row in data["packages"]), Decimal(0))
    # Unscoped or old-SHA evidence cannot qualify this release.
    def current(row: dict[str, Any], status: str) -> bool:
        return sha is not None and row["status"] == status and row.get("verified_sha") == sha
    approved = sum(current(row, "release-approved") for row in data["packages"])
    passed = sum(current(row, "passed") for row in data["scenarios"])
    return {
        "sha": sha,
        "engineering_estimate_percent": str((credit / 26 * 100).quantize(Decimal("0.01"))),
        "engineering_credit": str(credit),
        "release_approved_packages": approved,
        "package_total": 26,
        "accepted_scenarios": passed,
        "scenario_total": 84,
        "accepted_scenario_percent": str((Decimal(passed) / 84 * 100).quantize(Decimal("0.01"))),
        "partial_scenarios": sum(row["status"] == "partial" for row in data["scenarios"]),
        "release_ready": approved == 26 and passed == 84 and not data["release_blockers"],
        "blockers": data["release_blockers"],
    }


def render_markdown(data: dict[str, Any], *, sha: str | None = None) -> str:
    summary = summarize(data, sha=sha)
    def safe(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")
    lines = [
        "# Production implementation progress", "",
        "Generated from `docs/production-implementation-register.json`; do not edit this report manually.", "",
        f"**Engineering estimate: {summary['engineering_estimate_percent']}%** ({summary['engineering_credit']} / 26 equal-weight package credits).",
        "This is a manually assessed planning estimate, not measured test coverage, extraction accuracy or release readiness.", "",
        f"Exact-SHA release-approved packages: **{summary['release_approved_packages']} / 26**.",
        f"Exact-SHA accepted scenarios: **{summary['accepted_scenarios']} / 84** ({summary['accepted_scenario_percent']}%).",
        f"Partial scenario evidence: **{summary['partial_scenarios']}**.",
        f"Evidence SHA: `{sha or 'not supplied; no exact-SHA acceptance is credited'}`.",
        f"Release ready: **{'YES' if summary['release_ready'] else 'NO'}**.", "",
        "Zero qualified packages means no complete package exit has been certified for this SHA, not that the repository contains no implementation.", "",
        "## Package register", "", "| Package | Credit | Status | Assessment / remaining work |", "| --- | ---: | --- | --- |",
    ]
    for row in data["packages"]:
        lines.append(f"| {row['id']} {safe(row['title'])} | {row['implementation_credit']} | {row['status']} | {safe(row['assessment'])} |")
    lines.extend(["", "## Release blockers", ""])
    lines.extend(f"- {safe(blocker)}" for blocker in data["release_blockers"])
    lines.extend(["", "## Acceptance matrix", "", "| ID | Scenario | Status |", "| --- | --- | --- |"])
    lines.extend(f"| {row['id']} | {safe(row['title'])} | {row['status']} |" for row in data["scenarios"])
    lines.extend(["", "## Updating progress", "",
        "Update the register with scoped source/test evidence. Full package credit requires all exit evidence; a passed scenario needs its environment, evidence references and verified SHA. Do not convert skipped tests into passes.",
        "Run `python scripts/implementation_progress.py --write docs/production-implementation-progress.md` to regenerate this report.",
        "Run `python scripts/implementation_progress.py --sha <release-sha> --require-release` for the strict recorded-readiness check. Exit 2 means incomplete release evidence; exit 1 means an invalid register.",
        "Exact-SHA signoffs may be supplied with `--register <CI-artifact-register.json>` after tests execute. This avoids trying to embed a commit's own hash inside itself. The checker validates recorded evidence metadata, not the contents or authenticity of external evidence.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    parser.add_argument("--sha")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", type=Path)
    parser.add_argument("--check", type=Path, help="Require an existing report to match the register")
    parser.add_argument("--require-release", action="store_true")
    args = parser.parse_args()
    try:
        data = json.loads(args.register.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Register root must be an object")
        summary = summarize(data, sha=args.sha)
        report = render_markdown(data, sha=args.sha)
        if args.check and args.check.read_text(encoding="utf-8") != report:
            raise ValueError("Generated progress report is stale")
        if args.write:
            args.write.parent.mkdir(parents=True, exist_ok=True)
            args.write.write_text(report, encoding="utf-8")
        print(json.dumps(summary, indent=2) if args.json else report)
        return 2 if args.require_release and not summary["release_ready"] else 0
    except (OSError, ValueError, TypeError) as exc:
        print(f"Invalid implementation register: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
