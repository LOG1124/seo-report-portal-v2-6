# 同事首次上手：从采集到在线报告链接

本指南适用于 `seo-report-portal-v2-6`。每位同事都能完成**本地 → SMB → OSS**，但不得跳过数据、付费或发布批准门禁。

在 Windows 首次使用前，先阅读 [Windows 配置](windows-first-run.md)；不要把 macOS 的 `/Volumes/共享盘`、`.venv/bin/python` 或 `chmod` 命令照搬到 Windows。

## 安装或升级 v2.6

这次更新从 GitHub 仓库 `https://github.com/LOG1124/seo-report-portal-v2-4.git` 的 `main` 分支取得 v2.5，不再由管理员分发 ZIP。更新**不会**重新配置 Google、DataForSEO、SEOAgent、SMB 或 OSS，也不会读取、复制或改写任何密钥。

更新时必须保留以下内容不变：客户工作区的 `private/`、`workflows/automation/input/`、`output/dashboards/`、`~/.codex/config.toml` 以及已经发布的报告。GitHub 工作副本固定放在全局 Skill 目录之外；旧的全局 v2.5 Skill 目录只会移动到带时间戳的备份目录。若源副本或现有全局 Skill 内出现 `private/`，先停止并报告，不要将凭据带入新安装。

macOS/Linux 从 GitHub 更新：

```bash
repo_url='https://github.com/LOG1124/seo-report-portal-v2-4.git'
source_dir="$HOME/.codex/sources/seo-report-portal-v2-6"
skill_dir="$HOME/.codex/skills/seo-report-portal-v2-6"
backup_dir="$HOME/.codex/skill-backups/seo-report-portal-v2-6-pre-update-$(date +%Y%m%d%H%M%S)"

if test -e "$source_dir"; then
  test -d "$source_dir/.git" || { echo '现有 GitHub 源目录不是 Git 工作副本，停止。' >&2; exit 1; }
  test -z "$(git -C "$source_dir" status --porcelain)" || { echo 'GitHub 源目录有本地修改，停止。' >&2; exit 1; }
  git -C "$source_dir" fetch --prune origin
  git -C "$source_dir" switch main
  git -C "$source_dir" pull --ff-only origin main
else
  mkdir -p "$(dirname "$source_dir")"
  git clone --branch main --single-branch "$repo_url" "$source_dir"
fi

test -f "$source_dir/SKILL.md"
test ! -e "$source_dir/private" || { echo 'GitHub 源目录包含 private，停止。' >&2; exit 1; }
test ! -e "$skill_dir/private" || { echo '现有全局 Skill 包含 private，停止更新。' >&2; exit 1; }
stage_dir="$(mktemp -d)"
git -C "$source_dir" archive --format=tar HEAD | tar -xf - -C "$stage_dir"
test -f "$stage_dir/SKILL.md"
test ! -e "$stage_dir/private" || { echo '暂存安装内容包含 private，停止。' >&2; exit 1; }
mkdir -p "$(dirname "$backup_dir")" "$(dirname "$skill_dir")"
if test -e "$skill_dir"; then mv "$skill_dir" "$backup_dir"; fi
mv "$stage_dir" "$skill_dir"
```

Windows 从 GitHub 更新：

```powershell
$repoUrl = 'https://github.com/LOG1124/seo-report-portal-v2-4.git'
$source = Join-Path $env:USERPROFILE '.codex\sources\seo-report-portal-v2-6'
$archive = Join-Path $env:TEMP ('seo-report-portal-v2-6-' + [guid]::NewGuid() + '.zip')
$stage = Join-Path $env:TEMP ('seo-report-portal-v2-6-stage-' + [guid]::NewGuid())
$skill = Join-Path $env:USERPROFILE '.codex\skills\seo-report-portal-v2-6'
$backup = Join-Path $env:USERPROFILE ('.codex\skill-backups\seo-report-portal-v2-6-pre-update-' + (Get-Date -Format yyyyMMddHHmmss))

if (Test-Path -LiteralPath $source) {
    if (!(Test-Path -LiteralPath (Join-Path $source '.git') -PathType Container)) { throw '现有 GitHub 源目录不是 Git 工作副本，停止。' }
    if (git -C $source status --porcelain) { throw 'GitHub 源目录有本地修改，停止。' }
    git -C $source fetch --prune origin
    git -C $source switch main
    git -C $source pull --ff-only origin main
} else {
    New-Item -ItemType Directory -Force (Split-Path $source) | Out-Null
    git clone --branch main --single-branch $repoUrl $source
}

if (!(Test-Path -LiteralPath (Join-Path $source 'SKILL.md') -PathType Leaf)) { throw 'GitHub 源目录缺少 SKILL.md' }
if (Test-Path -LiteralPath (Join-Path $source 'private')) { throw 'GitHub 源目录包含 private，停止更新' }
if (Test-Path (Join-Path $skill 'private')) { throw '现有全局 Skill 包含 private，停止更新' }
New-Item -ItemType Directory -Force $stage | Out-Null
git -C $source archive --format=zip --output $archive HEAD
Expand-Archive -LiteralPath $archive -DestinationPath $stage
if (!(Test-Path -LiteralPath (Join-Path $stage 'SKILL.md') -PathType Leaf)) { throw 'GitHub 暂存内容缺少 SKILL.md' }
if (Test-Path -LiteralPath (Join-Path $stage 'private')) { throw 'GitHub 暂存内容包含 private，停止更新' }
New-Item -ItemType Directory -Force (Split-Path $backup) | Out-Null
if (Test-Path -LiteralPath $skill) { Move-Item -LiteralPath $skill -Destination $backup }
Move-Item -LiteralPath $stage -Destination $skill
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
```

替换后重启 Codex，让新 Skill 生效；不需要重建客户工作区或重新填写任何密钥。出现问题时，将新目录移走，再把对应时间戳备份目录移回 `~/.codex/skills/seo-report-portal-v2-6`（Windows 使用同样的 `Move-Item`），然后重新启动 Codex。上述命令只删除临时 Git archive；不会删除任何旧 Skill、客户工作区或私密配置。

Windows 同事如需将“更新 v2.6、验证 UNC、迁移当前工作区已有 v2.2 原始档案”交由 Codex 一次完成，可将 `references/windows-v24-repair-runbook.md` 作为任务附件交给 Codex。该运行手册不扫描整个磁盘、不自动重采集 Google 数据，也不会触碰 `private/` 或 `~/.codex/config.toml`。

## 管理员先完成

1. 为同事提供客户的 GA4/GSC 只读服务账号访问。
2. 如需第三方模块，通过密码管理器发放获批准的 DataForSEO 凭据和 SEOAgent Token。
3. 让同事的独立 RAM 用户加入 `SEOReportPublishers` 用户组；该组应已绑定 `SEOReportPublisherPolicy`，且仅允许上传 `jzyseo-reports/reports/*`。
4. 提供 SMB 公盘写入访问，以及同事本机可用的归档路径：macOS 挂载路径、Windows 映射盘或 Windows UNC 路径。
5. 通过密码管理器提供该同事独立的 RAM AccessKey ID、AccessKey Secret 和 OSS 地域。不要共享管理员或其他同事的 AccessKey。

## 同事首次配置

在自己的客户工作区只创建 `private/` 与报告输出目录；不要创建或复制 `scripts/`。采集、校验、导入和发布都从已安装的 v2.5 Skill 目录运行。Windows 请按 [Windows 配置](windows-first-run.md) 使用 PowerShell 与 Python。

只在本机填写 `private/dataforseo.env`、`private/ossutilconfig` 和 Google 服务账号 JSON。`private/oss.env` 指向本机 `ossutil`、`ossutilconfig` 和已连接的 SMB 归档根路径；不要填写或提交真实凭据到其他文件。

## 共享原始档案首次设置

1. 连接共享原始档案根目录。macOS 使用 `/Volumes/共享盘/seo-report-source-archive`；Windows 使用映射盘路径或 UNC，具体命令见 [Windows 配置](windows-first-run.md)。该共享盘是 guest 读写，**不是保密归档位置**。
2. 从 `assets/customer-registry.example.json` 创建 `<共享原始档案根目录>/customer-registry.json`。在采集某客户前，先添加一条 active 的真实域名 ↔ 报告 slug 记录。新客户 slug 只能是小写字母、数字和连字符；仅为保留一个目录名与真实域名完全相同的既有公开路径，才允许添加 `legacy_public_slug: true`，新客户不得使用该例外。
3. 每次采集必须传入 `--archive-root <共享原始档案根目录> --month YYYY-MM`；自定义日期采集改用 `--start YYYY-MM-DD --end YYYY-MM-DD`，并独立写入 `ga4-gsc/<域名>/custom/<开始>_to_<结束>.json`。每次生成也必须传入同一个 `--archive-root`。采集/导入完成前会先独占写入 JSON，再写同名非公开 `.json.ready` SHA-256 标记；只有两者匹配才可生成、发布或自动选词。自定义报告使用 `--type custom --start-date YYYY-MM-DD --end-date YYYY-MM-DD`，会自动尝试上一等长日期范围；失败仅在操作者结果和内部诊断中说明，不写入客户文字总结。非标准连续月跨度使用 `--type period`，不能标为季度报告。
4. `GOOGLE_SOURCE_ARCHIVE_ROOT` 仅可作为 `oss.env` 内供人复制到发布器 `--source-archive-root` 的便利值。采集器和生成器绝不会隐式读取它。

## 无消费与无写入检查

1. 重启 Codex 后确认 `seoagent` MCP 显示正常；不要用真实查询测试。
2. 确认 `private/oss.env` 的 `OSS_ARCHIVE_ROOT` 是本机可访问的报告 SMB 路径；若填写了 `GOOGLE_SOURCE_ARCHIVE_ROOT`，仍须在发布命令中显式传入该路径。
3. 生成本地报告并使用已安装 v2.5 Skill 的校验器检查产物。Windows 先设置 `$skill`，再使用 `py -3`：

```powershell
$skill = Join-Path $env:USERPROFILE '.codex\skills\seo-report-portal-v2-6'
py -3 "$skill\scripts\validate_report_artifact.py" --report-dir <output/dashboards/domain/type/period> --domain-root <output/dashboards/domain>
```

4. 只运行已安装 v2.5 Skill 的跨平台发布 dry-run；它不会写入 SMB 或 OSS：

```powershell
py -3 "$skill\scripts\publish_oss_report.py" --local-report-dir <output/dashboards/domain/type/period> --client-slug <client-slug> --type <monthly|quarterly|yearly|period|custom> --period <period> --source-archive-root <shared-source-root> --dry-run
```

## 每份报告的发布步骤

1. 采集并归档 GA4/GSC 官方月度数据，绝不改写历史档案。
2. 先复用同客户、同完整 `reporting_period`、范围一致且带 `approval.approved: true` 的 DataForSEO 和 SEOAgent 归档。自定义日期报告只能复用精确日期快照；服务不支持精确日期时，先由用户明确选择 `--third-party-proxy-month YYYY-MM` 作为月度背景或 `--without-third-party`。任一缺失或范围变化时，先给出该次请求范围、费用上限并获得明确确认。
3. 生成报告并人工核对 `index.html`、`summary.md` 和内部 `diagnostic.md`。
4. 获得这份报告的明确发布批准。
5. 执行 `publish_oss_report.py --source-archive-root <shared-source-root>`。它先验证非公开的 `source-archive-usage.json`，再按以下顺序处理，任何一步失败即停止；仅发布三件套。仅当期例外必须同时增加 `--allow-current-only`：

```text
本地 index.html/dashboard-data.json/summary.md
→ 本机配置的 SMB <archive-root>/<client-slug>/<type>/<period>/
→ oss://jzyseo-reports/reports/<client-slug>/<type>/<period>/
→ https://reports.jzyseo.com/reports/<client-slug>/<type>/<period>/
```

6. 只有脚本报告 SMB 与本地 SHA-256 一致、线上 `index.html` SHA-256 一致且公开链接 GET 成功时，才能交付。
7. 客户交付固定包含在线报告链接和文字总结。文字总结必须逐字复制已审核 `summary.md` 的 `## 运营总结` 标题与编号正文；不得因任何人的要求改写、删减、重排、补充或替换。

已有不同公盘版本时，脚本会停止。只有明确批准替换时才增加 `--replace-archive`；这会覆盖该报告周期的三个公盘文件并上传 OSS。

## 常见停止条件

- `AccessDenied`：检查 RAM 用户是否已加入 `SEOReportPublishers`，以及用户组是否仍绑定 `SEOReportPublisherPolicy`。
- SMB 路径不存在：先连接或映射指定路径；不要把别人的 `/Volumes/共享盘` 当作本机路径，也不要绕过 SMB 直接上传。
- 线上目录 HEAD 返回 404：这是 OSS 目录行为；以报告链接的 GET 结果和 SHA-256 为准。
- 付费请求失败：停止并报告原始错误，不得自动重试。
