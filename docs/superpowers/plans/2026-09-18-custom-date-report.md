# Custom Date Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release v2.6 support for exact inclusive-date SEO reports without changing existing complete-month workflows or archives.

**Architecture:** Keep full-month reporting on its current path. Add a small custom-date archive path and reader alongside it, then route `--type custom` through a date-range generation path that reuses a current archive and attempts the immediately preceding equal-day Google range. Preserve the existing ready-marker, provenance, and publication gates, generalized only where they currently assume a `YYYY-MM` filename.

**Tech Stack:** Python standard library, existing GA4/GSC clients, JSON ready-marker archives, unittest.

**Spec:** `docs/superpowers/specs/2026-09-18-custom-date-report-design.md`

## Global Constraints

- `custom` accepts only inclusive `YYYY-MM-DD` start and end dates; the label is `YYYY-MM-DD_to_YYYY-MM-DD`.
- Complete-month archives remain immutable and cannot satisfy a partial-date request.
- The current custom archive is required; an absent or failed previous equal-day archive produces unavailable comparison without blocking the current report.
- Do not mention unavailable comparison data in `summary.md` or the final customer “文字总结”.
- Third-party exact-date queries, month-proxy use, and waivers require the user’s explicit choice; paid calls are never automatic or retried.
- Do not change private credential formats, OSS/RAM settings, existing reports, or existing report-type behavior.
- No live Google, provider, SMB, or OSS request is part of automated validation.

---

### Task 1: Add custom-date source identity and immutable archive support

**Files:**
- Modify: `scripts/customer_registry.py`
- Modify: `scripts/google_api_collector.py`
- Create: `tests/test_custom_date_archives.py`

**Interfaces:**
- Produces `custom_google_archive_path(archive_root, record, start_date, end_date) -> Path` at `ga4-gsc/<domain>/custom/<start>_to_<end>.json`.
- Produces `read_ready_custom_date_archive(archive_root, domain, start_date, end_date) -> ReadyArchive` and `save_new_custom_archive(archive_root, domain, start_date, end_date, payload) -> Path`.
- Consumes the existing `write_new_archive_bytes`, `read_ready_archive_bytes`, `ReadyArchive`, customer registry, and `--start`/`--end` collector inputs.

- [ ] **Step 1: Write failing custom archive tests**

Create `tests/test_custom_date_archives.py` with fixtures that write a registered `example.com` archive root and a non-empty GA4/GSC payload for `2026-09-01` through `2026-09-15`. Cover the exact path, successful ready-marker read, domain/date mismatch rejection, no-overwrite rejection, and proof that `ga4-gsc/example.com/2026-09.json` is not read or written.

```python
path = save_new_custom_archive(root, "example.com", "2026-09-01", "2026-09-15", payload)
self.assertEqual(path, root / "ga4-gsc" / "example.com" / "custom" / "2026-09-01_to_2026-09-15.json")
self.assertEqual(read_ready_custom_date_archive(root, "example.com", "2026-09-01", "2026-09-15").payload["period"], ["2026-09-01", "2026-09-15"])
```

- [ ] **Step 2: Run the new test to verify RED**

Run: `./.venv/bin/python -m unittest tests.test_custom_date_archives`

Expected: failure because custom archive helpers do not exist.

- [ ] **Step 3: Implement the minimal archive helpers**

Add strict ISO-date parsing and `custom_google_archive_path` in `customer_registry.py`; reject reversed dates and paths outside the registered customer root. In `google_api_collector.py`, add custom payload validation and reader/writer wrappers that reuse existing byte hashing, locking, exclusive creation, ready-marker generation, and `ReadyArchive`. Keep `validate_complete_month_archive` unchanged.

```python
def custom_google_archive_path(root: Path, record: CustomerRecord, start: str, end: str) -> Path:
    _validate_date_range(start, end)
    return Path(root) / "ga4-gsc" / record.canonical_domain / "custom" / f"{start}_to_{end}.json"
```

- [ ] **Step 4: Extend the collector archive mode**

Permit non-dry-run `--start YYYY-MM-DD --end YYYY-MM-DD` only when both arguments are supplied and `--platform all` is selected. Save that result through `save_new_custom_archive`; retain current `--month` behavior verbatim. Make the collector label always use the full date range for this mode, including same-month ranges.

- [ ] **Step 5: Run source-archive tests**

Run: `./.venv/bin/python -m unittest tests.test_custom_date_archives tests.test_google_archive_import tests.test_report_period_aggregation`

Expected: all tests pass; existing partial-month rejection for a monthly archive remains green.

- [ ] **Step 6: Commit the source-archive unit**

```bash
git add scripts/customer_registry.py scripts/google_api_collector.py tests/test_custom_date_archives.py
git commit -m "Add immutable custom date archives"
```

### Task 2: Generate custom reports and safely attempt equal-day comparison

**Files:**
- Modify: `scripts/report_periods.py`
- Modify: `scripts/generate_dashboard_report.py`
- Modify: `tests/test_report_period_aggregation.py`

**Interfaces:**
- Adds `custom` to `REPORT_TYPES` with label `自定义报告`.
- `generate_dashboard_report.py --type custom --start-date YYYY-MM-DD --end-date YYYY-MM-DD` reads one exact custom source archive.
- Produces `report.customRange = {"startDate": start, "endDate": end, "dayCount": days}` and `comparison_mode` of `complete` or `unavailable`.
- Consumes `read_ready_custom_date_archive` and a callable collector entry point that can attempt the prior range without changing the current archive.

- [ ] **Step 1: Write failing report-generation tests**

Extend `tests/test_report_period_aggregation.py` with a custom-source fixture and two tests: a 15-day run computes `2026-08-17_to_2026-08-31`, and a 20-day run computes `2026-08-12_to_2026-08-31`. Mock the collector only at the call boundary; assert no network client is built. Test an unavailable prior collection still writes a current report with `comparison.available == false`, `comparison_mode == "unavailable"`, and no unavailable-comparison language in `summary.md`.

```python
with patch.object(report_generator, "collect_missing_custom_comparison", side_effect=FileNotFoundError("no access")):
    self.assertEqual(generate_report(), 0)
self.assertNotIn("对比不可用", (report_dir / "summary.md").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run the focused report tests to verify RED**

Run: `./.venv/bin/python -m unittest tests.test_report_period_aggregation`

Expected: failure because `custom` arguments and prior-date computation are not supported.

- [ ] **Step 3: Add custom-range validation and date arithmetic**

In `report_periods.py`, add a date-range validator and an inclusive `previous_equal_day_range(start, end)` helper. Keep the current month-count validation function and its callers for the four older report types unchanged.

```python
def previous_equal_day_range(start: str, end: str) -> tuple[str, str]:
    start_day, end_day = _parse_range(start, end)
    span = (end_day - start_day).days + 1
    return ((start_day - timedelta(days=span)).isoformat(), (start_day - timedelta(days=1)).isoformat())
```

- [ ] **Step 4: Add the custom generator branch**

Make `--start-month` optional only for `custom`; require `--start-date` and `--end-date` for that type and reject those flags for all other types. Load the exact current custom archive. Attempt the exact previous range through a focused collector helper only when that ready archive is absent. Catch prior-only collection/read failures, write a secret-safe `CUSTOM_PREVIOUS_RANGE_UNAVAILABLE` diagnostic and an operator-facing result field, and proceed without comparison. Reject missing or invalid current data before output creation.

- [ ] **Step 5: Make customer-visible text date-accurate**

Set the custom output directory to `<domain>/custom/<start>_to_<end>`, render the full date range and day count, and use neutral “指定报告期” action-plan language. In `summary()`, include comparison prose only when custom comparison is complete; otherwise omit it entirely. Do not alter existing monthly, quarterly, yearly, or period copy.

- [ ] **Step 6: Run generation regressions**

Run: `./.venv/bin/python -m unittest tests.test_report_period_aggregation tests.test_summary_page_names tests.test_report_period_ui_state`

Expected: custom cases pass, and existing report labels and summary rules remain unchanged.

- [ ] **Step 7: Commit the custom-generation unit**

```bash
git add scripts/report_periods.py scripts/generate_dashboard_report.py tests/test_report_period_aggregation.py
git commit -m "Generate custom date reports with safe comparison fallback"
```

### Task 3: Enforce exact-date third-party snapshots and explicit month proxies

**Files:**
- Modify: `scripts/build_google_seo_dashboard.py`
- Modify: `scripts/generate_dashboard_report.py`
- Modify: `assets/dataforseo-trial.example.json`
- Modify: `assets/seoagent-archive.example.json`
- Modify: `tests/test_extension_archive_scope.py`
- Modify: `tests/test_report_period_aggregation.py`

**Interfaces:**
- Custom exact snapshots declare `reporting_period: ["YYYY-MM-DD", "YYYY-MM-DD"]` and `coverage_mode: "exact_date"`.
- An approved fallback declares `coverage_mode: "month_proxy"` plus `proxy_months: ["YYYY-MM"]`; it is usable only after the user-selected set exactly matches the report metadata.
- The report records each provider status as `reused`, `month_proxy`, or `waived`.

- [ ] **Step 1: Write failing snapshot-scope tests**

Add a custom report fixture. Assert that matching exact-date approved DataForSEO and SEOAgent archives are reused; a same-domain archive with a different end date is rejected; a `month_proxy` archive is rejected without explicit matching selected month metadata; and `--without-third-party` generates with provider panels absent.

```python
self.assertEqual(payload["report"]["thirdParty"]["dataforseo"]["status"], "month_proxy")
self.assertIn("月度市场", payload["report"]["thirdParty"]["dataforseo"]["disclosure"])
```

- [ ] **Step 2: Run provider tests to verify RED**

Run: `./.venv/bin/python -m unittest tests.test_extension_archive_scope tests.test_report_period_aggregation`

Expected: failure because custom period identity and proxy mode are not recognized.

- [ ] **Step 3: Implement narrow custom scope validation**

Extend the existing provider validators without weakening their month-based checks. For `custom`, accept only an approved exact-date archive or an approved `month_proxy` archive whose `proxy_months` were explicitly passed by the operator. Never infer a proxy month. Surface non-reusable snapshots as `THIRD_PARTY_APPROVAL_REQUIRED` before any credential read or provider command.

- [ ] **Step 4: Preserve honest report disclosures**

For exact-date snapshots, label provider data with the custom date range. For `month_proxy`, render and record “月度市场/策略背景” plus the selected month names. A waiver hides the associated panels. Do not add provider-missing or comparison-unavailable statements to `summary.md`.

- [ ] **Step 5: Update safe example schemas**

Add empty, non-secret custom-date and month-proxy examples to both provider JSON examples. Document `approval.approved`, `coverage_mode`, `reporting_period`, and `proxy_months`; do not add credentials or real provider output.

- [ ] **Step 6: Run provider regressions**

Run: `./.venv/bin/python -m unittest tests.test_extension_archive_scope tests.test_dataforseo_keyword_enrichment tests.test_report_period_aggregation`

Expected: all existing approved month snapshots still reuse, while custom snapshots require exact scope or explicit proxy mode.

- [ ] **Step 7: Commit the provider-scope unit**

```bash
git add scripts/build_google_seo_dashboard.py scripts/generate_dashboard_report.py assets/dataforseo-trial.example.json assets/seoagent-archive.example.json tests/test_extension_archive_scope.py tests/test_report_period_aggregation.py
git commit -m "Gate custom report provider snapshots by exact scope"
```

### Task 4: Generalize artifact, provenance, and publishing gates for `custom`

**Files:**
- Modify: `scripts/source_archive_usage.py`
- Modify: `scripts/validate_report_artifact.py`
- Modify: `scripts/publish_oss_report.py`
- Modify: `tests/test_source_archive_usage.py`
- Modify: `tests/test_report_output_identity.py`
- Modify: `tests/test_publisher_source_gate.py`

**Interfaces:**
- Source-usage entries retain `role`, `relative_path`, and `sha256`, and additionally validate each recorded source by its report-type-specific reader.
- Custom artifact identity requires `report.customRange`, exact directory label, and an exact date range.
- Publisher accepts `--type custom --period YYYY-MM-DD_to_YYYY-MM-DD` and retains its current three-file SHA-256 gate.

- [ ] **Step 1: Write failing provenance and publication tests**

Create custom ready archives under the new `custom/` directory, write a usage record, and assert `verify_usage` succeeds only while its exact path and digest remain valid. Add publisher dry-run coverage for `custom/2026-09-01_to_2026-09-15` and rejection coverage for a malformed or metadata-mismatched date label.

```python
args = ["--type", "custom", "--period", "2026-09-01_to_2026-09-15", "--dry-run"]
self.assertEqual(publish_main(), 0)
```

- [ ] **Step 2: Run provenance and publisher tests to verify RED**

Run: `./.venv/bin/python -m unittest tests.test_source_archive_usage tests.test_report_output_identity tests.test_publisher_source_gate`

Expected: failure because the current code assumes a month filename and only month-style publication labels.

- [ ] **Step 3: Generalize readers, not path safety**

Make `source_archive_usage.py` select the complete-month or custom-date reader from the usage record’s validated relative path and report type. Continue rejecting absolute paths, another customer root, missing ready markers, and digest changes. Do not relax the existing customer-root boundary.

- [ ] **Step 4: Extend artifact and publisher identity checks**

Add `custom` handling to artifact validation and replace the publisher’s single period regex with type-specific validation from `report_periods.py`. Build the same `<slug>/<type>/<period>` SMB, OSS, and public paths, now allowing the custom label only under `custom`.

- [ ] **Step 5: Run validation regressions**

Run: `./.venv/bin/python -m unittest tests.test_source_archive_usage tests.test_report_output_identity tests.test_publisher_source_gate tests.test_package_smoke`

Expected: custom dry-run passes without writes, malformed custom labels fail, and all older publication paths remain valid.

- [ ] **Step 6: Commit the publication-gate unit**

```bash
git add scripts/source_archive_usage.py scripts/validate_report_artifact.py scripts/publish_oss_report.py tests/test_source_archive_usage.py tests/test_report_output_identity.py tests/test_publisher_source_gate.py
git commit -m "Validate custom report provenance and publishing"
```

### Task 5: Update v2.6 distribution contract and verify the release locally

**Files:**
- Modify: `SKILL.md`
- Modify: `agents/openai.yaml`
- Modify: `CHANGELOG.md`
- Modify: `references/team-first-run-guide.md`
- Modify: `references/team-usage-guide.md`
- Modify: `references/third-party-data-guide.md`
- Modify: `references/windows-first-run.md`
- Modify: `tests/test_package_parity.py`
- Modify: `tests/test_package_smoke.py`

**Interfaces:**
- Documents `custom` exact dates, automatic prior Google attempt, unavailable-comparison disclosure boundary, provider choices, and `custom/<date-range>` paths.
- Retains all credentials exclusively in `private/` and requires explicit paid-request approval.

- [ ] **Step 1: Write failing package-contract tests**

Add static assertions that v2.6 documents `--type custom`, `--start-date`, `--end-date`, no customer-summary disclosure for unavailable comparison, explicit `month_proxy` choice, and the GitHub update source. Keep tests focused on published contract terms rather than prose layout.

- [ ] **Step 2: Run package tests to verify RED**

Run: `./.venv/bin/python -m unittest tests.test_package_parity tests.test_package_smoke`

Expected: failure because v2.6 custom-date terms are not yet present.

- [ ] **Step 3: Update the distribution files**

Set package identity to v2.6 in `SKILL.md` and UI metadata. Update the changelog and teammate documentation with exact commands, the isolated custom archive path, the automatic previous-range behavior, the internal-only unavailable-comparison message, and third-party exact/proxy/waiver choices. State explicitly that `oss.env`, OSS policy, SMB credentials, Google credentials, and provider credentials do not need format changes.

- [ ] **Step 4: Run all offline validation**

Run: `./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`

Then run: `./.venv/bin/python /Users/jzy2026/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`

Expected: full suite and Skill validation pass with no live API, SMB, OSS, or provider request.

- [ ] **Step 5: Create and verify the v2.6 distribution archive**

Copy only tracked, non-private package files to `output/packages/seo-report-portal-v2-6/`, create `output/packages/seo-report-portal-v2-6.zip`, run `scripts/check_package_parity.py` against source and ZIP, and record the SHA-256. Do not install globally, push GitHub, modify OSS, or replace any colleague installation without separate approval.

- [ ] **Step 6: Commit the v2.6 release contract**

```bash
git add SKILL.md agents/openai.yaml CHANGELOG.md references/team-first-run-guide.md references/team-usage-guide.md references/third-party-data-guide.md references/windows-first-run.md tests/test_package_parity.py tests/test_package_smoke.py
git commit -m "Release SEO Report Portal v2.6"
```

## Plan self-review

- Spec coverage: Tasks 1–2 cover isolated exact-date archives and automatic equal-day comparison; Task 3 covers exact/provider-proxy/waiver handling; Task 4 covers provenance and OSS path gates; Task 5 covers customer-copy, distribution, and regression validation.
- No placeholders: checked for unfinished markers and generic validation steps; each task has exact files, interfaces, commands, and behavioral assertions.
- Type consistency: all tasks use `custom`, `start-date`, `end-date`, `customRange`, `coverage_mode`, and the `YYYY-MM-DD_to_YYYY-MM-DD` label consistently.
