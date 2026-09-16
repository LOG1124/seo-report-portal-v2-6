"""Tests for report artifact path and content identity before publication."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "scripts"))

from validate_report_artifact import validate_report_artifact, validate_report_tree  # noqa: E402


class ReportOutputIdentityTests(unittest.TestCase):
    def write_report(self, root: Path, report_type: str, label: str, months: list[str], *, payload_marker: str = "") -> Path:
        directory = root / "example.com" / report_type / label
        directory.mkdir(parents=True)
        payload = {"report": {"domain": "example.com", "type": report_type, "label": label, "selectedMonths": months, "rangeLabel": months[0] if len(months) == 1 else f"{months[0]} 至 {months[-1]}"}, "marker": payload_marker}
        data = json.dumps(payload, ensure_ascii=False)
        (directory / "dashboard-data.json").write_text(data, encoding="utf-8")
        (directory / "index.html").write_text(f'<script id="google-seo-data" type="application/json">{data}</script>', encoding="utf-8")
        (directory / "summary.md").write_text(f"# example.com {report_type} {label}\n", encoding="utf-8")
        return directory

    def test_monthly_and_quarterly_paths_must_match_report_metadata_and_month_count(self) -> None:
        """A quarterly payload cannot pass validation from a monthly report path."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            monthly = self.write_report(root, "monthly", "2026-06", ["2026-06"], payload_marker="month")
            quarterly = self.write_report(root, "quarterly", "2026-06_to_2026-08", ["2026-06", "2026-07", "2026-08"], payload_marker="quarter")
            self.assertEqual(validate_report_artifact(monthly)["code"], "REPORT_ARTIFACT_VALID")
            self.assertEqual(validate_report_artifact(quarterly)["code"], "REPORT_ARTIFACT_VALID")
            wrong = root / "example.com" / "monthly" / "2026-07"
            wrong.mkdir(parents=True)
            for file in quarterly.iterdir():
                (wrong / file.name).write_text(file.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "REPORT_TYPE_PATH_MISMATCH"):
                validate_report_artifact(wrong)

    def test_period_accepts_five_consecutive_months(self) -> None:
        """A non-standard but continuous span is a valid 阶段报告."""
        with tempfile.TemporaryDirectory() as tmp:
            report = self.write_report(
                Path(tmp), "period", "2026-04_to_2026-08",
                ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
            )
            self.assertEqual(validate_report_artifact(report)["code"], "REPORT_ARTIFACT_VALID")

    def test_quarterly_rejects_non_three_month_period(self) -> None:
        """Named quarterly reports retain their exact three-month contract."""
        with tempfile.TemporaryDirectory() as tmp:
            report = self.write_report(
                Path(tmp), "quarterly", "2026-04_to_2026-08",
                ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
            )
            with self.assertRaisesRegex(ValueError, "季度报告必须包含 3 个月"):
                validate_report_artifact(report)

    def test_duplicate_payloads_at_distinct_period_paths_are_reported(self) -> None:
        """Copying the same report data into another period path must block publication review."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.write_report(root, "monthly", "2026-06", ["2026-06"], payload_marker="same")
            second = self.write_report(root, "monthly", "2026-07", ["2026-07"], payload_marker="same")
            # Simulate the historical defect: the second path contains a byte-for-byte first report.
            for file in first.iterdir():
                (second / file.name).write_text(file.read_text(encoding="utf-8"), encoding="utf-8")
            codes = [item["code"] for item in validate_report_tree(root / "example.com")]
            self.assertIn("DUPLICATE_REPORT_ARTIFACT", codes)


if __name__ == "__main__":
    unittest.main()
