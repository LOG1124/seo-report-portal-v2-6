#!/usr/bin/env python3
"""Build dashboard-ready monthly SEO data from official GA4/GSC archives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from report_diagnostics import diagnostic
from google_api_collector import ReadyArchive


# ponytail: fixed 2% session tolerance; retain per-query GA4 metadata if a property needs a stricter policy.
MAX_GA4_SESSION_DIMENSION_MISMATCH_RATIO = 0.02


def _load(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return payload


def _path_key(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://local.invalid{value}")
    path = parsed.path or "/"
    return path.rstrip("/") or "/"


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _month_summary(archive: Dict[str, Any], label: str) -> Dict[str, Any]:
    ga4 = archive.get("ga4", {})
    gsc = archive.get("gsc", {})
    index_rows = gsc.get("gsc_index_status", [])
    indexed = sum(1 for row in index_rows if row.get("verdict") == "PASS")
    return {
        "label": label,
        "period": archive.get("period", []),
        "metrics": {
            "clicks": gsc.get("organic_clicks", 0),
            "impressions": gsc.get("organic_impressions", 0),
            "ctr": gsc.get("organic_ctr", 0),
            "averagePosition": gsc.get("average_position", 0),
            "totalUsers": ga4.get("ga4_total_users", 0),
            "pageViews": ga4.get("ga4_page_views", 0),
            "sessions": ga4.get("session_count", 0),
            "averageSessionDuration": ga4.get("ga4_avg_session_duration", 0),
            "averageEngagementTimePerSession": ga4.get("ga4_avg_engagement_time_per_session", 0),
            "bounceRate": ga4.get("ga4_bounce_rate", 0),
            "keyEvents": ga4.get("ga4_key_events", 0),
            "indexedPages": indexed,
            "inspectedPages": len(index_rows),
        },
        "keywords": list(gsc.get("gsc_queries", [])),
        "gscPages": list(gsc.get("gsc_pages", [])),
        "indexStatus": index_rows,
        "ga4Pages": list(ga4.get("ga4_landing_pages", [])),
        "channels": list(ga4.get("ga4_channels", [])),
        "sources": list(ga4.get("ga4_sources", [])),
        "ga4Countries": list(ga4.get("ga4_countries", [])),
        "ga4OrganicSearchCountries": list(ga4.get("ga4_organic_search_countries", [])),
        "countries": list(gsc.get("gsc_countries", [])),
        "gscDaily": list(gsc.get("gsc_daily", [])),
        "ga4Daily": list(ga4.get("ga4_daily", [])),
    }


def _with_keyword_changes(months: List[Dict[str, Any]]) -> None:
    previous: Dict[str, float] = {}
    for month in months:
        current: Dict[str, float] = {}
        for row in month["keywords"]:
            query = str(row.get("query", ""))
            position = _float(row.get("position"))
            prior = previous.get(query)
            row["positionChange"] = round(prior - position, 2) if prior is not None else None
            current[query] = position
        previous = current


def _join_pages(month: Dict[str, Any]) -> List[Dict[str, Any]]:
    ga4_by_path = {_path_key(str(row.get("landingPagePlusQueryString", ""))): row for row in month["ga4Pages"]}
    index_by_url = {str(row.get("page", "")): row for row in month["indexStatus"]}
    joined: List[Dict[str, Any]] = []
    for gsc in month["gscPages"]:
        url = str(gsc.get("page", ""))
        ga4 = ga4_by_path.get(_path_key(url), {})
        index = index_by_url.get(url, {})
        joined.append({
            "page": url,
            "path": _path_key(url),
            "clicks": gsc.get("clicks", 0),
            "impressions": gsc.get("impressions", 0),
            "ctr": gsc.get("ctr", 0),
            "position": gsc.get("position", 0),
            "sessions": ga4.get("sessions", 0),
            "users": ga4.get("totalUsers", 0),
            "views": ga4.get("screenPageViews", 0),
            "bounceRate": round(_float(ga4.get("bounceRate")) * 100, 2),
            "averageSessionDuration": round(_float(ga4.get("averageSessionDuration")), 2),
            "indexVerdict": index.get("verdict", "NOT_INSPECTED"),
            "coverageState": index.get("coverageState", ""),
        })
    return joined


def _recommendations(month: Dict[str, Any]) -> List[Dict[str, str]]:
    metrics = month["metrics"]
    site_ctr = _float(metrics.get("ctr"))
    recommendations: List[Dict[str, str]] = []
    for page in month["pages"]:
        name = page["path"]
        if 0 < _float(page["position"]) <= 10 and _float(page["bounceRate"]) >= 60:
            recommendations.append({"type": "体验", "target": name, "text": "排名靠前但跳出率高，建议优化内容匹配度、首屏信息与内部链接。"})
        if _float(page["impressions"]) >= 20 and _float(page["ctr"]) < site_ctr:
            recommendations.append({"type": "点击率", "target": name, "text": "曝光较高但点击率低，建议优化标题、描述和搜索意图匹配。"})
        if page["indexVerdict"] not in ("PASS", "NOT_INSPECTED"):
            recommendations.append({"type": "索引", "target": name, "text": "URL 检查未通过，建议核对抓取、noindex、规范链接和页面可用性。"})
    for keyword in month["keywords"]:
        position = _float(keyword.get("position"))
        if 10 < position <= 20 and _float(keyword.get("impressions")) >= 3:
            recommendations.append({"type": "排名", "target": str(keyword.get("query", "")), "text": "当前位于第 2 页且已有曝光，适合优先补充内容并强化目标页面相关性。"})
    unique: List[Dict[str, str]] = []
    seen = set()
    for item in recommendations:
        key = (item["type"], item["target"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) == 8:
            break
    return unique


def _quarter_summary(months: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate a three-month reporting period without changing source rows."""
    impressions = sum(_float(month["metrics"].get("impressions")) for month in months)
    clicks = sum(_float(month["metrics"].get("clicks")) for month in months)
    sessions = sum(_float(month["metrics"].get("sessions")) for month in months)
    weighted_position = sum(
        _float(month["metrics"].get("averagePosition")) * _float(month["metrics"].get("impressions"))
        for month in months
    )
    weighted_bounce = sum(
        _float(month["metrics"].get("bounceRate")) * _float(month["metrics"].get("sessions"))
        for month in months
    )
    weighted_duration = sum(
        _float(month["metrics"].get("averageSessionDuration")) * _float(month["metrics"].get("sessions"))
        for month in months
    )
    weighted_engagement = sum(
        _float(month["metrics"].get("averageEngagementTimePerSession")) * _float(month["metrics"].get("sessions"))
        for month in months
    )
    return {
        "months": [month["label"] for month in months],
        "metrics": {
            "clicks": round(clicks, 2),
            "impressions": round(impressions, 2),
            "ctr": round(clicks / impressions * 100, 4) if impressions else 0,
            "averagePosition": round(weighted_position / impressions, 4) if impressions else 0,
            "sessions": round(sessions, 2),
            "totalUsers": round(sum(_float(month["metrics"].get("totalUsers")) for month in months), 2),
            "pageViews": round(sum(_float(month["metrics"].get("pageViews")) for month in months), 2),
            "keyEvents": round(sum(_float(month["metrics"].get("keyEvents")) for month in months), 2),
            "bounceRate": round(weighted_bounce / sessions, 4) if sessions else 0,
            "averageSessionDuration": round(weighted_duration / sessions, 4) if sessions else 0,
            "averageEngagementTimePerSession": round(weighted_engagement / sessions, 4) if sessions else 0,
        },
    }


def _aggregate_ga4_dimension(months: List[Dict[str, Any]], key: str, name_key: str) -> List[Dict[str, Any]]:
    """Aggregate GA4 dimensions from monthly archives without accepting an external total."""
    grouped: Dict[str, Dict[str, Any]] = {}
    for month in months:
        for row in month.get(key, []):
            name = str(row.get(name_key, "") or "Unassigned")
            item = grouped.setdefault(name, {
                name_key: name,
                "sessions": 0.0,
                "keyEvents": 0.0,
                "engagementSeconds": 0.0,
                "engagementSessions": 0.0,
            })
            sessions = _float(row.get("sessions"))
            item["sessions"] += sessions
            item["keyEvents"] += _float(row.get("keyEvents"))
            engagement = _float(row.get("averageEngagementTimePerSession"))
            item["engagementSeconds"] += engagement * sessions
            item["engagementSessions"] += sessions
    rows: List[Dict[str, Any]] = []
    for item in grouped.values():
        sessions = item["sessions"]
        rows.append({
            name_key: item[name_key],
            "sessions": round(sessions, 2),
            "keyEvents": round(item["keyEvents"], 2),
            "averageEngagementTimePerSession": round(
                item["engagementSeconds"] / item["engagementSessions"], 4
            ) if item["engagementSessions"] else 0,
        })
    return sorted(rows, key=lambda row: (-_float(row["sessions"]), str(row[name_key])))


def _report_ga4(
    months: List[Dict[str, Any]], metrics: Dict[str, Any], diagnostics: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Canonical report-period GA4 aggregate derived only from monthly archive rows."""
    channels = _aggregate_ga4_dimension(months, "channels", "sessionDefaultChannelGroup")
    sources = _aggregate_ga4_dimension(months, "sources", "sessionSource")
    channel_sessions = sum(_float(row.get("sessions")) for row in channels)
    channel_events = sum(_float(row.get("keyEvents")) for row in channels)
    expected_sessions = _float(metrics.get("sessions"))
    expected_events = _float(metrics.get("keyEvents"))
    if channels and channel_sessions != expected_sessions:
        difference = channel_sessions - expected_sessions
        difference_ratio = abs(difference) / expected_sessions if expected_sessions else float("inf")
        if difference_ratio > MAX_GA4_SESSION_DIMENSION_MISMATCH_RATIO:
            raise ValueError(
                "GA4 渠道会话合计与报告期会话差异超过允许范围："
                f"{channel_sessions} != {expected_sessions} ({difference_ratio:.2%})"
            )
        diagnostics.append(diagnostic(
            "GA4_CHANNEL_SESSION_TOTAL_MISMATCH", stage="aggregation",
            scope={"months": [month.get("label") for month in months]},
            detected={
                "total_sessions": expected_sessions,
                "channel_sessions": channel_sessions,
                "difference": difference,
                "difference_ratio": difference_ratio,
                "allowed_ratio": MAX_GA4_SESSION_DIMENSION_MISMATCH_RATIO,
            },
            impact="GA4 总会话和渠道行均保留官方原值；小幅近似计数差异不再阻断报告生成。",
            next_action="若后续差异超过 2%，请核对 GA4 查询范围、分页和响应元数据。",
            status="warning",
            safe_actions=("未改写原始归档", "未调整 GA4 官方指标"),
        ))
    if channels and channel_events != expected_events:
        raise ValueError(f"GA4 渠道关键事件合计与报告期关键事件不一致：{channel_events} != {expected_events}")
    return {
        "period": [months[0]["period"][0], months[-1]["period"][-1]] if months else [],
        "sessions": metrics.get("sessions", 0),
        "keyEvents": metrics.get("keyEvents", 0),
        "averageEngagementTimePerSession": metrics.get("averageEngagementTimePerSession", 0),
        "channels": channels,
        "sources": sources,
    }


def _market_keywords(enrichment: Dict[str, Any]) -> List[Dict[str, Any]]:
    search_volume = {
        str(row.get("keyword", "")): row
        for row in enrichment.get("search_volume", {}).get("keywords", [])
        if str(row.get("keyword", ""))
    }
    rows: List[Dict[str, Any]] = []
    for selected in enrichment.get("selected_keywords", []):
        query = str(selected.get("query", ""))
        if not query:
            continue
        rows.append({**selected, **search_volume.get(query, {}) , "query": query})
    return rows


def _enrich_month(
    month: Dict[str, Any], archive: Dict[str, Any], label: str,
    enrichment_archive_dir: Optional[Path], diagnostics: List[Dict[str, Any]], expected_report_months: Optional[List[str]],
) -> None:
    month["marketKeywords"] = []
    month["serpDetail"] = None
    if enrichment_archive_dir is None:
        return
    path = enrichment_archive_dir / f"{label}.json"
    if not path.exists():
        return
    enrichment = _load(path)
    allowed_queries = {str(row.get("query", "")).strip() for row in month.get("keywords", []) if row.get("query")}
    selected_queries = {str(row.get("query", "")).strip() for row in enrichment.get("selected_keywords", []) if isinstance(row, dict) and row.get("query")}
    market = enrichment.get("market")
    valid = (
        enrichment.get("domain") == archive.get("domain")
        and enrichment.get("month") == label
        and isinstance(market, dict)
        and bool(market.get("location_code"))
        and bool(market.get("language_code"))
        and bool(selected_queries)
        and selected_queries.issubset(allowed_queries)
        and (expected_report_months is None or (
            enrichment.get("reporting_period") == expected_report_months
            and enrichment.get("approval", {}).get("approved") is True
        ))
    )
    if not valid:
        diagnostics.append(diagnostic(
            "DATAFORSEO_ARCHIVE_SCOPE_MISMATCH", stage="extension_validation",
            scope={"domain": archive.get("domain"), "month": label},
            detected={"archive": path.name, "archive_domain": enrichment.get("domain"), "archive_month": enrichment.get("month"), "selected_keywords": sorted(selected_queries)},
            impact="已隐藏 DataForSEO 市场机会模块；GSC/GA4 官方指标未改变。",
            next_action="核对归档域名、月份、市场、语言和 GSC 已选词后重新导入。",
            status="warning",
        ))
        return
    month["marketKeywords"] = _market_keywords(enrichment)
    month["serpDetail"] = enrichment.get("serp")


def _normalise_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _is_local_intent(keyword: Any) -> bool:
    return "near me" in _normalise_text(keyword)


def _domain_brand_token(domain: Any) -> str:
    root = str(domain or "").split(".", 1)[0]
    return re.sub(r"[^a-z0-9]+", "", root.lower())


def _is_candidate_brand_keyword(keyword: Any, competitor_domain: Any) -> bool:
    token = _domain_brand_token(competitor_domain)
    normalised = re.sub(r"[^a-z0-9]+", "", _normalise_text(keyword))
    return bool(token and normalised and token in normalised)


def _strategy_row(row: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    dashboard_key = {
        "current_rank": "currentRank",
        "matched_url": "matchedUrl",
        "recommended_page_type": "pageType",
        "page_type": "pageType",
        "traffic_estimate": "trafficEstimate",
    }
    return {dashboard_key.get(key, key): row.get(key) for key in keys}


def _normalise_strategy_opportunities(raw: Dict[str, Any]) -> Dict[str, Any]:
    responses = raw.get("responses", {})
    opportunities = responses.get("domain_keyword_opportunities", {}).get("keywords", [])
    priority_rows = [
        _strategy_row(row, "keyword", "current_rank", "matched_url", "recommendation", "recommended_page_type", "intent")
        for row in opportunities
        if row.get("priority") == "P1" and not _is_local_intent(row.get("keyword"))
    ][:2]
    ranked_rows = sorted(
        responses.get("domain_keywords", {}).get("keywords", []),
        key=lambda row: _float(row.get("rank")) or float("inf"),
    )[:5]
    domain_keywords = [
        _strategy_row(row, "keyword", "rank", "url", "traffic_estimate")
        for row in ranked_rows
        if row.get("keyword") and row.get("rank")
    ]
    competitors = responses.get("competitor_keyword_strategy", {}).get("competitors", [])
    competitor_domains = {str(row.get("domain", "")): row for row in competitors if row.get("domain")}
    directions: List[Dict[str, Any]] = []
    for row in responses.get("competitor_keyword_strategy", {}).get("keywords", []):
        domain = str(row.get("competitor", row.get("competitorDomain", "")))
        keyword = row.get("keyword")
        if not domain or domain not in competitor_domains or not keyword:
            continue
        if _is_local_intent(keyword) or _is_candidate_brand_keyword(keyword, domain):
            continue
        if _normalise_text(row.get("intent")) not in {"commercial", "transactional"}:
            continue
        directions.append({
            "competitor": domain,
            "keyword": keyword,
            "intent": row.get("intent"),
            "pageType": row.get("page_type", row.get("pageType", "")),
        })

    scope = raw.get("query_scope", {})
    return {
        "archiveMonth": raw.get("collection_month", ""),
        "collectedAt": raw.get("collected_at", ""),
        "location": scope.get("location", ""),
        "language": scope.get("language", ""),
        "disclaimer": "第三方策略发现，不替代 GSC / GA4 / DataForSEO 核心指标。候选竞品，尚未确认。",
        "priorityOpportunities": priority_rows,
        "domainKeywords": domain_keywords,
        "competitorDirections": directions[:6],
    }


def _load_seoagent_strategy_archive(
    archive_dir: Optional[Path], domain: str, report_months: List[str], diagnostics: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if archive_dir is None or not archive_dir.exists():
        return None
    scope_mismatch = None
    for path in sorted(archive_dir.glob("*.json"), reverse=True):
        try:
            raw = _load(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if raw.get("provider") != "seoagent" or raw.get("domain") != domain or raw.get("status") != "complete":
            continue
        strategy = _normalise_strategy_opportunities(raw)
        if (
            strategy["archiveMonth"] not in report_months or not strategy["location"] or not strategy["language"]
            or raw.get("reporting_period") != report_months
            or raw.get("approval", {}).get("approved") is not True
        ):
            scope_mismatch = {"archive": path.name, "collection_month": strategy["archiveMonth"], "location": strategy["location"], "language": strategy["language"]}
            continue
        if strategy["archiveMonth"] and (strategy["priorityOpportunities"] or strategy["domainKeywords"] or strategy["competitorDirections"]):
            return strategy
    if scope_mismatch:
        diagnostics.append(diagnostic(
            "SEOAGENT_ARCHIVE_SCOPE_MISMATCH", stage="extension_validation",
            scope={"domain": domain, "report_months": report_months}, detected=scope_mismatch,
            impact="已隐藏 SEOAgent 策略机会模块；GSC/GA4 官方指标未改变。",
            next_action="导入同域、报告期内且标明市场和语言的完整 SEOAgent 归档。",
            status="warning",
        ))
    return None


def build_dashboard_data(
    archives: Iterable[Path | ReadyArchive], *, report_months: Optional[int] = 3,
    enrichment_archive_dir: Optional[Path] = None,
    seoagent_archive_dir: Optional[Path] = None,
    expected_report_months: Optional[List[str]] = None,
) -> Dict[str, Any]:
    all_months = []
    source_domain = ""
    diagnostics: List[Dict[str, Any]] = []
    for source in sorted(archives, key=lambda item: str(item.path if isinstance(item, ReadyArchive) else item)):
        path = source.path if isinstance(source, ReadyArchive) else Path(source)
        archive = source.payload if isinstance(source, ReadyArchive) else _load(path)
        archived_domain = str(archive.get("domain", "")).strip()
        if not archived_domain:
            raise ValueError(f"归档缺少域名：{path.name}")
        if source_domain and archived_domain != source_domain:
            raise ValueError(f"归档域名不一致：{path.name} 属于 {archived_domain}，不是 {source_domain}")
        source_domain = source_domain or archived_domain
        month = _month_summary(archive, path.stem)
        _enrich_month(month, archive, path.stem, enrichment_archive_dir, diagnostics, expected_report_months)
        all_months.append(month)
    _with_keyword_changes(all_months)
    for month in all_months:
        month["pages"] = _join_pages(month)
        month["recommendations"] = _recommendations(month)
        for key in ("gscPages", "ga4Pages", "indexStatus"):
            month.pop(key, None)
    selected_months = all_months[-report_months:] if report_months else all_months
    previous_months = (
        all_months[-report_months * 2:-report_months]
        if report_months and len(all_months) >= report_months * 2
        else []
    )
    current_summary = _quarter_summary(selected_months)
    payload = {
        "source": "Google Search Console + Google Analytics 4",
        "months": selected_months,
        "quarterComparison": {
            "current": current_summary,
            "previous": _quarter_summary(previous_months) if report_months and len(previous_months) == report_months else None,
        },
        "reportGa4": _report_ga4(selected_months, current_summary["metrics"], diagnostics),
        "diagnostics": diagnostics,
    }
    strategy = _load_seoagent_strategy_archive(seoagent_archive_dir, source_domain, [month["label"] for month in selected_months], diagnostics)
    if strategy:
        payload["strategyOpportunities"] = strategy
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="旧版看板数据入口（已禁用）")
    parser.add_argument("--archive-dir", help=argparse.SUPPRESS)
    parser.add_argument("--output", help=argparse.SUPPRESS)
    parser.add_argument("--all-months", action="store_true", help=argparse.SUPPRESS)
    parser.parse_args()
    parser.error(
        "此入口已禁用，避免 --archive-dir 绕过 v2.3 共享原始档案校验；"
        "请改用 generate_dashboard_report.py --archive-root <shared-source-root>。"
    )


if __name__ == "__main__":
    raise SystemExit(main())
