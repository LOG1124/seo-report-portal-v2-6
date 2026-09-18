"""Shared report-period rules used before generation and publication."""

from __future__ import annotations

import re
from datetime import date, timedelta


REPORT_TYPES = frozenset(("monthly", "quarterly", "yearly", "period", "custom"))
FIXED_MONTH_COUNTS = {"monthly": 1, "quarterly": 3, "yearly": 12}
TYPE_LABELS = {
    "monthly": "月度报告",
    "quarterly": "季度报告",
    "yearly": "年度报告",
    "period": "阶段报告",
    "custom": "自定义报告",
}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_custom_date_range(start: str, end: str) -> tuple[date, date]:
    """Parse an inclusive custom report range without accepting reversed dates."""
    try:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("自定义日期必须是 YYYY-MM-DD") from exc
    if last < first:
        raise ValueError("结束日期不能早于开始日期")
    return first, last


def previous_equal_day_range(start: str, end: str) -> tuple[str, str]:
    """Return the immediately preceding inclusive range with the same day count."""
    first, last = validate_custom_date_range(start, end)
    days = (last - first).days + 1
    return (first - timedelta(days=days)).isoformat(), (first - timedelta(days=1)).isoformat()


def validate_report_label(report_type: str, label: str) -> None:
    """Validate a public/archive period label without accepting a label for another type."""
    if report_type == "custom":
        try:
            start, end = label.split("_to_", 1)
        except ValueError as exc:
            raise ValueError("自定义报告周期必须是 YYYY-MM-DD_to_YYYY-MM-DD") from exc
        validate_custom_date_range(start, end)
        return
    if not re.fullmatch(r"(?:\d{4}|\d{4}-\d{2}|\d{4}-\d{2}_to_\d{4}-\d{2})", label):
        raise ValueError("周期格式必须是 YYYY、YYYY-MM 或 YYYY-MM_to_YYYY-MM。")


def _next_month(value: str) -> str:
    year, month = map(int, value.split("-"))
    return f"{year + (month == 12):04d}-{1 if month == 12 else month + 1:02d}"


def validate_report_months(report_type: str, months: list[str]) -> None:
    """Reject unknown, discontinuous, or wrongly sized report periods."""
    if report_type not in REPORT_TYPES:
        raise ValueError("报告类型无效")
    if report_type == "custom":
        raise ValueError("自定义报告必须使用日期范围")
    if report_type == "period":
        if len(months) < 2:
            raise ValueError("阶段报告至少包含 2 个月")
    elif len(months) != FIXED_MONTH_COUNTS[report_type]:
        raise ValueError(f"{TYPE_LABELS[report_type]}必须包含 {FIXED_MONTH_COUNTS[report_type]} 个月")
    if not months or any(not MONTH_RE.fullmatch(month) for month in months):
        raise ValueError("报告月份必须是 YYYY-MM")
    if any(current != _next_month(previous) for previous, current in zip(months, months[1:])):
        raise ValueError("报告月份必须连续")
