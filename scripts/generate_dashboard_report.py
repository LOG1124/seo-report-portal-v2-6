#!/usr/bin/env python3
"""Generate a dashboard and written summary from a selected range of monthly archives."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from build_google_seo_dashboard import _domain_brand_token, _normalise_strategy_opportunities, build_dashboard_data
from customer_registry import require_active_customer
from google_api_collector import ReadyArchive, read_ready_complete_month_archive
from report_diagnostics import diagnostic, write_diagnostics
from report_periods import REPORT_TYPES, TYPE_LABELS, validate_report_months
from source_archive_usage import write_usage
from validate_report_artifact import validate_report_artifact, validate_report_tree

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATA_TAG_RE = re.compile(r'(<script id="google-seo-data" type="application/json">).*?(</script>)', re.S)
RUNTIME_SCRIPT_RE = re.compile(
    r"<script>\n\(\(\) => \{\n  const root = document\.getElementById\('seo-growth-dashboard-v2'\);.*?\n</script>",
    re.S,
)


def shift_month(value: str, delta: int) -> str:
    year, month = map(int, value.split("-"))
    absolute = year * 12 + month - 1 + delta
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def display_range(months: List[str], report_type: str) -> str:
    return months[0] if report_type == "monthly" else f"{months[0]} 至 {months[-1]}"


def fail(message: str) -> None:
    raise ValueError(message)


def read_archives(archive_root: Path, domain: str, months: List[str], *, required: bool) -> tuple[List[ReadyArchive], List[str]]:
    """Read each source month once; optional comparison months may be absent only as a group."""
    snapshots: List[ReadyArchive] = []
    missing: List[str] = []
    for month in months:
        try:
            snapshots.append(read_ready_complete_month_archive(archive_root, domain, month))
        except FileNotFoundError:
            if required:
                fail(f"缺少月度归档：{month}")
            missing.append(month)
        except ValueError as exc:
            fail(str(exc))
    return snapshots, missing


def standalone_document(fragment: str) -> str:
    """Serve generated dashboard fragments as UTF-8 standalone HTML documents."""
    if re.search(r"<!doctype\\s+html|<html[\\s>]", fragment, re.I):
        return fragment
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body>'
        f"{fragment}</body></html>"
    )


def month_range(start: str, end: str) -> List[str]:
    if not MONTH_RE.fullmatch(start) or not MONTH_RE.fullmatch(end):
        fail("月份格式应为 YYYY-MM")
    current, result = start, []
    while current <= end:
        result.append(current)
        year, month = map(int, current.split("-"))
        current = f"{year + (month == 12):04d}-{1 if month == 12 else month + 1:02d}"
    if not result:
        fail("结束月份不能早于开始月份")
    return result


def pct_change(first: float, last: float) -> str:
    if first == 0:
        return "无法计算（起始月为 0）"
    return f"{(last - first) / first * 100:+.1f}%"


def top_rows(months: List[Dict[str, Any]], key: str, name_key: str, value_key: str, limit: int = 2) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for month in months:
        for row in month.get(key, []):
            name = str(row.get(name_key, "")).strip()
            if not name:
                continue
            item = merged.setdefault(name, {"name": name, "value": 0.0})
            item["value"] += float(row.get(value_key, 0) or 0)
    return sorted(merged.values(), key=lambda item: item["value"], reverse=True)[:limit]


def channel_name(value: str) -> str:
    return {
        "Direct": "直接访问", "Paid Search": "付费搜索", "Organic Search": "自然搜索",
        "Organic Social": "自然社媒", "Referral": "引荐流量", "Unassigned": "未分类流量",
    }.get(value, value)


def page_name(value: str) -> str:
    return "首页" if value == "/" else value


def _value(row: Dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_brand_query(query: Any, domain: str) -> bool:
    """Use the customer domain token as the no-reconfiguration brand baseline."""
    token = _domain_brand_token(str(domain).removeprefix("www."))
    normalised_query = re.sub(r"[^a-z0-9]+", "", str(query or "").lower())
    # ponytail: domain-token heuristic covers the no-config baseline; add explicit aliases when a client needs them.
    return bool(token and normalised_query and token in normalised_query)


def _summary_keywords(months: List[Dict[str, Any]], domain: str, report_type: str) -> List[Dict[str, Any]]:
    """Select the report summary keywords from GSC rows, not GA4 or third-party data."""
    if report_type == "monthly":
        rows = [row for row in months[-1].get("keywords", []) if not _is_brand_query(row.get("query"), domain)]
        return sorted(rows, key=lambda row: _value(row, "impressions"), reverse=True)[:2]
    rows = [
        row for row in _aggregate_action_rows(months, "keywords", "query")
        if row["impressions"] > 0 and not _is_brand_query(row.get("query"), domain)
    ]
    return sorted(rows, key=lambda row: (row["position"], -row["impressions"], str(row["query"])))[:2]


def _aggregate_action_rows(months: List[Dict[str, Any]], key: str, name_key: str) -> List[Dict[str, Any]]:
    """Aggregate report-period detail rows without changing immutable archives."""
    merged: Dict[str, Dict[str, float | str]] = {}
    for month in months:
        for row in month.get(key, []):
            name = str(row.get(name_key, "")).strip()
            if not name:
                continue
            item = merged.setdefault(name, {
                name_key: name, "clicks": 0.0, "impressions": 0.0, "sessions": 0.0,
                "positionWeight": 0.0, "bounceWeight": 0.0,
            })
            impressions = _value(row, "impressions")
            sessions = _value(row, "sessions")
            item["clicks"] += _value(row, "clicks")
            item["impressions"] += impressions
            item["sessions"] += sessions
            item["positionWeight"] += _value(row, "position") * impressions
            item["bounceWeight"] += _value(row, "bounceRate") * sessions
    rows: List[Dict[str, Any]] = []
    for item in merged.values():
        impressions = float(item["impressions"])
        sessions = float(item["sessions"])
        rows.append({
            name_key: item[name_key],
            "clicks": item["clicks"],
            "impressions": impressions,
            "sessions": sessions,
            "ctr": item["clicks"] / impressions * 100 if impressions else 0.0,
            "position": item["positionWeight"] / impressions if impressions else 0.0,
            "bounceRate": item["bounceWeight"] / sessions if sessions else 0.0,
        })
    return rows


def _action_number(value: Any, digits: int = 0) -> str:
    number = float(value or 0)
    return f"{number:.{digits}f}" if digits else f"{number:,.0f}"


def _is_actionable_page(path: Any) -> bool:
    """Exclude file-download URLs from content and conversion action priorities."""
    return not str(path or "").lower().split("?", 1)[0].endswith((
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".png", ".jpg", ".jpeg", ".webp",
    ))


def build_action_plans(months: List[Dict[str, Any]], report_type: str) -> List[Dict[str, str]]:
    """Build three report-specific 90-day actions from the selected report period."""
    if not months:
        return []
    pages = [row for row in _aggregate_action_rows(months, "pages", "path") if _is_actionable_page(row["path"])]
    keywords = _aggregate_action_rows(months, "keywords", "query")
    impressions = sum(_value(month.get("metrics", {}), "impressions") for month in months)
    clicks = sum(_value(month.get("metrics", {}), "clicks") for month in months)
    site_ctr = clicks / impressions * 100 if impressions else 0.0
    scope = "本月" if report_type == "monthly" else "指定报告期"

    ctr_pages = [row for row in pages if row["impressions"] > 0]
    ctr_page = max(
        (row for row in ctr_pages if row["ctr"] < site_ctr),
        key=lambda row: row["impressions"],
        default=max(ctr_pages, key=lambda row: row["impressions"], default=None),
    )
    keyword = max(
        (row for row in keywords if 10 < row["position"] <= 30),
        key=lambda row: row["impressions"],
        default=max(keywords, key=lambda row: row["impressions"], default=None),
    )
    experience_page = max(pages, key=lambda row: (row["sessions"], row["bounceRate"]), default=None)

    plans: List[Dict[str, str]] = []
    if ctr_page:
        plans.append({
            "period": "1–30 天",
            "title": f"提升 {page_name(str(ctr_page['path']))} 的搜索点击率",
            "copy": (
                f"{scope}该页获得 {_action_number(ctr_page['impressions'])} 次曝光、"
                f"{_action_number(ctr_page['clicks'])} 次点击，CTR {_action_number(ctr_page['ctr'], 2)}%，"
                f"平均排名第 {_action_number(ctr_page['position'], 1)} 位。"
                "优先优化标题、描述、首屏卖点与询盘入口。"
            ),
            "kpi": "观察：该页曝光、CTR、自然点击与询盘关键事件",
        })
    else:
        plans.append({
            "period": "1–30 天",
            "title": "建立重点落地页的搜索承接",
            "copy": f"{scope}暂无可用于页面级比较的搜索数据。先明确首页、产品页与案例页的主题分工，并补齐标题、描述和内部链接。",
            "kpi": "观察：重点页面的收录、曝光与自然点击",
        })
    if keyword:
        plans.append({
            "period": "31–60 天",
            "title": f"推进“{keyword['query']}”的自然排名",
            "copy": (
                f"该词在{scope}累计 {_action_number(keyword['impressions'])} 次曝光、"
                f"{_action_number(keyword['clicks'])} 次点击，平均排名第 {_action_number(keyword['position'], 1)} 位。"
                "围绕对应采购场景补充页面信息，并从相关产品与案例页建立内链。"
            ),
            "kpi": "观察：该词排名、曝光、自然点击与相关页面会话",
        })
    else:
        plans.append({
            "period": "31–60 天",
            "title": "建立可持续跟踪的关键词主题",
            "copy": f"{scope}暂无可用于关键词级比较的数据。先从已有产品、应用与采购场景中确定可持续追踪的核心主题。",
            "kpi": "观察：主题词覆盖、曝光、平均排名与自然点击",
        })
    if experience_page:
        plans.append({
            "period": "61–90 天",
            "title": f"改善 {page_name(str(experience_page['path']))} 的访问承接",
            "copy": (
                f"{scope}该页有 {_action_number(experience_page['sessions'])} 次会话，"
                f"跳出率 {_action_number(experience_page['bounceRate'], 2)}%。"
                "优化首屏价值说明、相关内容入口和询盘 CTA，提升访问后的下一步行动。"
            ),
            "kpi": "观察：跳出率、平均互动时长、CTA 点击与关键事件",
        })
    else:
        plans.append({
            "period": "61–90 天",
            "title": "补齐自然流量的转化路径",
            "copy": "检查产品页和联系页的表单、邮箱、电话与即时通讯入口，并建立可追踪的关键事件。",
            "kpi": "观察：自然搜索会话、互动质量与关键事件",
        })
    return plans


def summary(payload: Dict[str, Any], title: str, domain: str) -> str:
    all_months = payload["months"]
    selected_labels = set(payload.get("report", {}).get("selectedMonths", []))
    months = [month for month in all_months if month["label"] in selected_labels] or all_months
    total = payload["quarterComparison"]["current"]["metrics"]
    first, last = months[0]["metrics"], months[-1]["metrics"]
    ranked_keywords = len({str(row.get("query", "")) for month in months for row in month.get("keywords", []) if row.get("query")})
    keywords = _summary_keywords(months, domain, payload.get("report", {}).get("type", "monthly"))
    channels = top_rows(months, "channels", "sessionDefaultChannelGroup", "sessions")
    pages = top_rows(months, "pages", "path", "clicks")
    countries = top_rows(months, "ga4OrganicSearchCountries", "country", "organicGoogleSearchClicks", limit=1)
    channel_text = "，其次是".join(channel_name(str(item["name"])) for item in channels)
    page_text = "，其次是".join(page_name(str(item["name"])) for item in pages)
    lines = [
        f"# {title} 数据总结",
        "",
        f"- 网站：{domain}",
        f"- 周期：{payload.get('report', {}).get('rangeLabel', months[-1]['label'])}",
        f"- 已汇总月度归档：{', '.join(month['label'] for month in months)}",
        "",
        "## 运营总结",
        "",
        f"1. 近期有 {ranked_keywords} 个关键词开始有排名，平均排名 {total['averagePosition']:.1f}。",
    ]
    if keywords:
        lines.append("2. " + "；".join(f"关键词 {row.get('query')} 排名 {float(row.get('position', 0) or 0):.0f}" for row in keywords) + "。")
    lines.append(f"3. 谷歌自然展示次数 {int(total['impressions'])} 次，点击次数 {int(total['clicks'])} 次，CTR {total['ctr']:.2f}%。")
    if channel_text or page_text:
        lines.append(f"4. 访问来源以 {channel_text or '暂无可用数据'} 为主；GSC 点击最高的页面为 {page_text or '暂无可用数据'}。")
    lines.append("5. 社媒建议持续更新与产品、案例相关的帖子，为网站引流。")
    lines.append(f"6. 访问较多的国家/地区是 {countries[0]['name'] if countries else '暂无可用数据'}。")
    lines.append("7. 建议每周保持 2–4 篇网站博客和产品更新。")
    comparison = payload.get("report", {}).get("comparison", {})
    if comparison.get("available"):
        lines.append(f"8. 本{payload['report']['typeLabel']}与{comparison['label']}对比：自然点击 {comparison['clickDelta']:+.1f}%，CTR {comparison['ctrDelta']:+.1f}%，平均排名 {comparison['rankDelta']:+.1f} 位（正值代表排名改善）。")
    lines.extend(["", "## 补充指标", "", f"- 本期会话 {int(total['sessions'])} 次；首末月会话变化 {pct_change(float(first['sessions']), float(last['sessions']))}。"])
    return "\n".join(lines) + "\n"


def runtime_script() -> str:
    """Patch template text that is intentionally presentation-only, not source data."""
    return """
<script>
(() => {
  const root = document.getElementById('seo-growth-dashboard-v2');
  const data = JSON.parse(root.querySelector('#google-seo-data').textContent);
  const report = data.report || {};
  const current = data.quarterComparison?.current?.metrics || {};
  const previous = data.quarterComparison?.previous?.metrics;
  const months = data.months || [];
  const text = (selector, value) => { const node = root.querySelector(selector); if (node) node.textContent = value; };
  const number = value => Number(value || 0).toLocaleString();
  const typeLabel = report.typeLabel || '报告期';
  const range = report.rangeLabel || '本报告期';
  const compare = report.comparison || {};
  const monthOverMonth = report.type === 'monthly' && compare.available;
  const comparisonContext = monthOverMonth ? `本月与${compare.label}对比` : `${months.length} 个月度归档${compare.available ? ` · 对比${compare.label}` : ''}`;
  text('.topbar-brand p', report.domain || '');
  text('#report-period-trends h2', `${typeLabel}趋势`);
  text('#report-period-trends .apple-section-heading p', `${range} · ${comparisonContext}`);
  if (monthOverMonth) {
    text('[data-panel="google-seo"] .apple-section-heading h2', '月度对比 · Google SEO Intelligence');
    text('[data-seo-panel="summary"] .section-head .section-title', '本月与上月变化');
  }
  text('[data-seo-panel="seo-channels"] .section-note', `${typeLabel}汇总`);
  text('[data-panel="plan"] h2', '下一阶段行动计划');
  text('[data-panel="plan"] .apple-section-heading p', `基于本${typeLabel}数据结论制定`);
  text('[data-panel="markets"] .apple-section-heading p', '报告期内的自然搜索地区机会');
  text('[data-panel="markets"] .chart-caption', '优先优化高曝光、低点击率市场的标题、描述、案例内容与产品落地页。');
  const footer = root.querySelectorAll('.dashboard-footer div');
  if (footer[1]) footer[1].textContent = `数据周期：${range} · ${comparisonContext} · 站点：${report.domain || ''}`;
  const cards = root.querySelectorAll('[data-panel="overview"] .viz-stat');
  const values = [[current.clicks,'次'], [current.impressions,'次'], [current.ctr,'%'], [current.averagePosition,'']];
  cards.forEach((card, index) => {
    const value = values[index]; if (!value) return;
    const target = card.querySelector('.viz-stat-value');
    if (target) target.innerHTML = `${index === 2 || index === 3 ? Number(value[0] || 0).toFixed(index === 2 ? 2 : 1) : number(value[0])}${value[1] ? ` <span class="metric-tag text-small">${value[1]}</span>` : ''}`;
  });
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const plans = report.actionPlans || [];
  const timeline = root.querySelector('[data-panel="plan"] .timeline');
  if (timeline) {
    timeline.innerHTML = plans.map(plan => {
      return `<div class="phase"><div class="phase-period text-small">${plan.period}</div><div class="rail"><span class="node"></span></div><div><div class="phase-title">${escapeHtml(plan.title)}</div><div class="phase-copy">${escapeHtml(plan.copy)}</div><div class="phase-kpi text-small">${escapeHtml(plan.kpi)}</div></div></div>`;
    }).join('');
  }
})();
</script>"""


def refresh_existing_dashboard_action_plans(dashboard_dir: Path) -> None:
    """Refresh only derived action-plan content in an already generated report."""
    data_path = dashboard_dir / "dashboard-data.json"
    html_path = dashboard_dir / "index.html"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    report = payload.get("report")
    if not isinstance(report, dict):
        fail(f"既有看板缺少报告口径：{data_path}")
    months = payload.get("months")
    if not isinstance(months, list) or not months:
        fail(f"既有看板缺少月度明细：{data_path}")
    report["actionPlans"] = build_action_plans(months, str(report.get("type", "monthly")))
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    html = html_path.read_text(encoding="utf-8")
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html, data_count = DATA_TAG_RE.subn(lambda match: match.group(1) + embedded + match.group(2), html, count=1)
    if data_count != 1:
        fail(f"既有看板未找到数据块：{html_path}")
    html, script_count = RUNTIME_SCRIPT_RE.subn(runtime_script().strip(), html, count=1)
    if script_count != 1:
        fail(f"既有看板未找到运行时渲染脚本：{html_path}")
    html_path.write_text(standalone_document(html), encoding="utf-8")


def restore_quarterly_market_snapshot_for_rendering(payload: Dict[str, Any]) -> None:
    """Expose a preserved quarterly DataForSEO snapshot to the shared market renderer."""
    report = payload.get("report", {})
    quarterly = payload.get("dataforseoQuarterly")
    months = payload.get("months")
    if report.get("type") != "quarterly" or not isinstance(quarterly, dict) or not isinstance(months, list) or not months:
        return
    final_month = months[-1]
    if not isinstance(final_month, dict) or final_month.get("marketKeywords"):
        return
    keywords = quarterly.get("keywords", [])
    if not isinstance(keywords, list) or not keywords:
        return
    final_month["marketKeywords"] = [
        {
            "query": row.get("query"),
            "search_volume": row.get("q2SearchDemand"),
            "cpc": row.get("cpc"),
            "competition": row.get("competition"),
        }
        for row in keywords
        if isinstance(row, dict) and row.get("query")
    ]
    serp = quarterly.get("serp", {})
    organic_results = serp.get("organicResults", []) if isinstance(serp, dict) else []
    if isinstance(serp, dict) and serp.get("keyword") and isinstance(organic_results, list):
        final_month["serpDetail"] = {
            "keyword": serp["keyword"],
            "organic_results": organic_results,
        }


def refresh_existing_dashboard_strategy(
    dashboard_dir: Path,
    strategy_archive: Path,
    template_path: Path,
) -> None:
    """Add a validated SEOAgent snapshot without rewriting preserved Google archives."""
    data_path = dashboard_dir / "dashboard-data.json"
    html_path = dashboard_dir / "index.html"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    report = payload.get("report")
    if not isinstance(report, dict):
        fail(f"既有看板缺少报告口径：{data_path}")
    raw = json.loads(strategy_archive.read_text(encoding="utf-8"))
    expected_domain = str(report.get("domain", ""))
    if raw.get("provider") != "seoagent" or raw.get("domain") != expected_domain or raw.get("status") != "complete":
        fail(f"SEOAgent 归档与看板不匹配：{strategy_archive}")
    strategy = _normalise_strategy_opportunities(raw)
    if not (strategy["priorityOpportunities"] or strategy["domainKeywords"] or strategy["competitorDirections"]):
        fail(f"SEOAgent 归档没有可展示的策略数据：{strategy_archive}")
    payload["strategyOpportunities"] = strategy
    restore_quarterly_market_snapshot_for_rendering(payload)
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    html = template_path.read_text(encoding="utf-8")
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    rendered, count = DATA_TAG_RE.subn(lambda match: match.group(1) + embedded + match.group(2), html, count=1)
    if count != 1:
        fail(f"看板模板中未找到 google-seo-data 数据块：{template_path}")
    html_path.write_text(standalone_document(rendered + runtime_script()), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="按任意月份范围生成月度、季度、年度或阶段看板与总结")
    parser.add_argument("--type", choices=sorted(REPORT_TYPES), required=True)
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--allow-current-only", action="store_true")
    parser.add_argument("--dataforseo-archive-dir", type=Path)
    parser.add_argument("--seoagent-archive-dir", type=Path)
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "assets" / "dashboard-template.html",
    )
    parser.add_argument("--output-root", type=Path, default=Path("output/dashboards"))
    parser.add_argument("--diagnostics-root", type=Path, default=Path("output/report-diagnostics"))
    args = parser.parse_args()

    archive_root = args.archive_root.resolve()
    end = args.end_month or args.start_month
    requested = month_range(args.start_month, end)
    validate_report_months(args.type, requested)
    record = require_active_customer(archive_root, args.domain)
    domain = record.canonical_domain
    archives, _ = read_archives(archive_root, domain, requested, required=True)

    comparison_labels = {"monthly": "上月", "quarterly": "上个季度", "yearly": "上一年度", "period": "上一等长阶段"}
    previous_requested = month_range(shift_month(requested[0], -len(requested)), shift_month(requested[0], -1))
    previous_archives, missing_previous_months = read_archives(
        archive_root, domain, previous_requested, required=False
    )
    previous_available = not missing_previous_months
    comparison_mode = "complete" if previous_available else "unavailable"
    enrichment_archive_dir = args.dataforseo_archive_dir
    payload = build_dashboard_data(
        archives,
        report_months=None,
        enrichment_archive_dir=enrichment_archive_dir,
        seoagent_archive_dir=args.seoagent_archive_dir,
    )
    if previous_available:
        previous_payload = build_dashboard_data(
            previous_archives,
            report_months=None,
            enrichment_archive_dir=enrichment_archive_dir,
            seoagent_archive_dir=args.seoagent_archive_dir,
        )
        payload["quarterComparison"]["previous"] = previous_payload["quarterComparison"]["current"]
        # A monthly report is a month-over-month view. Keep this separate from
        # the report months so other monthly-only sections do not aggregate two
        # months of traffic, markets, keywords or recommendations.
        if args.type == "monthly":
            payload["comparisonMonths"] = previous_payload["months"] + payload["months"]
    else:
        payload.setdefault("diagnostics", []).append(diagnostic(
            "PREVIOUS_PERIOD_ARCHIVE_MISSING", stage="archive_validation",
            scope={"domain": domain, "report_months": requested},
            detected={"requested_previous_months": previous_requested, "missing_months": missing_previous_months},
            impact="仅生成当前报告期汇总，不展示未经验证的环比或同比结论。",
            next_action="补齐同域官方 GA4/GSC 月度归档后重新生成报告。",
            status="warning",
        ))
    label = args.start_month if args.start_month == end else f"{args.start_month}_to_{end}"
    output_dir = args.output_root / domain / args.type / label
    output_dir.mkdir(parents=True, exist_ok=True)
    current_metrics = payload["quarterComparison"]["current"]["metrics"]
    prior_metrics = (payload["quarterComparison"].get("previous") or {}).get("metrics", {})
    payload["report"] = {
        "type": args.type, "typeLabel": TYPE_LABELS[args.type], "label": label, "domain": domain,
        "rangeLabel": display_range(requested, args.type),
        "selectedMonths": requested,
        "comparison": {
            "label": f"{comparison_labels[args.type]}（{display_range(previous_requested, args.type)}）",
            "available": previous_available,
            "clickDelta": ((current_metrics["clicks"] - prior_metrics["clicks"]) / prior_metrics["clicks"] * 100) if previous_available and prior_metrics.get("clicks") else 0,
            "ctrDelta": ((current_metrics["ctr"] - prior_metrics["ctr"]) / prior_metrics["ctr"] * 100) if previous_available and prior_metrics.get("ctr") else 0,
            "rankDelta": (prior_metrics["averagePosition"] - current_metrics["averagePosition"]) if previous_available else 0,
        },
    }
    payload["report"]["actionPlans"] = build_action_plans(payload["months"], args.type)
    (output_dir / "dashboard-data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html = args.template.read_text(encoding="utf-8")
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    rendered, count = DATA_TAG_RE.subn(lambda match: match.group(1) + embedded + match.group(2), html, count=1)
    if count != 1:
        fail("看板模板中未找到 google-seo-data 数据块")
    (output_dir / "index.html").write_text(standalone_document(rendered + runtime_script()), encoding="utf-8")
    title = f"{domain} {args.type}（{label}）"
    (output_dir / "summary.md").write_text(summary(payload, title, domain), encoding="utf-8")
    validate_report_artifact(output_dir)
    write_usage(
        output_dir, archive_root, record, args.type, label, archives,
        previous_archives if previous_available else [], comparison_mode,
    )
    payload.setdefault("diagnostics", []).extend(validate_report_tree(args.output_root / domain))
    payload["diagnostics"].append(diagnostic(
        "PUBLISH_REVIEW_REQUIRED", stage="publish_review",
        scope={"domain": domain, "report": f"{args.type}/{label}"}, detected={"artifact_validation": "passed"},
        impact="报告仅在本地生成，尚未复制或发布。",
        next_action="人工复核本地 HTML、summary 和诊断后，获得明确发布批准再复制。",
        status="warning", safe_actions=["未改写月度原始归档", "未发布任何客户报告"],
    ))
    diagnostics_dir = write_diagnostics(args.diagnostics_root / domain / args.type / label, payload["diagnostics"])
    print(json.dumps({"output": str(output_dir), "months": requested, "diagnostics": str(diagnostics_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(f"错误: {exc}")
