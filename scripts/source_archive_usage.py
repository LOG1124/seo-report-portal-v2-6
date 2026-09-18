"""Non-public provenance for the Google archives used by a generated report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PureWindowsPath
from typing import Any

from customer_registry import CustomerRecord, google_archive_path
from google_api_collector import ReadyArchive, read_ready_archive_bytes, read_ready_complete_month_archive, read_ready_custom_date_archive


USAGE_FILE = "source-archive-usage.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot(archive_root: Path, record: CustomerRecord, value: Path | ReadyArchive) -> ReadyArchive:
    if isinstance(value, ReadyArchive):
        customer_root = (Path(archive_root) / "ga4-gsc" / record.canonical_domain).resolve()
        try:
            value.path.resolve().relative_to(customer_root)
        except ValueError:
            raise ValueError("来源使用记录包含其他客户档案")
        if value.record != record:
            raise ValueError("来源使用记录包含其他客户档案")
        return value
    path = Path(value)
    if path.parent.name == "custom":
        try:
            start, end = path.stem.split("_to_", 1)
        except ValueError as exc:
            raise ValueError("自定义日期来源路径无效") from exc
        return read_ready_custom_date_archive(archive_root, record.canonical_domain, start, end)
    return read_ready_complete_month_archive(archive_root, record.canonical_domain, path.stem)


def usage_entry(archive_root: Path, record: CustomerRecord, role: str, value: Path | ReadyArchive) -> dict[str, str]:
    root = Path(archive_root).resolve()
    snapshot = _snapshot(root, record, value)
    resolved = snapshot.path.resolve()
    return {
        "role": role,
        "relative_path": str(resolved.relative_to(root)),
        "sha256": snapshot.sha256,
    }


def write_usage(
    report_dir: Path,
    archive_root: Path,
    record: CustomerRecord,
    report_type: str,
    label: str,
    current: list[Path | ReadyArchive],
    previous: list[Path | ReadyArchive],
    comparison_mode: str,
) -> Path:
    payload = {
        "domain": record.canonical_domain,
        "portal_slug": record.portal_slug,
        "report_type": report_type,
        "label": label,
        "comparison_mode": comparison_mode,
        "archives": [
            *(usage_entry(archive_root, record, "current", path) for path in current),
            *(usage_entry(archive_root, record, "previous", path) for path in previous),
        ],
    }
    path = Path(report_dir) / USAGE_FILE
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _source_path(root: Path, relative_path: str) -> Path:
    windows_path = PureWindowsPath(relative_path)
    if Path(relative_path).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("来源使用记录包含档案根目录外路径")
    try:
        source = (root / relative_path).resolve()
        source.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("来源使用记录包含档案根目录外路径") from exc
    return source


def verify_usage(
    report_dir: Path,
    archive_root: Path,
    record: CustomerRecord,
    report_type: str,
    label: str,
    allow_current_only: bool,
) -> dict[str, Any]:
    """Verify the local provenance record before an exception report can publish."""
    payload = json.loads((Path(report_dir) / USAGE_FILE).read_text(encoding="utf-8"))
    expected = {
        "domain": record.canonical_domain,
        "portal_slug": record.portal_slug,
        "report_type": report_type,
        "label": label,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("来源使用记录与报告身份不一致")

    comparison_mode = payload.get("comparison_mode")
    if comparison_mode not in {"complete", "unavailable", "current_only_exception"}:
        raise ValueError("来源使用记录的对比模式无效")
    if comparison_mode == "current_only_exception" and not allow_current_only:
        raise ValueError("仅当期报告必须显式允许发布")

    entries = payload.get("archives")
    if not isinstance(entries, list):
        raise ValueError("来源使用记录格式无效")
    roles = [item.get("role") for item in entries if isinstance(item, dict)]
    if "current" not in roles:
        raise ValueError("来源使用记录缺少当期档案")
    if comparison_mode == "complete" and "previous" not in roles:
        raise ValueError("来源使用记录缺少对比期档案")

    root = Path(archive_root).resolve()
    customer_root = (root / "ga4-gsc" / record.canonical_domain).resolve()
    for item in entries:
        if (
            not isinstance(item, dict)
            or item.get("role") not in {"current", "previous"}
            or not isinstance(item.get("relative_path"), str)
            or not isinstance(item.get("sha256"), str)
        ):
            raise ValueError("来源使用记录格式无效")
        source = _source_path(root, item["relative_path"])
        try:
            source.relative_to(customer_root)
        except ValueError as exc:
            raise ValueError("来源使用记录包含其他客户档案") from exc
        try:
            snapshot = _snapshot(root, record, source)
        except (FileNotFoundError, ValueError) as exc:
            raise ValueError("源档案 SHA-256 不一致或尚未就绪") from exc
        if snapshot.path.resolve() != source or snapshot.sha256 != item["sha256"]:
            raise ValueError("源档案 SHA-256 不一致")
    return payload
