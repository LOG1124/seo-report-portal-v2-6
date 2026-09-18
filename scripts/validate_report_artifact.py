#!/usr/bin/env python3
"""Verify a generated report is internally consistent before it is copied for publication."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List

from report_diagnostics import diagnostic
from report_periods import validate_custom_date_range, validate_report_months


def _fail(message: str) -> None:
    raise ValueError(message)


def validate_report_artifact(directory: Path) -> Dict[str, Any]:
    """Validate report path, report metadata, embedded HTML and summary identity."""
    directory = Path(directory)
    try:
        domain, report_type, label = directory.parts[-3:]
    except ValueError as exc:
        raise ValueError(f"REPORT_TYPE_PATH_MISMATCH: 无法从路径识别客户、类型和周期：{directory}") from exc
    data_path = directory / "dashboard-data.json"
    html_path = directory / "index.html"
    summary_path = directory / "summary.md"
    if not all(path.exists() for path in (data_path, html_path, summary_path)):
        _fail(f"REPORT_TYPE_PATH_MISMATCH: 报告产物不完整：{directory}")
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    report = payload.get("report")
    if not isinstance(report, dict):
        _fail("REPORT_TYPE_PATH_MISMATCH: dashboard-data.json 缺少 report 元数据")
    if (
        report.get("domain") != domain or report.get("type") != report_type or report.get("label") != label
    ):
        _fail(f"REPORT_TYPE_PATH_MISMATCH: 路径 {domain}/{report_type}/{label} 与 report 元数据不一致")
    try:
        if report_type == "custom":
            custom_range = report.get("customRange", {})
            start, end = str(custom_range.get("startDate", "")), str(custom_range.get("endDate", ""))
            first, last = validate_custom_date_range(start, end)
            if label != f"{first.isoformat()}_to_{last.isoformat()}" or custom_range.get("dayCount") != (last - first).days + 1:
                _fail("REPORT_TYPE_PATH_MISMATCH: 自定义报告日期范围与路径不一致")
        else:
            validate_report_months(report_type, report.get("selectedMonths", []))
    except ValueError as exc:
        _fail(str(exc))
    html = html_path.read_text(encoding="utf-8")
    summary = summary_path.read_text(encoding="utf-8")
    embedded = re.search(r'<script id="google-seo-data" type="application/json">(.*?)</script>', html, re.S)
    try:
        embedded_payload = json.loads(embedded.group(1)) if embedded else None
    except json.JSONDecodeError:
        embedded_payload = None
    if embedded_payload != payload or domain not in summary or report_type not in summary or label not in summary:
        _fail("REPORT_TYPE_PATH_MISMATCH: index.html 或 summary.md 与 dashboard-data.json 身份不一致")
    return {"code": "REPORT_ARTIFACT_VALID", "directory": str(directory)}


def validate_report_tree(domain_root: Path) -> List[Dict[str, Any]]:
    """Find duplicate report payloads at different report paths before publication review."""
    domain_root = Path(domain_root)
    grouped: Dict[str, List[Path]] = {}
    for data_path in domain_root.glob("*/*/dashboard-data.json"):
        digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
        grouped.setdefault(digest, []).append(data_path.parent)
    diagnostics: List[Dict[str, Any]] = []
    for paths in grouped.values():
        if len(paths) > 1:
            diagnostics.append(diagnostic(
                "DUPLICATE_REPORT_ARTIFACT", stage="artifact_validation",
                scope={"domain_root": str(domain_root)}, detected={"paths": [str(path) for path in paths]},
                impact="已阻止将疑似重复周期内容复制到发布目录。",
                next_action="分别重新生成每个报告周期，并确认 dashboard-data.json 的周期元数据不同。",
                status="blocked",
            ))
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 SEO 报告产物身份，供发布前复核使用")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--domain-root", type=Path)
    args = parser.parse_args()
    result = validate_report_artifact(args.report_dir)
    diagnostics = validate_report_tree(args.domain_root) if args.domain_root else []
    print(json.dumps({"artifact": result, "diagnostics": diagnostics}, ensure_ascii=False))
    return 1 if diagnostics else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(f"错误: {exc}")
