#!/usr/bin/env python3
"""Cost-capped DataForSEO enrichment for dashboard-selected GSC keywords."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Tuple
import urllib.error
import urllib.request

from customer_registry import CustomerRecord, require_active_customer
from google_api_collector import month_dates, read_ready_complete_month_archive


SEARCH_VOLUME_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
SERP_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/regular"
REQUIRED_CONFIG = {
    "domain", "month", "location_code", "language_code", "serp_device",
    "max_keywords", "output_archive_dir",
}
Transport = Callable[[str, bytes, Mapping[str, str]], Dict[str, Any]]


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalise_query(value: Any) -> str:
    return " ".join(str(value or "").split())


def load_trial_config(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("DataForSEO 试水配置必须是 JSON 对象")
    missing = sorted(key for key in REQUIRED_CONFIG if key not in payload)
    if missing:
        raise ValueError(f"DataForSEO 试水配置缺少字段: {', '.join(missing)}")
    if int(payload["max_keywords"]) != 5:
        raise ValueError("试水配置 max_keywords 必须固定为 5")
    if payload["serp_device"] != "desktop":
        raise ValueError("试水配置 serp_device 必须固定为 desktop")
    if "source_archive" in payload:
        raise ValueError("source_archive 已不受支持；GSC 来源由 --archive-root、客户注册表和月份唯一确定")
    has_source_selection = all(key in payload for key in ("include_terms", "exclude_terms"))
    has_explicit_selection = "selected_keywords" in payload
    if has_source_selection == has_explicit_selection:
        raise ValueError("试水配置必须二选一：include_terms/exclude_terms 自动选词，或 selected_keywords 明确词表")
    if has_explicit_selection:
        rows = payload["selected_keywords"]
        if not isinstance(rows, list) or len(rows) != 5:
            raise ValueError("明确词表必须恰好包含 5 个关键词")
        queries = [_normalise_query(row.get("query")) if isinstance(row, dict) else "" for row in rows]
        if any(not query for query in queries) or len(set(queries)) != 5:
            raise ValueError("明确词表关键词必须非空且不重复")
        primary = _normalise_query(payload.get("primary_serp_keyword"))
        if primary != queries[0]:
            raise ValueError("primary_serp_keyword 必须是明确词表的第一优先级关键词")
    return payload


def _selection_reason(row: Mapping[str, Any]) -> str:
    reasons: List[str] = ["与主营产品词匹配"]
    impressions = _number(row.get("impressions"))
    ctr = _number(row.get("ctr"))
    position = _number(row.get("position"))
    if impressions > 0:
        reasons.append("已有美国市场曝光")
    if ctr <= 1:
        reasons.append("点击率偏低")
    if 11 <= position <= 80:
        reasons.append("排名存在提升空间")
    return "；".join(reasons)


def _selection_score(row: Mapping[str, Any]) -> float:
    impressions = _number(row.get("impressions"))
    ctr = _number(row.get("ctr"))
    position = _number(row.get("position"))
    ctr_opportunity = max(0.0, 1.0 - min(ctr, 1.0)) * 10
    ranking_opportunity = 20.0 if 11 <= position <= 80 else 0.0
    return impressions + ctr_opportunity + ranking_opportunity


def select_dashboard_keywords(rows: Iterable[Mapping[str, Any]], config: Mapping[str, Any]) -> List[Dict[str, Any]]:
    include_terms = [str(value).lower() for value in config.get("include_terms", []) if str(value).strip()]
    exclude_terms = [str(value).lower() for value in config.get("exclude_terms", []) if str(value).strip()]
    limit = int(config.get("max_keywords", 5))
    if not include_terms:
        raise ValueError("include_terms 不能为空")
    if not 1 <= limit <= 5:
        raise ValueError("max_keywords 必须介于 1 和 5 之间")

    selected: List[Dict[str, Any]] = []
    for source_row in rows:
        query = _normalise_query(source_row.get("query"))
        lowered = query.lower()
        if not query or any(term in lowered for term in exclude_terms):
            continue
        if not any(term in lowered for term in include_terms):
            continue
        row = dict(source_row)
        row["query"] = query
        row["selection_reason"] = _selection_reason(row)
        row["_selection_score"] = _selection_score(row)
        selected.append(row)

    selected.sort(key=lambda row: (-_number(row["_selection_score"]), -_number(row.get("impressions")), str(row["query"]).lower()))
    for row in selected:
        row.pop("_selection_score", None)
    return selected[:limit]


def load_credentials(path: Path) -> Tuple[str, str]:
    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    login = values.get("DATAFORSEO_LOGIN", "")
    password = values.get("DATAFORSEO_PASSWORD", "")
    if not login or not password:
        raise ValueError("DataForSEO 凭据文件缺少 DATAFORSEO_LOGIN 或 DATAFORSEO_PASSWORD")
    return login, password


def build_search_volume_request(keywords: List[str], *, location_code: int, language_code: str) -> List[Dict[str, Any]]:
    if not 1 <= len(keywords) <= 5:
        raise ValueError("搜索量试水请求必须包含 1 至 5 个关键词")
    if len(set(keywords)) != len(keywords) or any(not keyword.strip() for keyword in keywords):
        raise ValueError("搜索量试水关键词必须非空且不重复")
    return [{"keywords": keywords, "location_code": location_code, "language_code": language_code}]


def build_serp_request(selected_keywords: List[str], *, primary_keyword: str, location_code: int, language_code: str, device: str) -> List[Dict[str, Any]]:
    if not selected_keywords or primary_keyword != selected_keywords[0]:
        raise ValueError("SERP 只能查询第一优先级的已选关键词")
    if device != "desktop":
        raise ValueError("试水 SERP 只允许 desktop")
    return [{"keyword": primary_keyword, "location_code": location_code, "language_code": language_code, "device": device}]


def _normalise_search_volume(response: Mapping[str, Any]) -> Dict[str, Any]:
    task = ((response.get("tasks") or [{}])[0])
    items = task.get("result") or []
    return {
        "status_code": response.get("status_code"),
        "status_message": response.get("status_message"),
        "cost": response.get("cost"),
        "task_status_code": task.get("status_code"),
        "task_status_message": task.get("status_message"),
        "keywords": [
            {
                "keyword": item.get("keyword"),
                "search_volume": item.get("search_volume"),
                "cpc": item.get("cpc"),
                "competition": item.get("competition"),
                "competition_index": item.get("competition_index"),
                "monthly_searches": item.get("monthly_searches"),
            }
            for item in items
        ],
    }


def _normalise_serp(response: Mapping[str, Any], keyword: str) -> Dict[str, Any]:
    task = ((response.get("tasks") or [{}])[0])
    result = ((task.get("result") or [{}])[0])
    organic = [item for item in result.get("items") or [] if item.get("type") == "organic"]
    return {
        "keyword": keyword,
        "status_code": response.get("status_code"),
        "status_message": response.get("status_message"),
        "cost": response.get("cost"),
        "task_status_code": task.get("status_code"),
        "task_status_message": task.get("status_message"),
        "organic_results": [
            {
                "rank": item.get("rank_absolute"),
                "domain": item.get("domain"),
                "title": item.get("title"),
                "url": item.get("url"),
                "description": item.get("description"),
            }
            for item in organic
        ],
    }


class DataForSEOClient:
    def __init__(self, login: str, password: str, *, transport: Transport | None = None) -> None:
        self._token = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")
        self._transport = transport or self._send

    def _send(self, url: str, body: bytes, headers: Mapping[str, str]) -> Dict[str, Any]:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")[:500]
            try:
                detail = json.loads(raw)
                status_code = detail.get("status_code")
                status_message = str(detail.get("status_message", "")).strip()
                if status_code or status_message:
                    raise RuntimeError(f"DataForSEO HTTP {exc.code}: {status_code or 'unknown'} {status_message}") from exc
            except json.JSONDecodeError:
                pass
            raise RuntimeError(f"DataForSEO HTTP {exc.code}: {raw}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DataForSEO 网络请求失败: {exc.reason}") from exc

    def _post(self, url: str, payload: List[Dict[str, Any]]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Basic {self._token}", "Content-Type": "application/json"}
        response = self._transport(url, body, headers)
        if not isinstance(response, dict):
            raise RuntimeError("DataForSEO 返回的内容不是 JSON 对象")
        return response

    def fetch_search_volume(self, keywords: List[str], *, location_code: int, language_code: str) -> Dict[str, Any]:
        response = self._post(SEARCH_VOLUME_URL, build_search_volume_request(keywords, location_code=location_code, language_code=language_code))
        return _normalise_search_volume(response)

    def fetch_organic_serp(self, keyword: str, *, selected_keywords: List[str], location_code: int, language_code: str, device: str) -> Dict[str, Any]:
        response = self._post(SERP_URL, build_serp_request(selected_keywords, primary_keyword=keyword, location_code=location_code, language_code=language_code, device=device))
        return _normalise_serp(response, keyword)


def write_trial_archive(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _is_success(payload: Mapping[str, Any]) -> bool:
    return payload.get("status_code") == 20000 and payload.get("task_status_code") == 20000


def _archive_path(config: Mapping[str, Any], record: CustomerRecord) -> Path:
    return Path(str(config["output_archive_dir"])) / record.canonical_domain / f"{config['month']}.json"


def selected_rows_from_config(
    config: Mapping[str, Any], archive_root: Path, record: CustomerRecord
) -> List[Dict[str, Any]]:
    """Return either GSC-selected rows or a pre-approved, fixed quarterly word list."""
    if "selected_keywords" in config:
        selected: List[Dict[str, Any]] = []
        for source_row in config["selected_keywords"]:
            row = dict(source_row)
            row["query"] = _normalise_query(row.get("query"))
            row.setdefault("selection_reason", "已确认的季度 GSC 重点词")
            selected.append(row)
        return selected
    month = str(config["month"])
    snapshot = read_ready_complete_month_archive(archive_root, record.canonical_domain, month)
    return select_dashboard_keywords(snapshot.payload["gsc"].get("gsc_queries", []), config)


def main() -> int:
    parser = argparse.ArgumentParser(description="按看板 GSC 选词进行 5+1 DataForSEO 试水采集")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    config = load_trial_config(args.config)
    record = require_active_customer(args.archive_root, str(config["domain"]))
    month_dates(str(config["month"]))
    selected = selected_rows_from_config(config, args.archive_root, record)
    if len(selected) != 5:
        raise ValueError(f"筛选后必须恰好得到 5 个关键词，当前为 {len(selected)}")
    keywords = [str(row["query"]) for row in selected]
    if args.dry_run:
        print(json.dumps({"mode": "dry-run", "selected_keywords": [{"query": row["query"], "selection_reason": row["selection_reason"]} for row in selected]}, ensure_ascii=False, indent=2))
        return 0

    login, password = load_credentials(args.credentials)
    client = DataForSEOClient(login, password)
    market = {"location_code": config["location_code"], "language_code": config["language_code"], "device": config["serp_device"]}
    search_volume = client.fetch_search_volume(keywords, location_code=int(config["location_code"]), language_code=str(config["language_code"]))
    payload: Dict[str, Any] = {
        "domain": config["domain"], "month": config["month"], "market": market,
        "selected_keywords": selected, "search_volume": search_volume, "serp": None,
        "costs": {"search_volume": search_volume.get("cost"), "serp": None},
        "approval": {"approved": True},
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    for metadata_key in ("reporting_period", "selection_basis"):
        if metadata_key in config:
            payload[metadata_key] = config[metadata_key]
    primary_keyword = str(config.get("primary_serp_keyword") or keywords[0])
    if _is_success(search_volume):
        try:
            serp = client.fetch_organic_serp(primary_keyword, selected_keywords=keywords, location_code=int(config["location_code"]), language_code=str(config["language_code"]), device=str(config["serp_device"]))
            payload["serp"] = serp
            payload["costs"]["serp"] = serp.get("cost")
        except RuntimeError as exc:
            payload["serp"] = {"keyword": primary_keyword, "error": str(exc)}
    else:
        payload["serp"] = {"keyword": primary_keyword, "skipped": "search_volume_failed"}

    archive = write_trial_archive(_archive_path(config, record), payload)
    print(json.dumps({"mode": "execute", "selected_keywords": keywords, "archive": str(archive), "costs": payload["costs"], "search_volume_ok": _is_success(search_volume), "serp_ok": isinstance(payload["serp"], dict) and _is_success(payload["serp"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"DataForSEO 试水失败 [{type(exc).__name__}]: {exc}")
        raise SystemExit(2)
