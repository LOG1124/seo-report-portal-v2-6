"""Shared report-period rules used before generation and publication."""

from __future__ import annotations

import re


REPORT_TYPES = frozenset(("monthly", "quarterly", "yearly", "period"))
FIXED_MONTH_COUNTS = {"monthly": 1, "quarterly": 3, "yearly": 12}
TYPE_LABELS = {
    "monthly": "月度报告",
    "quarterly": "季度报告",
    "yearly": "年度报告",
    "period": "阶段报告",
}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _next_month(value: str) -> str:
    year, month = map(int, value.split("-"))
    return f"{year + (month == 12):04d}-{1 if month == 12 else month + 1:02d}"


def validate_report_months(report_type: str, months: list[str]) -> None:
    """Reject unknown, discontinuous, or wrongly sized report periods."""
    if report_type not in REPORT_TYPES:
        raise ValueError("报告类型无效")
    if report_type == "period":
        if len(months) < 2:
            raise ValueError("阶段报告至少包含 2 个月")
    elif len(months) != FIXED_MONTH_COUNTS[report_type]:
        raise ValueError(f"{TYPE_LABELS[report_type]}必须包含 {FIXED_MONTH_COUNTS[report_type]} 个月")
    if not months or any(not MONTH_RE.fullmatch(month) for month in months):
        raise ValueError("报告月份必须是 YYYY-MM")
    if any(current != _next_month(previous) for previous, current in zip(months, months[1:])):
        raise ValueError("报告月份必须连续")
