#!/usr/bin/env python3
"""Collect read-only GA4 and Google Search Console data via Google APIs."""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import socket
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

from collection import CollectedDataStore, ProjectContext, normalized_domain
from customer_registry import google_archive_path, require_active_customer


GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA4_SOURCE_URL = "https://analyticsdata.googleapis.com/"
GSC_SOURCE_URL = "https://www.googleapis.com/webmasters/v3/"

CHANNEL_NAMES = {
    "Direct": "直接访问",
    "Organic Search": "自然搜索",
    "Paid Search": "付费搜索",
    "Organic Social": "自然社交",
    "Paid Social": "付费社交",
    "Referral": "引荐流量",
    "Email": "电子邮件",
    "Display": "展示广告",
    "Cross-network": "跨网络",
    "Organic Video": "自然视频",
    "Unassigned": "未分配",
}

CANONICAL_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")


class SearchConsoleRestClient:
    """Small authenticated REST client that avoids discovery-document timeouts."""

    def __init__(self, credentials: Any, timeout: int = 60):
        from google.auth.transport.requests import AuthorizedSession

        self.session = AuthorizedSession(credentials)
        self.timeout = timeout

    def query_search_analytics(self, site_url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        encoded_site = quote(site_url, safe="")
        url = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query"
        response = self.session.post(url, json=body, timeout=self.timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"GSC API {response.status_code}: {response.text[:1200]}")
        return response.json()

    def inspect_url(self, site_url: str, inspection_url: str) -> Dict[str, Any]:
        response = self.session.post(
            "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
            json={"inspectionUrl": inspection_url, "siteUrl": site_url, "languageCode": "zh-CN"},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"URL Inspection API {response.status_code}: {response.text[:1200]}")
        return response.json()


def _load_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return payload


def _credential_path(config: Dict[str, Any], config_path: Path) -> Path:
    configured = str(config.get("credentials_file", "")).strip()
    environment = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    value = environment or configured
    if not value:
        raise ValueError("缺少 Google 凭据：请设置 GOOGLE_APPLICATION_CREDENTIALS 或 credentials_file")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        raise FileNotFoundError(f"Google 服务账号凭据不存在: {path}")
    return path


def _validate_credential_identity(credentials_file: Path, expected_email: str) -> None:
    payload = _load_object(credentials_file)
    if payload.get("type") != "service_account":
        raise ValueError("Google 凭据文件不是 service_account 类型")
    actual_email = str(payload.get("client_email", "")).strip().lower()
    expected = expected_email.strip().lower()
    if not expected:
        raise ValueError("google_api.json 缺少 service_account_email")
    if actual_email != expected:
        raise ValueError(f"服务账号不匹配：配置为 {expected}，密钥属于 {actual_email or '未知账号'}")


def build_clients(credentials_file: Path, *, ga4: bool, gsc: bool) -> Tuple[Any, Any]:
    """Build Google clients lazily so unit tests do not require Google SDKs."""
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError("缺少 google-auth；请先安装 requirements.txt") from exc

    scopes = [scope for enabled, scope in ((ga4, GA4_SCOPE), (gsc, GSC_SCOPE)) if enabled]
    credentials = service_account.Credentials.from_service_account_file(
        str(credentials_file), scopes=scopes
    )
    ga4_client = None
    gsc_client = None
    if ga4:
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
        except ImportError as exc:
            raise RuntimeError("缺少 google-analytics-data；请先安装 requirements.txt") from exc
        # REST avoids common gRPC/TLS handshake failures on macOS and restricted networks.
        ga4_client = BetaAnalyticsDataClient(credentials=credentials, transport="rest")
    if gsc:
        gsc_client = SearchConsoleRestClient(credentials)
    return ga4_client, gsc_client


def _number(value: str) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else round(number, 6)


def _ga4_report(
    client: Any,
    property_id: str,
    start: str,
    end: str,
    dimensions: Sequence[str],
    metrics: Sequence[str],
    limit: int,
) -> List[Dict[str, Any]]:
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name=name) for name in dimensions],
        metrics=[Metric(name=name) for name in metrics],
        limit=limit,
    )
    response = client.run_report(request=request)
    rows: List[Dict[str, Any]] = []
    for row in response.rows:
        item: Dict[str, Any] = {}
        for index, name in enumerate(dimensions):
            item[name] = row.dimension_values[index].value
        for index, name in enumerate(metrics):
            item[name] = _number(row.metric_values[index].value)
        rows.append(item)
    return rows


def _add_average_engagement_per_session(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Match GA4 Traffic acquisition's average engagement time per session."""
    for row in rows:
        sessions = float(row.get("sessions", 0) or 0)
        engagement_seconds = float(row.get("userEngagementDuration", 0) or 0)
        row["averageEngagementTimePerSession"] = round(engagement_seconds / sessions, 2) if sessions else 0
    return rows


def collect_ga4(
    client: Any,
    property_id: str,
    start: str,
    end: str,
    row_limit: int = 1000,
) -> Dict[str, Any]:
    if not property_id.strip().isdigit():
        raise ValueError("GA4 property_id 必须是纯数字属性 ID")
    row_limit = max(1, min(int(row_limit), 100000))

    totals = _ga4_report(
        client,
        property_id,
        start,
        end,
        [],
        ["sessions", "engagedSessions", "totalUsers", "screenPageViews", "averageSessionDuration", "userEngagementDuration", "bounceRate", "keyEvents"],
        1,
    )
    if not totals:
        raise ValueError("GA4 在指定周期内没有返回汇总数据")
    quality_metrics = ["sessions", "engagedSessions", "totalUsers", "screenPageViews", "averageSessionDuration", "userEngagementDuration", "bounceRate", "keyEvents"]
    channels = _ga4_report(client, property_id, start, end, ["sessionDefaultChannelGroup"], quality_metrics, row_limit)
    sources = _ga4_report(client, property_id, start, end, ["sessionSource"], quality_metrics, row_limit)
    countries = _ga4_report(client, property_id, start, end, ["country"], ["sessions", "totalUsers", "engagedSessions"], row_limit)
    organic_search_countries = _ga4_report(client, property_id, start, end, ["country"], ["organicGoogleSearchClicks"], row_limit)
    landing_pages = _ga4_report(client, property_id, start, end, ["landingPagePlusQueryString"], quality_metrics, row_limit)
    devices = _ga4_report(client, property_id, start, end, ["deviceCategory"], quality_metrics, row_limit)
    daily = _ga4_report(client, property_id, start, end, ["date"], quality_metrics, row_limit)

    for report_rows in (totals, channels, sources, countries, landing_pages, devices, daily):
        _add_average_engagement_per_session(report_rows)

    by_sessions = lambda rows: sorted(rows, key=lambda item: float(item.get("sessions", 0)), reverse=True)
    channels = by_sessions(channels)
    sources = by_sessions(sources)
    countries = by_sessions(countries)
    organic_search_countries.sort(key=lambda item: float(item.get("organicGoogleSearchClicks", 0) or 0), reverse=True)
    landing_pages = by_sessions(landing_pages)
    devices = by_sessions(devices)
    daily.sort(key=lambda item: str(item.get("date", "")))

    primary_raw = str(channels[0]["sessionDefaultChannelGroup"]) if channels else "未分配"
    secondary_raw = str(channels[1]["sessionDefaultChannelGroup"]) if len(channels) > 1 else "未分配"
    return {
        "session_count": int(totals[0]["sessions"]),
        "engaged_session_count": int(totals[0]["engagedSessions"]),
        "ga4_total_users": int(totals[0].get("totalUsers", 0)),
        "ga4_page_views": int(totals[0].get("screenPageViews", 0)),
        "ga4_avg_session_duration": round(float(totals[0].get("averageSessionDuration", 0)), 2),
        "ga4_avg_engagement_time_per_session": round(float(totals[0].get("averageEngagementTimePerSession", 0)), 2),
        "ga4_bounce_rate": round(float(totals[0].get("bounceRate", 0)) * 100, 2),
        "ga4_key_events": int(totals[0].get("keyEvents", 0)),
        "traffic_primary_channel": CHANNEL_NAMES.get(primary_raw, primary_raw),
        "traffic_secondary_channel": CHANNEL_NAMES.get(secondary_raw, secondary_raw),
        "session_top_source": str(sources[0]["sessionSource"]) if sources else "未分配",
        "country_region_count": len(countries),
        "top_country_region": str(countries[0]["country"]) if countries else "未分配",
        "ga4_channels": channels,
        "ga4_sources": sources,
        "ga4_countries": countries,
        "ga4_organic_search_countries": organic_search_countries,
        "ga4_landing_pages": landing_pages,
        "ga4_devices": devices,
        "ga4_daily": daily,
        "_raw_channels": {"primary": primary_raw, "secondary": secondary_raw},
    }


def _gsc_query(
    service: Any,
    site_url: str,
    start: str,
    end: str,
    dimensions: Optional[Sequence[str]] = None,
    row_limit: int = 25000,
) -> List[Dict[str, Any]]:
    body: Dict[str, Any] = {
        "startDate": start,
        "endDate": end,
        "type": "web",
        "dataState": "final",
        "rowLimit": max(1, min(int(row_limit), 25000)),
    }
    if dimensions:
        body["dimensions"] = list(dimensions)
    if hasattr(service, "query_search_analytics"):
        response = service.query_search_analytics(site_url, body)
    else:
        response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows: List[Dict[str, Any]] = []
    for row in response.get("rows", []):
        item = {
            "clicks": _number(row.get("clicks", 0)),
            "impressions": _number(row.get("impressions", 0)),
            "ctr": round(float(row.get("ctr", 0)) * 100, 4),
            "position": round(float(row.get("position", 0)), 4),
        }
        for index, name in enumerate(dimensions or []):
            item[name] = row.get("keys", [])[index]
        rows.append(item)
    return rows


def _page_type(url: str) -> str:
    from urllib.parse import urlparse

    path = urlparse(url).path.strip("/")
    if not path:
        return "主页"
    if path.lower().endswith(".pdf"):
        return "PDF"
    return "产品或内容页"


def collect_gsc(
    service: Any,
    site_url: str,
    expected_domain: str,
    start: str,
    end: str,
    row_limit: int = 25000,
    inspection_limit: int = 20,
) -> Dict[str, Any]:
    value = site_url.removeprefix("sc-domain:")
    if normalized_domain(value) != expected_domain:
        raise ValueError(f"GSC 资源域名不匹配：当前项目为 {expected_domain}，配置为 {site_url}")

    summary = _gsc_query(service, site_url, start, end, row_limit=1)
    if not summary:
        raise ValueError("GSC 在指定周期内没有返回效果数据")
    queries = _gsc_query(service, site_url, start, end, ["query"], row_limit)
    pages = _gsc_query(service, site_url, start, end, ["page"], row_limit)
    countries = _gsc_query(service, site_url, start, end, ["country"], row_limit)
    devices = _gsc_query(service, site_url, start, end, ["device"], row_limit)
    daily = _gsc_query(service, site_url, start, end, ["date"], row_limit)
    daily.sort(key=lambda item: str(item.get("date", "")))

    index_status: List[Dict[str, Any]] = []
    if hasattr(service, "inspect_url"):
        for page in pages[:max(0, min(int(inspection_limit), 50))]:
            page_url = str(page.get("page", ""))
            try:
                response = service.inspect_url(site_url, page_url)
                inspection = response.get("inspectionResult", {})
                status = inspection.get("indexStatusResult", {})
                index_status.append({
                    "page": page_url,
                    "verdict": status.get("verdict", "VERDICT_UNSPECIFIED"),
                    "coverageState": status.get("coverageState", ""),
                    "indexingState": status.get("indexingState", ""),
                    "pageFetchState": status.get("pageFetchState", ""),
                    "lastCrawlTime": status.get("lastCrawlTime", ""),
                    "googleCanonical": status.get("googleCanonical", ""),
                    "userCanonical": status.get("userCanonical", ""),
                    "inspectionResultLink": inspection.get("inspectionResultLink", ""),
                })
            except Exception as exc:
                index_status.append({"page": page_url, "verdict": "ERROR", "error": str(exc)[:300]})

    top_page_types: List[str] = []
    for page in pages:
        page_type = _page_type(str(page.get("page", "")))
        if page_type not in top_page_types:
            top_page_types.append(page_type)
        if len(top_page_types) == 2:
            break
    while len(top_page_types) < 2:
        top_page_types.append("其他页面")

    total = summary[0]
    return {
        "organic_clicks": int(total["clicks"]),
        "organic_impressions": int(total["impressions"]),
        "organic_ctr": round(float(total["ctr"]), 2),
        "average_position": round(float(total["position"]), 2),
        "ranked_keyword_count": len(queries),
        "top_landing_page_type": top_page_types[0],
        "second_landing_page_type": top_page_types[1],
        "gsc_queries": queries,
        "gsc_pages": pages,
        "gsc_countries": countries,
        "gsc_devices": devices,
        "gsc_daily": daily,
        "gsc_index_status": index_status,
    }


def _record_fields(store: CollectedDataStore, fields: Dict[str, Any], source_name: str, source_url: str) -> List[str]:
    recorded: List[str] = []
    raw_channels = fields.get("_raw_channels", {})
    for field, value in fields.items():
        if field.startswith("_"):
            continue
        raw_value = None
        if field == "traffic_primary_channel":
            raw_value = raw_channels.get("primary")
        elif field == "traffic_secondary_channel":
            raw_value = raw_channels.get("secondary")
        store.record(
            field,
            value,
            source_type="api",
            source_name=source_name,
            source_url=source_url,
            raw_value=raw_value,
        )
        recorded.append(field)
    return recorded


def _period_from_args(context: ProjectContext, month: Optional[str], start: Optional[str], end: Optional[str]) -> Tuple[str, str, str]:
    if month:
        try:
            year, month_number = (int(part) for part in month.split("-", 1))
            last_day = calendar.monthrange(year, month_number)[1]
        except (ValueError, TypeError) as exc:
            raise ValueError("--month 必须使用 YYYY-MM 格式") from exc
        return f"{year:04d}-{month_number:02d}-01", f"{year:04d}-{month_number:02d}-{last_day:02d}", f"{year:04d}-{month_number:02d}"
    start_value = start or context.report_start
    end_value = end or context.report_end
    start_date = date.fromisoformat(start_value)
    end_date = date.fromisoformat(end_value)
    if end_date < start_date:
        raise ValueError("采集结束日期不能早于开始日期")
    return start_value, end_value, f"{start_value}_to_{end_value}"


def month_dates(month: str) -> List[str]:
    """Return the inclusive start and end dates for one calendar month."""
    try:
        if not isinstance(month, str) or not CANONICAL_MONTH_RE.fullmatch(month):
            raise ValueError
        year, month_number = (int(part) for part in month.split("-", 1))
        last_day = calendar.monthrange(year, month_number)[1]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("月份格式必须为 YYYY-MM") from exc
    return [f"{year:04d}-{month_number:02d}-01", f"{year:04d}-{month_number:02d}-{last_day:02d}"]


def _custom_date_range(start: str, end: str) -> tuple[date, date]:
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("自定义日期必须是 YYYY-MM-DD") from exc
    if end_date < start_date:
        raise ValueError("采集结束日期不能早于开始日期")
    return start_date, end_date


def custom_google_archive_path(archive_root: Path, domain: str, start: str, end: str) -> Path:
    """Return the isolated immutable path for one exact inclusive date range."""
    _custom_date_range(start, end)
    record = require_active_customer(archive_root, domain)
    return Path(archive_root) / "ga4-gsc" / record.canonical_domain / "custom" / f"{start}_to_{end}.json"


def validate_custom_date_archive(
    archive_root: Path, domain: str, start: str, end: str, payload: Dict[str, Any]
) -> Path:
    record = require_active_customer(archive_root, domain)
    path = custom_google_archive_path(archive_root, record.canonical_domain, start, end)
    if payload.get("domain") != record.canonical_domain:
        raise ValueError("归档域名不匹配")
    if payload.get("period") != [start, end]:
        raise ValueError("归档周期必须与指定自定义日期完全一致")
    for platform in ("ga4", "gsc"):
        if not isinstance(payload.get(platform), dict) or not payload[platform]:
            raise ValueError("归档必须同时包含非空的 GA4 与 GSC 数据")
    return path


def validate_complete_month_archive(
    archive_root: Path, domain: str, month: str, payload: Dict[str, Any]
) -> tuple[Any, Path]:
    """Validate the identity and complete first-party payload for one source month."""
    record = require_active_customer(archive_root, domain)
    path = google_archive_path(archive_root, record, month)
    expected_period = month_dates(month)
    if payload.get("domain") != record.canonical_domain:
        raise ValueError("归档域名不匹配")
    if payload.get("period") != expected_period:
        raise ValueError("归档周期必须是指定自然月")
    for platform in ("ga4", "gsc"):
        section = payload.get(platform)
        if not isinstance(section, dict) or not section:
            raise ValueError("归档必须同时包含非空的 GA4 与 GSC 数据")
    return record, path


READY_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReadyArchive:
    """One verified, in-memory source archive snapshot."""

    record: Any
    path: Path
    content: bytes
    sha256: str
    payload: Dict[str, Any]


def ready_path(path: Path) -> Path:
    """Return the non-public digest marker that makes a source archive readable."""
    return Path(path).with_suffix(".json.ready")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _exclusive_write(path: Path, content: bytes, *, exists_message: str) -> None:
    """Create one file once and flush its full bytes before the caller proceeds."""
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError(exists_message) from exc


def read_ready_archive_bytes(path: Path) -> tuple[bytes, str]:
    """Read one JSON snapshot and accept it only when its ready marker matches it."""
    path = Path(path)
    ready = ready_path(path)
    if not path.is_file():
        if ready.exists():
            raise ValueError(f"原始档案 ready 标记缺少 JSON：{ready}")
        raise FileNotFoundError(f"缺少月度归档：{path}")
    if not ready.is_file():
        raise ValueError(f"原始档案尚未就绪或 ready 标记异常：{path}")
    try:
        marker = json.loads(ready.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"原始档案 ready 标记无效：{ready}") from exc
    expected = marker.get("sha256") if isinstance(marker, dict) else None
    if not isinstance(expected, str) or not READY_SHA256_RE.fullmatch(expected):
        raise ValueError(f"原始档案 ready 标记无效：{ready}")
    content = path.read_bytes()
    actual = _sha256_bytes(content)
    if actual != expected:
        raise ValueError(f"原始档案 ready SHA-256 不一致：{path}")
    return content, actual


def verify_ready_archive(path: Path) -> str:
    """Return a source digest only when its non-public ready marker proves its bytes."""
    _, digest = read_ready_archive_bytes(path)
    return digest


def read_ready_complete_month_archive(archive_root: Path, domain: str, month: str) -> ReadyArchive:
    """Return one ready, registered, complete natural-month archive without reopening it."""
    root = Path(archive_root).resolve()
    record = require_active_customer(root, domain)
    path = google_archive_path(root, record, month)
    content, digest = read_ready_archive_bytes(path)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"原始档案 JSON 无效：{path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("归档 JSON 必须是对象")
    validate_complete_month_archive(root, record.canonical_domain, month, payload)
    return ReadyArchive(record, path, content, digest, payload)


def read_ready_custom_date_archive(archive_root: Path, domain: str, start: str, end: str) -> ReadyArchive:
    """Return one ready, registered exact-date source archive without reopening it."""
    root = Path(archive_root).resolve()
    record = require_active_customer(root, domain)
    path = custom_google_archive_path(root, record.canonical_domain, start, end)
    if not path.is_file() and not path.with_suffix(".json.ready").exists():
        raise FileNotFoundError(f"缺少自定义日期归档：{path}")
    content, digest = read_ready_archive_bytes(path)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"原始档案 JSON 无效：{path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("归档 JSON 必须是对象")
    validate_custom_date_archive(root, record.canonical_domain, start, end, payload)
    return ReadyArchive(record, path, content, digest, payload)


def _lock_payload() -> bytes:
    return (json.dumps({
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, ensure_ascii=False) + "\n").encode("utf-8")


def _ready_payload(content: bytes) -> bytes:
    return (json.dumps({"sha256": _sha256_bytes(content)}, ensure_ascii=False) + "\n").encode("utf-8")


def _reject_existing_archive_state(path: Path) -> None:
    """Never overwrite a completed archive or attempt to repair an incomplete one."""
    ready = ready_path(path)
    if path.exists() and ready.exists():
        verify_ready_archive(path)
        raise FileExistsError(f"档案已存在，未改写：{path}")
    if path.exists():
        raise ValueError(f"原始档案缺少 ready 标记，需维护负责人处理：{path}")
    if ready.exists():
        raise ValueError(f"原始档案 ready 标记缺少 JSON，需维护负责人处理：{ready}")


def write_new_archive_bytes(path: Path, content: bytes) -> Path:
    """Create an immutable archive, then its digest marker, under a provenance lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".json.lock")
    lock_acquired = False
    committed = False
    preserve_lock = False
    try:
        _exclusive_write(lock, _lock_payload(), exists_message=f"该月份正在归档或需人工检查锁文件：{lock}")
        lock_acquired = True
        _reject_existing_archive_state(path)
        # Once exclusive creation starts, a failed SMB write can leave a partial
        # JSON. Retain the provenance lock so it cannot be mistaken for usable.
        preserve_lock = True
        try:
            _exclusive_write(path, content, exists_message=f"档案已存在，未改写：{path}")
        except FileExistsError:
            try:
                _reject_existing_archive_state(path)
            except FileExistsError:
                preserve_lock = False
                raise
            raise
        # A JSON without this marker is intentionally unreadable. Keep its lock
        # if marker creation fails so a maintainer can inspect the exact state.
        preserve_lock = True
        _exclusive_write(
            ready_path(path), _ready_payload(content),
            exists_message=f"原始档案 ready 标记已存在，需维护负责人处理：{ready_path(path)}",
        )
        committed = True
        return path
    finally:
        if committed:
            try:
                lock.unlink(missing_ok=True)
            except OSError as exc:
                print(
                    f"警告：原始档案已提交：{path}；无法清理 {lock}（{exc}）。"
                    "保留锁供维护负责人按目标已存在流程复核。",
                    file=sys.stderr,
                )
        elif lock_acquired and (not preserve_lock or not path.exists()):
            lock.unlink(missing_ok=True)


def save_new_month_archive(archive_root: Path, domain: str, month: str, payload: Dict[str, Any]) -> Path:
    """Write one complete domain-isolated Google archive once, without replacing it."""
    _, path = validate_complete_month_archive(archive_root, domain, month, payload)
    archived_payload = dict(payload)
    archived_payload["archived_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    content = (json.dumps(archived_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return write_new_archive_bytes(path, content)


def save_new_custom_archive(archive_root: Path, domain: str, start: str, end: str, payload: Dict[str, Any]) -> Path:
    """Write one exact-date Google archive once, without touching monthly archives."""
    path = validate_custom_date_archive(archive_root, domain, start, end, payload)
    archived_payload = dict(payload)
    archived_payload["archived_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    content = (json.dumps(archived_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return write_new_archive_bytes(path, content)


def collect_custom_archive_from_project(
    archive_root: Path, config_path: Path, project_input: Path, start: str, end: str
) -> Path:
    """Collect one authorized exact range into its isolated archive, without local dashboard writes."""
    _custom_date_range(start, end)
    config = _load_object(config_path)
    context = ProjectContext.from_file(project_input)
    credentials_file = _credential_path(config, config_path)
    _validate_credential_identity(credentials_file, str(config.get("service_account_email", "")))
    ga4_client, gsc_client = build_clients(credentials_file, ga4=True, gsc=True)
    ga4_config, gsc_config = config.get("ga4", {}), config.get("gsc", {})
    payload = {
        "domain": context.domain, "period": [start, end],
        "ga4": {field: value for field, value in collect_ga4(
            ga4_client, str(ga4_config.get("property_id", "")), start, end,
            int(ga4_config.get("row_limit", 1000)),
        ).items() if not field.startswith("_")},
        "gsc": collect_gsc(
            gsc_client, str(gsc_config.get("site_url", "")), context.domain, start, end,
            int(gsc_config.get("row_limit", 25000)), int(gsc_config.get("inspection_limit", 20)),
        ),
    }
    return save_new_custom_archive(archive_root, context.domain, start, end, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="通过只读 API 采集 GA4 与 Google Search Console 数据")
    parser.add_argument("--platform", choices=("all", "ga4", "gsc"), default="all")
    parser.add_argument("--config", default="workflows/automation/config/google_api.json")
    parser.add_argument("--project-input", default="workflows/automation/config/project_input.json")
    parser.add_argument("--collected-data", default="workflows/automation/input/collected_data.json")
    parser.add_argument("--archive-root", type=Path, required=True, help="共享原始档案根目录")
    parser.add_argument("--month", help="按自然月采集并归档，格式 YYYY-MM")
    parser.add_argument("--start", help="自定义开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="自定义结束日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="调用 API 并输出摘要，不写入 collected_data.json 或原始档案")
    parser.add_argument("--archive-only", action="store_true", help="写入月度归档，但不改写 collected_data.json")
    args = parser.parse_args()
    custom_dates = bool(args.start or args.end)
    if args.month and custom_dates:
        parser.error("--month 不能与 --start/--end 同时使用")
    if custom_dates and (not args.start or not args.end):
        parser.error("自定义日期归档必须同时提供 --start YYYY-MM-DD 和 --end YYYY-MM-DD")
    if not args.dry_run and not args.month and not custom_dates:
        parser.error("非 --dry-run 模式必须提供 --month 或完整的 --start/--end 日期范围")
    if not args.dry_run and args.platform != "all":
        parser.error("共享原始档案必须同时采集 GA4 与 GSC；单平台仅可用于 --dry-run")
    if args.month:
        try:
            month_dates(args.month)
        except ValueError as exc:
            parser.error(str(exc))
    elif custom_dates:
        try:
            _custom_date_range(args.start, args.end)
        except ValueError as exc:
            parser.error(str(exc))

    config_path = Path(args.config)
    config = _load_object(config_path)
    context = ProjectContext.from_file(Path(args.project_input))
    period_start, period_end, archive_label = _period_from_args(context, args.month, args.start, args.end)
    use_ga4 = args.platform in ("all", "ga4")
    use_gsc = args.platform in ("all", "gsc")
    credentials_file = _credential_path(config, config_path)
    _validate_credential_identity(credentials_file, str(config.get("service_account_email", "")))
    ga4_client, gsc_client = build_clients(credentials_file, ga4=use_ga4, gsc=use_gsc)
    store = CollectedDataStore(Path(args.collected_data))
    result: Dict[str, Any] = {"domain": context.domain, "period": [period_start, period_end], "recorded": []}
    archive_payload: Dict[str, Any] = {"domain": context.domain, "period": [period_start, period_end]}

    if use_ga4:
        ga4_config = config.get("ga4", {})
        ga4_fields = collect_ga4(
            ga4_client,
            str(ga4_config.get("property_id", "")),
            period_start,
            period_end,
            int(ga4_config.get("row_limit", 1000)),
        )
        result["ga4"] = {"sessions": ga4_fields["session_count"], "detail_fields": 6}
        archive_payload["ga4"] = {field: value for field, value in ga4_fields.items() if not field.startswith("_")}
        if not args.dry_run and not args.archive_only:
            result["recorded"].extend(_record_fields(store, ga4_fields, "Google Analytics Data API", GA4_SOURCE_URL))

    if use_gsc:
        gsc_config = config.get("gsc", {})
        gsc_fields = collect_gsc(
            gsc_client,
            str(gsc_config.get("site_url", "")),
            context.domain,
            period_start,
            period_end,
            int(gsc_config.get("row_limit", 25000)),
            int(gsc_config.get("inspection_limit", 20)),
        )
        result["gsc"] = {"clicks": gsc_fields["organic_clicks"], "queries": gsc_fields["ranked_keyword_count"], "detail_fields": 5}
        archive_payload["gsc"] = gsc_fields
        if not args.dry_run and not args.archive_only:
            result["recorded"].extend(_record_fields(store, gsc_fields, "Google Search Console API", GSC_SOURCE_URL))

    if not args.dry_run:
        archive_path = (
            save_new_custom_archive(args.archive_root, context.domain, period_start, period_end, archive_payload)
            if custom_dates else save_new_month_archive(args.archive_root, context.domain, archive_label, archive_payload)
        )
        result["archive"] = str(archive_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"连接失败 [{type(exc).__name__}]: {exc}", file=sys.stderr)
        raise SystemExit(2)
