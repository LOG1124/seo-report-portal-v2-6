"""Regression checks for immutable exact-date Google source archives."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "scripts"))

from google_api_collector import (  # noqa: E402
    _period_from_args,
    read_ready_custom_date_archive,
    save_new_custom_archive,
)
from report_periods import previous_equal_day_range, validate_custom_date_range  # noqa: E402


def payload(start: str = "2026-09-01", end: str = "2026-09-15") -> dict:
    return {
        "domain": "example.com", "period": [start, end],
        "ga4": {"session_count": 1}, "gsc": {"organic_clicks": 1},
    }


class CustomDateArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "archive"
        self.root.mkdir()
        (self.root / "customer-registry.json").write_text(json.dumps({"customers": [{
            "canonical_domain": "example.com", "portal_slug": "example-com", "status": "active",
        }]}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_date_archive_is_ready_and_never_uses_month_path(self) -> None:
        """Changing a custom range into a monthly archive must fail this contract."""
        path = save_new_custom_archive(self.root, "example.com", "2026-09-01", "2026-09-15", payload())

        self.assertEqual(
            path,
            self.root / "ga4-gsc" / "example.com" / "custom" / "2026-09-01_to_2026-09-15.json",
        )
        self.assertTrue(path.with_suffix(".json.ready").is_file())
        self.assertFalse((self.root / "ga4-gsc" / "example.com" / "2026-09.json").exists())
        snapshot = read_ready_custom_date_archive(self.root, "example.com", "2026-09-01", "2026-09-15")
        self.assertEqual(snapshot.payload["period"], ["2026-09-01", "2026-09-15"])

    def test_custom_date_archive_rejects_overwrite_and_mismatched_range(self) -> None:
        """Replacing a retained range or reading it under another range is unsafe."""
        save_new_custom_archive(self.root, "example.com", "2026-09-01", "2026-09-15", payload())

        with self.assertRaisesRegex(FileExistsError, "档案已存在"):
            save_new_custom_archive(self.root, "example.com", "2026-09-01", "2026-09-15", payload())
        with self.assertRaisesRegex(FileNotFoundError, "缺少自定义日期归档"):
            read_ready_custom_date_archive(self.root, "example.com", "2026-09-01", "2026-09-20")

    def test_custom_same_month_range_keeps_full_date_label(self) -> None:
        """A half-month label must not collapse into a complete calendar month."""
        start, end, label = _period_from_args(
            SimpleNamespace(report_start="2026-09-01", report_end="2026-09-15"),
            None, "2026-09-01", "2026-09-15",
        )
        self.assertEqual((start, end, label), ("2026-09-01", "2026-09-15", "2026-09-01_to_2026-09-15"))

    def test_previous_equal_day_range_is_inclusive(self) -> None:
        """Dropping either endpoint would make a requested comparison shorter."""
        self.assertEqual(previous_equal_day_range("2026-09-01", "2026-09-15"), ("2026-08-17", "2026-08-31"))
        self.assertEqual(previous_equal_day_range("2026-09-01", "2026-09-20"), ("2026-08-12", "2026-08-31"))
        with self.assertRaisesRegex(ValueError, "结束日期"):
            validate_custom_date_range("2026-09-20", "2026-09-01")


if __name__ == "__main__":
    unittest.main()
