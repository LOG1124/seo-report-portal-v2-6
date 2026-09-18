---
name: seo-report-portal-v2-6
description: Create, review, and publish client-isolated monthly, quarterly, yearly, or custom-period SEO dashboards from GA4, GSC, approved DataForSEO keyword-market snapshots, and SEOAgent strategy archives.
---

# SEO Report Portal v2.6

**Active identity: `seo-report-portal-v2-6`.** Do not use, install, package, or inspect legacy `seo-report-portal` assets except as an explicitly requested rollback reference.

Work from a team workspace, never from this installed skill directory. Read `references/team-usage-guide.md` before first use. Read `references/third-party-data-guide.md` before any third-party collection or archive import.

## Core rules

- GSC owns search performance and dashboard opportunity-keyword selection. GA4 owns traffic, engagement, and key events. Never replace either with third-party estimates.
- 运营总结关键词第 2 条只使用 GSC 查询数据：月报取当月非品牌词；季报和年报先合并所选报告期，同一关键词按曝光加权计算平均排名，排除包含客户域名主词的品牌词，再按平均排名数值升序取前两条。GA4、DataForSEO 和 SEOAgent 不参与该排名。
- DataForSEO owns selected-keyword search volume, CPC, paid competition, monthly trend, and limited live SERP. Request only exact GSC-selected dashboard keywords.
- SEOAgent owns strategy opportunities: priority optimization themes, competitor keyword directions, and external keyword discoveries. Its estimates never enter first-party KPIs or DataForSEO market columns.
- Before any paid DataForSEO or SEOAgent request, show the customer/domain, market, language, keyword count, SERP count, maximum cost, and purpose. Wait for explicit confirmation. Never retry a paid request automatically.
- Keep provider archives isolated by domain and collection month. Never overwrite GSC/GA4 source archives.
- Credentials are local only. Do not put API credentials, service-account JSON, MCP tokens, customer archives, or published reports in the skill package or a public repository.
- DataForSEO and SEOAgent are required for a normal report. Reuse them only when both local archives have the same canonical customer, exact `reporting_period`, recorded scope, and `approval.approved: true`. Otherwise stop with `THIRD_PARTY_APPROVAL_REQUIRED` before reading credentials or making a paid request. `--without-third-party` is the only explicit waiver; it records the waiver and hides the corresponding panel.
- Resolve every GA4/GSC archive through the active customer registry and explicit shared `--archive-root`. `monthly`, `quarterly`, and `yearly` require exactly 1, 3, and 12 continuous months; `period` requires at least 2 continuous months and is labelled “阶段报告”. `custom` requires inclusive `--start-date YYYY-MM-DD --end-date YYYY-MM-DD`, stored separately from month archives. Missing current data always blocks. For `custom`, automatically attempt the immediately preceding equal-day GA4/GSC range; a missing predecessor makes comparison `unavailable`, never partial, and is reported only to the operator/internal diagnostic—not in `summary.md` or the customer 文字总结.
- The report-period aggregate is canonical. Monthly selection may change only monthly detail panels; it must never alter management summary, report-period KPIs, channels, strategy metadata, or action plans.
- The user's explicit continuous month range is authoritative. Generate and, after the normal explicit publication approval, publish that exact range even when its final month is still in progress. Do not silently replace it with the last closed month or add a "preview" label. Use only the data actually available in the selected monthly archives; real archive, permission, or collection failures must remain visible.
- Hide a waived or invalid DataForSEO or SEOAgent panel. Never fill an empty panel with another month, another client, or a third-party estimate.
- Every run writes secret-safe internal diagnostics outside public dashboard directories. Tell the user the execution state, location, verified detection, impact, safe actions taken, and next action.
- Review the local report before publishing. Publish only after explicit approval.
- **客户交付铁律：**最终回复的“文字总结”只能逐字复制已审核 `summary.md` 中 `## 运营总结` 标题及其编号正文；不得改写、删减、重排、补充、以自定义总结替换，或因任何用户偏好改变。在线报告链接可以单独提供，但不构成文字总结。
- **页面显示与运营总结铁律：**“搜索表现 × 页面体验”页面表只把客户主域（可带 `www`）、无参数的英语根页显示为“首页”；小语种首页（语言子域、语言参数或语言根路径）必须展示其完整 GSC URL，并以该完整 URL 区分和联动，不能与英语首页合并。其他客户可见的根路径 `/` 仍显示为“首页”。不得改写原始 GA4/GSC 路径。运营总结的页面排行只按 GSC 页面点击量：月报用当月，季报/年报用整个指定报告期的点击合计；页面联动表使用同一口径，季报/年报默认展示报告期合计，避免用单月代替整个报告期。
- **运营总结国家/地区口径：**第 6 条只按 GA4 `organicGoogleSearchClicks`（Google 搜索自然点击次数）选出国家/地区；月报取当月，季报/年报取指定报告期合计。该指标要求 GA4 已启用 Search Console 关联；缺少该字段时如实显示“暂无可用数据”，不得回退为会话、GSC 点击或 GSC 展示。

## Workflow

1. Connect the shared source root and create `<shared-source-root>/customer-registry.json` from `assets/customer-registry.example.json`.
2. Before collecting any customer, add exactly one active `canonical_domain` ↔ `portal_slug` record to that registry. New customers must use only lowercase letters, digits, and hyphens in `portal_slug`. An existing public directory whose slug is exactly its canonical domain may be retained only with the explicit `legacy_public_slug: true` marker; do not use that marker for new customers.
3. Import a verified v2.2 local archive with `<installed-skill-dir>/scripts/import_google_archive.py --archive-root <shared-source-root> --source-file <legacy-json> --month YYYY-MM`, or collect one natural month with `<installed-skill-dir>/scripts/google_api_collector.py --archive-root <shared-source-root> --month YYYY-MM`. A custom-date collection uses `--start YYYY-MM-DD --end YYYY-MM-DD` and writes only `<shared-source-root>/ga4-gsc/<canonical-domain>/custom/<start>_to_<end>.json` plus its non-public ready marker. Each consumer reads one validated in-memory JSON snapshot only; neither file is overwritten.
4. Generate with `<installed-skill-dir>/scripts/generate_dashboard_report.py --archive-root <shared-source-root>`. Use `monthly` (1), `quarterly` (3), `yearly` (12), `period` (2+ continuous months), or `custom --start-date YYYY-MM-DD --end-date YYYY-MM-DD`. A missing full predecessor simply hides comparison; an incomplete current period still stops.
5. First look for matching approved local DataForSEO and SEOAgent snapshots. If either is missing or differs in period/scope, show the required paid-request scope and maximum cost, then wait for explicit confirmation. For a custom range that a provider cannot represent exactly, let the user explicitly choose `--third-party-proxy-month YYYY-MM` as labeled monthly context or `--without-third-party`; never choose a month or make a paid call automatically.
6. For a newly approved DataForSEO request, determine GSC-selected terms, run `<installed-skill-dir>/scripts/dataforseo_keyword_enrichment.py --archive-root <shared-source-root> --dry-run`, then run `--execute` once after confirmation. Set `reporting_period` to the exact month list. Normalize approved SEOAgent results using `assets/seoagent-archive.example.json`, including the same `reporting_period` and `approval` fields.
7. Generate with explicit archive inputs. Keep the diagnostics path outside `output/dashboards/`:

```text
--dataforseo-archive-dir <domain-specific-dataforseo-archive-dir>
--seoagent-archive-dir <domain-specific-seoagent-archive-dir>
--diagnostics-root <internal-diagnostic-root>
```

8. Validate the exact local artifact before it can be copied:

```text
python <installed-skill-dir>/scripts/validate_report_artifact.py --report-dir <output/dashboards/domain/type/period> --domain-root <output/dashboards/domain>
```

9. Check the local HTML, summary, and internal `diagnostic.md`. Obtain explicit approval for this exact report before publishing.
10. Publish only with `<installed-skill-dir>/scripts/publish_oss_report.py --source-archive-root <shared-source-root>`. It validates the non-public `source-archive-usage.json`, but publishes only `index.html`, `dashboard-data.json`, and `summary.md`. A legacy current-only exception also requires `--allow-current-only` here. Configure the SMB report archive root for the local OS (macOS mount, Windows mapped drive, or Windows UNC path); never assume another teammate's mount path. The only supported public path is:

```text
https://reports.jzyseo.com/reports/<client-slug>/<monthly|quarterly|yearly|period|custom>/<period>/
```

11. In the final customer delivery, label the exact copied `## 运营总结` section from the reviewed `summary.md` as “文字总结”. Do not generate another prose summary, including when asked to change its wording or emphasis.

The shared SMB source archive has guest read/write access and is therefore not confidential or malicious-tamper-resistant. The ready marker only prevents consumers from using incomplete or accidentally mismatched files. `GOOGLE_SOURCE_ARCHIVE_ROOT` in `oss.env` is only a documented convenience for composing the publisher command; collector and generator never read it implicitly and always require `--archive-root`.

Read `references/team-first-run-guide.md` before a teammate's first end-to-end run. It covers Google access, required-provider approval or waiver, SMB, individual RAM credentials, ossutil, approval, and the required local-to-SMB-to-OSS order.
On Windows, also read `references/windows-first-run.md` before configuring paths or running the publisher.

Before replacing the global v2.5 installation from GitHub `main`, require a clean Git source checkout and a staged Git archive parity check for the complete v2.5 contract:

```text
python <installed-skill-dir>/scripts/check_package_parity.py --source <seo-report-portal-v2-6-source> --staged-zip <candidate.zip> --installed <global-seo-report-portal-v2-6>
```

## Resources

- `references/team-usage-guide.md` — teammate setup and daily workflow.
- `references/team-first-run-guide.md` — first-use checklist for the complete collection-to-public-link workflow.
- `references/windows-first-run.md` — Windows paths, SMB mapping, Python, and publisher setup.
- `references/windows-v24-repair-runbook.md` — one-task Windows update, UNC pilot, and v2.2 archive recovery handoff.
- `references/third-party-data-guide.md` — provider scope, cost gate, archive rules, and dashboard meaning.
- `references/seo-data-source-contract.json` — authoritative field ownership.
- `assets/dataforseo-trial.example.json` — safe DataForSEO configuration example.
- `assets/dataforseo.env.example` — empty credential-file template.
- `assets/oss.env.example` and `assets/ossutilconfig.example` — safe local OSS configuration templates.
- `assets/oss-report-publisher-policy.json` — minimum RAM policy for the `jzyseo-reports/reports/*` upload prefix.
- `assets/seoagent-archive.example.json` — normalized SEOAgent archive example.
