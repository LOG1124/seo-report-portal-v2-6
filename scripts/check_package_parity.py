#!/usr/bin/env python3
"""Compare the v2 source, staged ZIP, and optional global installation before replacement."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import zipfile

from report_diagnostics import diagnostic


CANONICAL_FILES = (
    "SKILL.md",
    "assets/dashboard-template.html",
    "assets/customer-registry.example.json",
    "assets/dataforseo-trial.example.json",
    "assets/oss.env.example",
    "assets/ossutilconfig.example",
    "assets/oss-report-publisher-policy.json",
    "scripts/customer_registry.py",
    "scripts/google_api_collector.py",
    "scripts/import_google_archive.py",
    "scripts/dataforseo_keyword_enrichment.py",
    "scripts/generate_dashboard_report.py",
    "scripts/publish_oss_report.py",
    "scripts/publish_oss_report.sh",
    "scripts/source_archive_usage.py",
    "references/team-first-run-guide.md",
    "references/team-usage-guide.md",
    "references/windows-first-run.md",
    "references/windows-v24-repair-runbook.md",
    "references/third-party-data-guide.md",
    "agents/openai.yaml",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_package_parity(source: Path, staged_zip: Path, installed: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return blockers for any canonical file whose source/ZIP/install bytes differ."""
    source = Path(source)
    staged_zip = Path(staged_zip)
    diagnostics: List[Dict[str, Any]] = []
    with zipfile.ZipFile(staged_zip) as archive:
        names = set(archive.namelist())
        prefix = f"{source.name}/" if any(name.startswith(f"{source.name}/") for name in names) else ""
        for name in CANONICAL_FILES:
            source_path = source / name
            zip_name = f"{prefix}{name}"
            source_bytes = source_path.read_bytes() if source_path.exists() else None
            zip_bytes = archive.read(zip_name) if zip_name in names else None
            installed_path = Path(installed) / name if installed else None
            installed_bytes = installed_path.read_bytes() if installed_path and installed_path.exists() else None
            hashes = {"source": _sha(source_bytes) if source_bytes is not None else None, "staged_zip": _sha(zip_bytes) if zip_bytes is not None else None}
            if installed is not None:
                hashes["installed"] = _sha(installed_bytes) if installed_bytes is not None else None
            if len(set(hashes.values())) != 1:
                diagnostics.append(diagnostic(
                    "SKILL_PACKAGE_OUT_OF_SYNC", stage="package_validation",
                    scope={"skill": source.name, "file": name}, detected=hashes,
                    impact="已阻止将不一致的候选包替换为全局技能。",
                    next_action="重新打包 v2 源目录，并在批准安装前再次执行包一致性校验。",
                    status="blocked",
                ))
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="校验指定 SEO Report Portal 源目录、候选 ZIP 与全局安装的一致性")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--staged-zip", type=Path, required=True)
    parser.add_argument("--installed", type=Path)
    args = parser.parse_args()
    diagnostics = check_package_parity(args.source, args.staged_zip, args.installed)
    print(json.dumps({"skill": args.source.name, "diagnostics": diagnostics}, ensure_ascii=False, indent=2))
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
