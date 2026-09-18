"""Custom-date report generation behavior without live provider access."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "scripts"))

from google_api_collector import save_new_custom_archive  # noqa: E402
from generate_dashboard_report import main as generate_report  # noqa: E402
from publish_oss_report import main as publish_report  # noqa: E402


def source_payload() -> dict:
    return {
        "domain": "example.com", "period": ["2026-09-01", "2026-09-15"],
        "gsc": {"organic_clicks": 4, "organic_impressions": 100, "organic_ctr": 4, "average_position": 12,
                "gsc_queries": [], "gsc_pages": [], "gsc_countries": [], "gsc_devices": [], "gsc_daily": [], "gsc_index_status": []},
        "ga4": {"session_count": 10, "ga4_key_events": 1, "ga4_total_users": 8, "ga4_page_views": 12,
                "ga4_avg_session_duration": 20, "ga4_avg_engagement_time_per_session": 15, "ga4_bounce_rate": 0.2,
                "ga4_channels": [{"sessionDefaultChannelGroup": "Direct", "sessions": 10, "keyEvents": 1}],
                "ga4_sources": [], "ga4_countries": [], "ga4_organic_search_countries": [], "ga4_landing_pages": [], "ga4_devices": [], "ga4_daily": []},
    }


class CustomReportGenerationTests(unittest.TestCase):
    def test_current_custom_range_generates_when_prior_range_is_unavailable(self) -> None:
        """A prior-collection failure must not leak into customer summary or block current facts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "customer-registry.json").write_text(json.dumps({"customers": [{
                "canonical_domain": "example.com", "portal_slug": "example-com", "status": "active",
            }]}), encoding="utf-8")
            save_new_custom_archive(root, "example.com", "2026-09-01", "2026-09-15", source_payload())
            args = [
                "generate_dashboard_report.py", "--type", "custom", "--start-date", "2026-09-01", "--end-date", "2026-09-15",
                "--domain", "example.com", "--archive-root", str(root), "--without-third-party",
                "--output-root", str(root / "dashboards"), "--diagnostics-root", str(root / "diagnostics"),
            ]
            with patch.object(sys, "argv", args):
                self.assertEqual(generate_report(), 0)

            report_dir = root / "dashboards" / "example.com" / "custom" / "2026-09-01_to_2026-09-15"
            payload = json.loads((report_dir / "dashboard-data.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["report"]["customRange"], {"startDate": "2026-09-01", "endDate": "2026-09-15", "dayCount": 15})
            self.assertFalse(payload["report"]["comparison"]["available"])
            self.assertNotIn("对比不可用", (report_dir / "summary.md").read_text(encoding="utf-8"))
            archive_root = root / "public"
            archive_root.mkdir()
            env = root / "oss.env"
            env.write_text(f"OSS_ARCHIVE_ROOT={archive_root}\n", encoding="utf-8")
            publish_args = [
                "publish_oss_report.py", "--local-report-dir", str(report_dir), "--client-slug", "example-com",
                "--type", "custom", "--period", "2026-09-01_to_2026-09-15", "--oss-env", str(env),
                "--source-archive-root", str(root), "--dry-run",
            ]
            with patch.object(sys, "argv", publish_args):
                self.assertEqual(publish_report(), 0)


if __name__ == "__main__":
    unittest.main()
