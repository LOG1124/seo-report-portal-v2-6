"""Tests for staged v2 package parity before global replacement."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "scripts"))

from check_package_parity import CANONICAL_FILES, check_package_parity  # noqa: E402


FILES = (
    "SKILL.md",
    "assets/dashboard-template.html",
    "assets/customer-registry.example.json",
    "assets/dataforseo-trial.example.json",
    "scripts/customer_registry.py",
    "scripts/google_api_collector.py",
    "scripts/import_google_archive.py",
    "scripts/dataforseo_keyword_enrichment.py",
    "scripts/generate_dashboard_report.py",
    "scripts/publish_oss_report.py",
    "scripts/source_archive_usage.py",
    "references/team-first-run-guide.md",
    "references/team-usage-guide.md",
    "references/windows-first-run.md",
    "references/windows-v24-repair-runbook.md",
    "references/third-party-data-guide.md",
    "agents/openai.yaml",
)


class PackageParityTests(unittest.TestCase):
    def make_skill(self, root: Path, suffix: str = "") -> Path:
        for name in FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name}{suffix}", encoding="utf-8")
        return root

    def make_zip(self, source: Path, destination: Path) -> Path:
        with zipfile.ZipFile(destination, "w") as archive:
            for name in FILES:
                archive.write(source / name, arcname=f"{source.name}/{name}")
        return destination

    def test_matching_source_staged_zip_and_global_copy_pass_parity(self) -> None:
        """A candidate release must be byte-identical across the three selectable forms."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill(root / "source")
            installed = self.make_skill(root / "installed")
            staged_zip = self.make_zip(source, root / "staged.zip")
            self.assertEqual(check_package_parity(source, staged_zip, installed), [])

    def test_out_of_sync_template_is_reported_before_installation(self) -> None:
        """A stale ZIP or global copy must be a visible release blocker, not silent drift."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill(root / "source")
            installed = self.make_skill(root / "installed", suffix="stale")
            staged_zip = self.make_zip(source, root / "staged.zip")
            codes = [item["code"] for item in check_package_parity(source, staged_zip, installed)]
            self.assertIn("SKILL_PACKAGE_OUT_OF_SYNC", codes)

    def test_out_of_sync_source_archive_usage_is_reported_before_installation(self) -> None:
        """The installed source-provenance gate must not drift from the candidate release."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill(root / "source")
            installed = self.make_skill(root / "installed")
            (installed / "scripts" / "source_archive_usage.py").write_text("stale", encoding="utf-8")
            staged_zip = self.make_zip(source, root / "staged.zip")
            codes = [item["code"] for item in check_package_parity(source, staged_zip, installed)]
            self.assertIn("SKILL_PACKAGE_OUT_OF_SYNC", codes)

    def test_windows_repair_runbook_is_a_release_parity_file(self) -> None:
        self.assertIn("references/windows-v24-repair-runbook.md", CANONICAL_FILES)

    def test_shared_period_rules_are_a_release_parity_file(self) -> None:
        self.assertIn("scripts/report_periods.py", CANONICAL_FILES)


if __name__ == "__main__":
    unittest.main()
