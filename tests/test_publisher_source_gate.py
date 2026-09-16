"""Offline publication gates for shared Google source archives."""

from __future__ import annotations

import json
import hashlib
import calendar
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "scripts"))

from customer_registry import CustomerRecord  # noqa: E402
from publish_oss_report import main as publish_main  # noqa: E402
from source_archive_usage import write_usage  # noqa: E402


def publish_args(root: Path, client_slug: str, *, dry_run: bool, allow_current_only: bool = False) -> list[str]:
    args = [
        "publish_oss_report.py", "--local-report-dir", str(root / "report"),
        "--client-slug", client_slug, "--type", "monthly", "--period", "2026-06",
        "--oss-env", str(root / "private" / "oss.env"),
        "--source-archive-root", str(root / "source"),
    ]
    if dry_run:
        args.append("--dry-run")
    if allow_current_only:
        args.append("--allow-current-only")
    return args


class PublisherSourceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.report_dir = self.root / "report"
        self.source_root = self.root / "source"
        self.public_root = self.root / "public"
        self.record = CustomerRecord("example.com", "example-com", "active")
        self._write_report()
        self._write_registry()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_report(self) -> None:
        self.report_dir.mkdir()
        (self.report_dir / "dashboard-data.json").write_text(
            json.dumps({"report": {"domain": "example.com"}}), encoding="utf-8"
        )
        (self.report_dir / "index.html").write_text("index", encoding="utf-8")
        (self.report_dir / "summary.md").write_text("summary", encoding="utf-8")

    def _write_registry(self) -> None:
        self.source_root.mkdir()
        (self.source_root / "customer-registry.json").write_text(
            json.dumps({"customers": [{
                "canonical_domain": self.record.canonical_domain,
                "portal_slug": self.record.portal_slug,
                "status": self.record.status,
            }]}),
            encoding="utf-8",
        )

    def _archive(self, month: str = "2026-06") -> Path:
        archive = self.source_root / "ga4-gsc" / "example.com" / f"{month}.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        year, month_number = (int(part) for part in month.split("-"))
        archive.write_text(json.dumps({
            "domain": "example.com",
            "period": [f"{month}-01", f"{month}-{calendar.monthrange(year, month_number)[1]:02d}"],
            "ga4": {"session_count": 1}, "gsc": {"organic_clicks": 1},
        }), encoding="utf-8")
        archive.with_suffix(".json.ready").write_text(
            json.dumps({"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}), encoding="utf-8"
        )
        return archive

    def _write_usage(self, *, comparison_mode: str = "complete", previous: list[Path] | None = None) -> Path:
        if previous is None:
            previous = [self._archive("2026-05")] if comparison_mode == "complete" else []
        return write_usage(
            self.report_dir, self.source_root, self.record, "monthly", "2026-06",
            [self._archive()], previous, comparison_mode,
        )

    def _write_oss_env(self) -> None:
        private = self.root / "private"
        private.mkdir()
        self.public_root.mkdir()
        (private / "oss.env").write_text(f"OSS_ARCHIVE_ROOT={self.public_root}\n", encoding="utf-8")

    def test_dry_run_rejects_slug_that_does_not_match_the_report_domain(self) -> None:
        self._write_usage()

        with patch.object(sys, "argv", publish_args(self.root, "wrong-slug", dry_run=True)):
            with self.assertRaisesRegex(ValueError, "客户标识与共享映射不一致"):
                publish_main()

    def test_dry_run_accepts_registered_legacy_public_slug(self) -> None:
        self.record = CustomerRecord("example.com", "example.com", "active")
        (self.source_root / "customer-registry.json").write_text(
            json.dumps({"customers": [{
                "canonical_domain": self.record.canonical_domain,
                "portal_slug": self.record.portal_slug,
                "legacy_public_slug": True,
                "status": self.record.status,
            }]}),
            encoding="utf-8",
        )
        self._write_usage()
        self._write_oss_env()

        with patch.object(sys, "argv", publish_args(self.root, "example.com", dry_run=True)):
            self.assertEqual(publish_main(), 0)

    def test_dry_run_rejects_changed_source_archive_without_writing_public_files(self) -> None:
        archive = self._archive()
        self._write_usage()
        archive.write_text(json.dumps({"domain": "example.com", "changed": True}), encoding="utf-8")

        with patch.object(sys, "argv", publish_args(self.root, "example-com", dry_run=True)):
            with self.assertRaisesRegex(ValueError, "源档案 SHA-256 不一致"):
                publish_main()

        self.assertFalse((self.public_root / "example-com").exists())

    def test_dry_run_requires_explicit_current_only_exception(self) -> None:
        self._write_usage(comparison_mode="current_only_exception")
        self._write_oss_env()

        with patch.object(sys, "argv", publish_args(self.root, "example-com", dry_run=True)):
            with self.assertRaisesRegex(ValueError, "仅当期报告必须显式允许发布"):
                publish_main()
        with patch.object(sys, "argv", publish_args(self.root, "example-com", dry_run=True, allow_current_only=True)):
            self.assertEqual(publish_main(), 0)

        self.assertFalse((self.public_root / "example-com").exists())

    def test_dry_run_accepts_unavailable_comparison_without_flag(self) -> None:
        self._write_usage(comparison_mode="unavailable")
        self._write_oss_env()

        with patch.object(sys, "argv", publish_args(self.root, "example-com", dry_run=True)):
            self.assertEqual(publish_main(), 0)

    def test_complete_mode_without_previous_archive_is_rejected(self) -> None:
        self._write_usage(comparison_mode="complete", previous=[])

        with patch.object(sys, "argv", publish_args(self.root, "example-com", dry_run=True)):
            with self.assertRaisesRegex(ValueError, "缺少对比期档案"):
                publish_main()


if __name__ == "__main__":
    unittest.main()
