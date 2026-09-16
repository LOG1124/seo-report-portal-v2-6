"""Offline checks that ship with the distributable package."""

from __future__ import annotations

import json
import hashlib
import calendar
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "scripts"))

from dataforseo_keyword_enrichment import load_trial_config  # noqa: E402
from generate_dashboard_report import month_range  # noqa: E402
from publish_oss_report import load_env_file, main as publish_main  # noqa: E402
from customer_registry import CustomerRecord  # noqa: E402
from source_archive_usage import write_usage  # noqa: E402


class PackageSmokeTests(unittest.TestCase):
    def test_v25_identity_is_consistent(self) -> None:
        skill = (PACKAGE / "SKILL.md").read_text(encoding="utf-8")
        agent = (PACKAGE / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("name: seo-report-portal-v2-5", skill)
        self.assertIn("# SEO Report Portal v2.5", skill)
        self.assertIn('display_name: "SEO Report Portal v2.5"', agent)
        self.assertIn("$seo-report-portal-v2-5", agent)
        self.assertNotIn("seo-report-portal-v2-2", skill)

    def test_generic_dataforseo_example_is_a_valid_limited_trial_config(self) -> None:
        config = load_trial_config(PACKAGE / "assets" / "dataforseo-trial.example.json")
        self.assertEqual(config["domain"], "example.com")
        self.assertEqual(config["max_keywords"], 5)
        self.assertEqual(config["serp_device"], "desktop")

    def test_google_api_example_has_a_generic_service_account_email_without_credentials(self) -> None:
        """The copied local Google config must have the collector's required identity key."""
        config = json.loads((PACKAGE / "assets" / "google-api.example.json").read_text(encoding="utf-8"))
        self.assertEqual(config.get("service_account_email"), "service-account@example.invalid")
        self.assertNotIn("private_key", config)
        self.assertNotIn("private_key_id", config)
        self.assertNotIn("client_secret", config)

    def test_month_range_is_local_and_deterministic(self) -> None:
        self.assertEqual(month_range("2026-04", "2026-06"), ["2026-04", "2026-05", "2026-06"])

    def test_windows_unc_env_value_is_preserved_without_shell_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oss.env"
            path.write_text("OSS_ARCHIVE_ROOT=\\\\server\\共享盘\\seo-report-portal\n", encoding="utf-8")
            self.assertEqual(load_env_file(path)["OSS_ARCHIVE_ROOT"], r"\\server\共享盘\seo-report-portal")

    def test_windows_source_archive_unc_value_is_preserved_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oss.env"
            path.write_text("GOOGLE_SOURCE_ARCHIVE_ROOT=\\\\server\\共享盘\\seo-report-source-archive\n", encoding="utf-8")
            self.assertEqual(
                load_env_file(path)["GOOGLE_SOURCE_ARCHIVE_ROOT"],
                r"\\server\共享盘\seo-report-source-archive",
            )

    def test_windows_dry_run_uses_python_publisher_and_explicit_source_root(self) -> None:
        """Windows instructions keep the source check explicit and non-writing."""
        guide = (PACKAGE / "references" / "windows-first-run.md").read_text(encoding="utf-8")
        self.assertIn(
            "py -3 \"$skill\\scripts\\publish_oss_report.py\" --local-report-dir .\\output\\dashboards\\example.com\\monthly\\2026-08 --client-slug example-com --type monthly --period 2026-08 --oss-env .\\private\\oss.env --source-archive-root 'Z:\\seo-report-source-archive' --dry-run",
            guide,
        )
        self.assertIn("publish_oss_report.sh` 仅适用于 macOS", guide)
        self.assertIn("绝不写入 SMB、OSS 或线上链接", guide)

    def test_windows_commands_use_installed_scripts_and_document_google_setup(self) -> None:
        """Windows instructions must not invoke workspace scripts that were never copied there."""
        guide = (PACKAGE / "references" / "windows-first-run.md").read_text(encoding="utf-8")
        for script in (
            "google_api_collector.py",
            "generate_dashboard_report.py",
            "publish_oss_report.py",
        ):
            self.assertIn(f'py -3 "$skill\\scripts\\{script}"', guide)
        self.assertIn('Copy-Item "$skill\\assets\\google-api.example.json" \'private\\google-api.json\'', guide)
        self.assertIn("private\\google-service-account.json", guide)
        self.assertIn("service_account_email", guide)
        self.assertIn("client_email", guide)
        self.assertIn("config\\project-input.json", guide)
        for field in ("website_url", "report_start", "report_end", "cooperation_level"):
            self.assertIn(field, guide)

    def test_team_upgrade_uses_github_without_touching_private_configuration(self) -> None:
        guide = (PACKAGE / "references" / "team-first-run-guide.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/LOG1124/seo-report-portal-v2-4.git", guide)
        self.assertIn("git clone --branch main --single-branch", guide)
        self.assertIn("private/", guide)
        self.assertIn("~/.codex/config.toml", guide)
        self.assertIn("现有全局 Skill 包含 private，停止更新", guide)

    def test_windows_repair_runbook_keeps_automation_in_a_safe_scope(self) -> None:
        runbook = (PACKAGE / "references" / "windows-v24-repair-runbook.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/LOG1124/seo-report-portal-v2-4.git", runbook)
        self.assertIn("WINDOWS_UNC_PILOT_PASS", runbook)
        self.assertIn("不得扫描整个磁盘", runbook)
        self.assertIn("不得自行重新采集", runbook)
        self.assertIn("不得读取、输出、复制或改写任何密钥", runbook)
        self.assertIn("小语种首页", runbook)
        self.assertIn("当前 Codex 工作区根目录内递归", runbook)
        self.assertIn("**\\workflows\\automation\\input\\google_api_archive\\*.json", runbook)

    def test_windows_dataforseo_dry_run_prepares_safe_local_config_first(self) -> None:
        """The documented dry run must not reference a config the setup omitted."""
        guide = (PACKAGE / "references" / "windows-first-run.md").read_text(encoding="utf-8")
        setup = "Copy-Item \"$skill\\assets\\dataforseo-trial.example.json\" 'config\\dataforseo-trial.json'"
        command = 'py -3 "$skill\\scripts\\dataforseo_keyword_enrichment.py" --config .\\config\\dataforseo-trial.json'
        self.assertIn(setup, guide)
        self.assertIn(command, guide)
        self.assertLess(guide.index(setup), guide.index(command))
        self.assertIn("不包含、也不能填写任何凭据", guide)

    def test_cross_platform_publisher_dry_run_checks_smb_path_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "report"
            report_dir.mkdir()
            (report_dir / "index.html").write_text("index", encoding="utf-8")
            (report_dir / "dashboard-data.json").write_text(
                json.dumps({"report": {"domain": "example.com"}}), encoding="utf-8"
            )
            (report_dir / "summary.md").write_text("summary", encoding="utf-8")
            source_root = root / "source"
            source_root.mkdir()
            (source_root / "customer-registry.json").write_text(json.dumps({"customers": [{
                "canonical_domain": "example.com", "portal_slug": "example-com", "status": "active",
            }]}), encoding="utf-8")
            source = source_root / "ga4-gsc" / "example.com" / "2026-06.json"
            previous = source_root / "ga4-gsc" / "example.com" / "2026-05.json"
            source.parent.mkdir(parents=True)
            for archive in (source, previous):
                month = archive.stem
                year, month_number = (int(part) for part in month.split("-"))
                archive.write_text(json.dumps({
                    "domain": "example.com",
                    "period": [f"{month}-01", f"{month}-{calendar.monthrange(year, month_number)[1]:02d}"],
                    "ga4": {"session_count": 1}, "gsc": {"organic_clicks": 1},
                }), encoding="utf-8")
                archive.with_suffix(".json.ready").write_text(
                    json.dumps({"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}), encoding="utf-8"
                )
            write_usage(
                report_dir, source_root, CustomerRecord("example.com", "example-com", "active"),
                "monthly", "2026-06", [source], [previous], "complete",
            )
            archive_root = root / "mapped-drive"
            archive_root.mkdir()
            private = root / "private"
            private.mkdir()
            (private / "oss.env").write_text(f"OSS_ARCHIVE_ROOT={archive_root}\n", encoding="utf-8")
            with patch.object(sys, "argv", [
                "publish_oss_report.py", "--local-report-dir", str(report_dir),
                "--client-slug", "example-com", "--type", "monthly", "--period", "2026-06",
                "--oss-env", str(private / "oss.env"), "--source-archive-root", str(source_root), "--dry-run",
            ]):
                self.assertEqual(publish_main(), 0)
            self.assertFalse((archive_root / "example-com").exists())


if __name__ == "__main__":
    unittest.main()
