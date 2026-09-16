"""Regression tests for first-party report-period aggregation."""

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

from build_google_seo_dashboard import build_dashboard_data  # noqa: E402
import generate_dashboard_report as report_generator  # noqa: E402
from generate_dashboard_report import main as generate_report  # noqa: E402


def archive(domain: str, *, clicks: int, impressions: int, sessions: int, key_events: int, channels: list[dict]) -> dict:
    """Small hand-checked GA4/GSC archive fixture; channel totals equal GA4 totals."""
    return {
        "domain": domain,
        "period": ["2026-06-01", "2026-06-30"],
        "gsc": {
            "organic_clicks": clicks,
            "organic_impressions": impressions,
            "organic_ctr": clicks / impressions * 100,
            "average_position": 12.5,
            "gsc_queries": [],
            "gsc_pages": [],
            "gsc_index_status": [],
            "gsc_countries": [],
            "gsc_daily": [],
        },
        "ga4": {
            "ga4_total_users": sessions,
            "ga4_page_views": sessions * 2,
            "session_count": sessions,
            "ga4_avg_session_duration": 20,
            "ga4_avg_engagement_time_per_session": 15,
            "ga4_bounce_rate": 0.4,
            "ga4_key_events": key_events,
            "ga4_landing_pages": [],
            "ga4_channels": channels,
            "ga4_sources": [],
            "ga4_countries": [],
            "ga4_daily": [],
        },
    }


class ReportPeriodAggregationTests(unittest.TestCase):
    def write_archive(self, directory: Path, label: str, payload: dict) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{label}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.with_suffix(".json.ready").write_text(
            json.dumps({"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}), encoding="utf-8"
        )
        return path

    def write_registry(self, root: Path) -> None:
        (root / "customer-registry.json").write_text(json.dumps({"customers": [{
            "canonical_domain": "example.com", "portal_slug": "example-com", "status": "active",
        }]}), encoding="utf-8")

    def write_google_archive(
        self, root: Path, month: str, payload: dict | None = None, *, preserve_period: bool = False
    ) -> Path:
        if payload is None:
            payload = archive(
                "example.com", clicks=1, impressions=10, sessions=1, key_events=0,
                channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}],
            )
        if not preserve_period:
            year, month_number = (int(part) for part in month.split("-"))
            payload["period"] = [f"{month}-01", f"{month}-{calendar.monthrange(year, month_number)[1]:02d}"]
        return self.write_archive(root / "ga4-gsc" / "example.com", month, payload)

    def generation_args(self, root: Path, month: str, report_type: str = "monthly", end_month: str | None = None) -> list[str]:
        args = [
            "generate_dashboard_report.py", "--type", report_type, "--start-month", month,
            "--domain", "example.com", "--archive-root", str(root),
            "--template", str(PACKAGE / "assets" / "dashboard-template.html"),
            "--output-root", str(root / "dashboards"), "--diagnostics-root", str(root / "diagnostics"),
        ]
        if end_month:
            args.extend(["--end-month", end_month])
        return args

    def write_provider_archives(self, root: Path, months: list[str]) -> tuple[Path, Path]:
        dataforseo_dir = root / "dataforseo"
        seoagent_dir = root / "seoagent"
        for month in months:
            self.write_archive(dataforseo_dir, month, {
                "domain": "example.com", "month": month, "reporting_period": months,
                "approval": {"approved": True},
                "market": {"location_code": 2840, "language_code": "en"},
                "selected_keywords": [{"query": "approved product"}],
                "search_volume": {"keywords": [{"keyword": "approved product", "search_volume": 10}]},
            })
        self.write_archive(seoagent_dir, months[-1], {
            "provider": "seoagent", "domain": "example.com", "status": "complete",
            "collection_month": months[-1], "reporting_period": months,
            "approval": {"approved": True},
            "query_scope": {"location": "United States", "language": "English"},
            "responses": {
                "domain_keyword_opportunities": {"keywords": [{"keyword": "approved product", "priority": "P1", "intent": "commercial"}]},
                "domain_keywords": {"keywords": []},
                "competitor_keyword_strategy": {"competitors": [], "keywords": []},
            },
        })
        return dataforseo_dir, seoagent_dir

    def test_report_ga4_is_derived_from_monthly_archives_and_matches_channel_totals(self) -> None:
        """Removing or independently altering reportGa4 must not change canonical GA4 totals."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            june = self.write_archive(directory, "2026-06", archive(
                "example.com", clicks=4, impressions=100, sessions=10, key_events=2,
                channels=[
                    {"sessionDefaultChannelGroup": "Direct", "sessions": 6, "keyEvents": 1, "averageEngagementTimePerSession": 10},
                    {"sessionDefaultChannelGroup": "Organic Search", "sessions": 4, "keyEvents": 1, "averageEngagementTimePerSession": 20},
                ],
            ))
            july = self.write_archive(directory, "2026-07", archive(
                "example.com", clicks=6, impressions=200, sessions=5, key_events=1,
                channels=[
                    {"sessionDefaultChannelGroup": "Direct", "sessions": 2, "keyEvents": 0, "averageEngagementTimePerSession": 30},
                    {"sessionDefaultChannelGroup": "Organic Search", "sessions": 3, "keyEvents": 1, "averageEngagementTimePerSession": 40},
                ],
            ))

            payload = build_dashboard_data([june, july], report_months=None)

        report_ga4 = payload.get("reportGa4")
        self.assertEqual(report_ga4["sessions"], 15)
        self.assertEqual(report_ga4["keyEvents"], 3)
        self.assertEqual(sum(row["sessions"] for row in report_ga4["channels"]), 15)
        self.assertEqual(sum(row["keyEvents"] for row in report_ga4["channels"]), 3)
        self.assertEqual(payload["quarterComparison"]["current"]["metrics"]["sessions"], 15)

    def test_small_ga4_channel_session_difference_warns_without_blocking_generation(self) -> None:
        """A normal HLL++ session estimate difference must not discard official GA4 data."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.write_archive(directory, "2026-06", archive(
                "example.com", clicks=1, impressions=10, sessions=13602, key_events=9,
                channels=[
                    {"sessionDefaultChannelGroup": "Direct", "sessions": 13654, "keyEvents": 9},
                ],
            ))
            payload = build_dashboard_data([source], report_months=None)

        self.assertEqual(payload["reportGa4"]["sessions"], 13602)
        mismatch = next(item for item in payload["diagnostics"] if item["code"] == "GA4_CHANNEL_SESSION_TOTAL_MISMATCH")
        self.assertEqual(mismatch["status"], "warning")
        self.assertEqual(mismatch["detected"]["difference"], 52)
        self.assertAlmostEqual(mismatch["detected"]["difference_ratio"], 52 / 13602)

    def test_large_ga4_channel_session_difference_still_blocks_generation(self) -> None:
        """A material channel mismatch must remain a report-generation stop."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.write_archive(directory, "2026-06", archive(
                "example.com", clicks=1, impressions=10, sessions=100, key_events=9,
                channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 103, "keyEvents": 9}],
            ))
            with self.assertRaisesRegex(ValueError, "差异超过允许范围"):
                build_dashboard_data([source], report_months=None)

    def test_ga4_channel_key_event_difference_still_blocks_generation(self) -> None:
        """The session tolerance must not weaken the additive key-event check."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.write_archive(directory, "2026-06", archive(
                "example.com", clicks=1, impressions=10, sessions=100, key_events=9,
                channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 100, "keyEvents": 10}],
            ))
            with self.assertRaisesRegex(ValueError, "渠道关键事件合计"):
                build_dashboard_data([source], report_months=None)

    def test_mixed_domain_archives_are_rejected_before_a_report_is_aggregated(self) -> None:
        """A misplaced client archive must never become part of another client's report."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = self.write_archive(directory, "2026-06", archive(
                "example.com", clicks=1, impressions=10, sessions=1, key_events=0,
                channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}],
            ))
            second = self.write_archive(directory, "2026-07", archive(
                "other.example", clicks=1, impressions=10, sessions=1, key_events=0,
                channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}],
            ))

            with self.assertRaisesRegex(ValueError, "归档域名不一致"):
                build_dashboard_data([first, second], report_months=None)

    def test_predecessor_archives_for_another_domain_block_comparison_generation(self) -> None:
        """A complete but wrong-client predecessor period must not silently become a comparison."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            for label in ("2026-06", "2026-07", "2026-08"):
                self.write_google_archive(root, label, archive(
                    "example.com", clicks=1, impressions=10, sessions=1, key_events=0,
                    channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}],
                ))
            for label in ("2026-03", "2026-04", "2026-05"):
                previous = archive(
                    "other.example", clicks=1, impressions=10, sessions=1, key_events=0,
                    channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}],
                )
                year, month_number = (int(part) for part in label.split("-"))
                previous["period"] = [f"{label}-01", f"{label}-{calendar.monthrange(year, month_number)[1]:02d}"]
                self.write_archive(root / "ga4-gsc" / "example.com", label, previous)
            template = root / "template.html"
            template.write_text('<script id="google-seo-data" type="application/json">{}</script>', encoding="utf-8")
            args = self.generation_args(root, "2026-06", "quarterly", "2026-08")
            args[args.index("--template") + 1] = str(template)
            args[args.index("--output-root") + 1] = str(root / "output")
            with patch.object(sys, "argv", args):
                with self.assertRaisesRegex(ValueError, "归档域名不匹配"):
                    generate_report()

    def test_missing_predecessor_generates_unavailable_comparison(self) -> None:
        """A complete current period remains usable without an all-month prior range."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            current = archive("example.com", clicks=1, impressions=10, sessions=1, key_events=0,
                              channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}])
            current["gsc"]["gsc_queries"] = [{"query": "approved product", "clicks": 1, "impressions": 10, "ctr": 10, "position": 11}]
            self.write_google_archive(root, "2026-06", current)
            dataforseo_dir, seoagent_dir = self.write_provider_archives(root, ["2026-06"])
            args = self.generation_args(root, "2026-06") + ["--dataforseo-archive-dir", str(dataforseo_dir), "--seoagent-archive-dir", str(seoagent_dir)]
            with patch.object(sys, "argv", args):
                self.assertEqual(generate_report(), 0)
            output = root / "dashboards" / "example.com" / "monthly" / "2026-06"
            payload = json.loads((output / "dashboard-data.json").read_text(encoding="utf-8"))
            usage = json.loads((output / "source-archive-usage.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["report"]["comparison"]["available"])
            self.assertEqual(usage["comparison_mode"], "unavailable")

    def test_missing_required_provider_archives_stop_before_output(self) -> None:
        """A normal report must pause before output when paid data cannot be reused."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            self.write_google_archive(root, "2026-06")
            with patch.object(sys, "argv", self.generation_args(root, "2026-06")):
                with self.assertRaisesRegex(ValueError, "THIRD_PARTY_APPROVAL_REQUIRED"):
                    generate_report()
            self.assertFalse((root / "dashboards").exists())

    def test_matching_provider_archives_are_reused_without_network_call(self) -> None:
        """Approved local snapshots for the exact range satisfy the normal report gate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            current = archive("example.com", clicks=1, impressions=10, sessions=1, key_events=0,
                              channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}])
            current["gsc"]["gsc_queries"] = [{"query": "approved product", "clicks": 1, "impressions": 10, "ctr": 10, "position": 11}]
            self.write_google_archive(root, "2026-06", current)
            dataforseo_dir, seoagent_dir = self.write_provider_archives(root, ["2026-06"])
            args = self.generation_args(root, "2026-06") + ["--dataforseo-archive-dir", str(dataforseo_dir), "--seoagent-archive-dir", str(seoagent_dir)]
            with patch.object(sys, "argv", args):
                self.assertEqual(generate_report(), 0)
            payload = json.loads((root / "dashboards" / "example.com" / "monthly" / "2026-06" / "dashboard-data.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["report"]["thirdParty"]["dataforseo"]["status"], "reused")
            self.assertEqual(payload["report"]["thirdParty"]["seoagent"]["status"], "reused")

    def test_explicit_third_party_waiver_generates_hidden_provider_panels(self) -> None:
        """A waiver is recorded and never inferred from absent optional paths."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            self.write_google_archive(root, "2026-06")
            with patch.object(sys, "argv", self.generation_args(root, "2026-06") + ["--without-third-party"]):
                self.assertEqual(generate_report(), 0)
            payload = json.loads((root / "dashboards" / "example.com" / "monthly" / "2026-06" / "dashboard-data.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["report"]["thirdParty"]["dataforseo"]["status"], "waived")
            self.assertEqual(payload["report"]["thirdParty"]["seoagent"]["status"], "waived")
            self.assertNotIn("strategyOpportunities", payload)

    def test_unready_current_archive_blocks_report_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            current = self.write_google_archive(root, "2026-06")
            current.with_suffix(".json.ready").unlink()
            with patch.object(sys, "argv", self.generation_args(root, "2026-06") + ["--allow-current-only"]):
                with self.assertRaisesRegex(ValueError, "尚未就绪"):
                    generate_report()

    def test_complete_monthly_report_writes_current_and_previous_usage(self) -> None:
        """A complete comparison must name exactly the two hashed source archives it used."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            self.write_google_archive(root, "2026-05")
            self.write_google_archive(root, "2026-06")
            with patch.object(sys, "argv", self.generation_args(root, "2026-06") + ["--without-third-party"]):
                self.assertEqual(generate_report(), 0)
            usage = json.loads((root / "dashboards" / "example.com" / "monthly" / "2026-06" / "source-archive-usage.json").read_text(encoding="utf-8"))
            self.assertEqual(usage["comparison_mode"], "complete")
            self.assertEqual([item["role"] for item in usage["archives"]], ["current", "previous"])
            self.assertTrue(all(len(item["sha256"]) == 64 for item in usage["archives"]))

    def test_generation_uses_reader_snapshot_after_source_replacement(self) -> None:
        """A source changed after the reader returns cannot alter this report's in-memory aggregate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            self.write_google_archive(root, "2026-06", archive(
                "example.com", clicks=1, impressions=10, sessions=1, key_events=0,
                channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}],
            ))
            original_reader = report_generator.read_ready_complete_month_archive

            def read_then_replace(*args: object):
                snapshot = original_reader(*args)
                if args[-1] == "2026-06":
                    replacement = archive(
                        "example.com", clicks=99, impressions=100, sessions=99, key_events=0,
                        channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 99, "keyEvents": 0}],
                    )
                    replacement["period"] = ["2026-06-01", "2026-06-30"]
                    snapshot.path.write_text(json.dumps(replacement), encoding="utf-8")
                    snapshot.path.with_suffix(".json.ready").write_text(
                        json.dumps({"sha256": hashlib.sha256(snapshot.path.read_bytes()).hexdigest()}), encoding="utf-8"
                    )
                return snapshot

            with patch.object(report_generator, "read_ready_complete_month_archive", side_effect=read_then_replace), patch.object(sys, "argv", self.generation_args(root, "2026-06") + ["--without-third-party"]):
                self.assertEqual(generate_report(), 0)
            data = json.loads((root / "dashboards" / "example.com" / "monthly" / "2026-06" / "dashboard-data.json").read_text(encoding="utf-8"))
            self.assertEqual(data["months"][0]["metrics"]["clicks"], 1)

    def test_user_selected_month_uses_complete_source_period_without_preview_label(self) -> None:
        """The requested report period is unchanged when its stored source is a complete calendar month."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            current = archive(
                "example.com", clicks=1, impressions=10, sessions=1, key_events=0,
                channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}],
            )
            current["period"] = ["2026-08-01", "2026-08-31"]
            self.write_google_archive(root, "2026-08", current)
            output_root = root / "dashboards"
            args = self.generation_args(root, "2026-08") + ["--without-third-party"]
            with patch.object(sys, "argv", args):
                self.assertEqual(generate_report(), 0)
            report_dir = output_root / "example.com" / "monthly" / "2026-08"
            payload = json.loads((report_dir / "dashboard-data.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["report"]["selectedMonths"], ["2026-08"])
            self.assertNotIn("预览", (report_dir / "summary.md").read_text(encoding="utf-8"))

    def test_incomplete_stored_month_is_rejected_even_with_a_matching_ready_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_registry(root)
            partial = archive(
                "example.com", clicks=1, impressions=10, sessions=1, key_events=0,
                channels=[{"sessionDefaultChannelGroup": "Direct", "sessions": 1, "keyEvents": 0}],
            )
            partial["period"] = ["2026-08-01", "2026-08-25"]
            self.write_google_archive(root, "2026-08", partial, preserve_period=True)
            with patch.object(sys, "argv", self.generation_args(root, "2026-08") + ["--allow-current-only"]):
                with self.assertRaisesRegex(ValueError, "归档周期必须是指定自然月"):
                    generate_report()


if __name__ == "__main__":
    unittest.main()
