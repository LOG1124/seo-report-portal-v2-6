# Windows 首次配置

本说明仅适用于 Windows 工作区。不要运行 macOS 的 `chmod`、`/Volumes/共享盘` 或 `.venv/bin/python` 命令。

## 1. 本地工具与私密文件

在 PowerShell 的客户工作区执行。`$skill` 是 Codex 已安装的现役 v2.4 Skill，不是旧版本：

```powershell
$skill = Join-Path $env:USERPROFILE '.codex\skills\seo-report-portal-v2-4'
New-Item -ItemType Directory -Force private, config | Out-Null
Copy-Item "$skill\assets\dataforseo.env.example" 'private\dataforseo.env'
Copy-Item "$skill\assets\oss.env.example" 'private\oss.env'
Copy-Item "$skill\assets\ossutilconfig.example" 'private\ossutilconfig'
Copy-Item "$skill\assets\google-api.example.json" 'private\google-api.json'
if (-not (Test-Path 'config\dataforseo-trial.json')) {
    Copy-Item "$skill\assets\dataforseo-trial.example.json" 'config\dataforseo-trial.json'
}
```

通过安全渠道手动放置 Google 服务账号 JSON 到 `private\google-service-account.json`。然后只在本机打开 `private\google-api.json`，将示例 `service_account_email` 替换为该本地服务账号 JSON 的 `client_email` 值，并完成凭据文件路径配置。不要把服务账号 JSON、真实账号信息或任何密钥粘贴到聊天、Skill 包或共享目录。

从经批准的客户配置取得或创建 `config\project-input.json`。该文件必须包含当前客户已核对的 `website_url`、`report_start`、`report_end` 和 `cooperation_level`；不要把真实客户值写入 Skill 包或示例文件。采集器、生成器和发布器始终从已安装的 `$skill\scripts\` 运行，客户工作区只保存 `private`、`config` 和 `output`。

首次使用时，上面的命令会从安全示例创建本机 `config\dataforseo-trial.json`，并保留已有本机配置不被覆盖。仅在本机填写已经批准的客户、月份和选词条件；这个试水配置不包含、也不能填写任何凭据。

安装 Python 后，运行时优先使用 `.venv\Scripts\python.exe`；没有虚拟环境时使用 `py -3`。不要使用 macOS 路径 `.venv/bin/python`。

## 2. 连接 SMB 公盘

优先将公司 SMB 公盘映射为固定盘符，例如 `Z:`；也可使用 UNC 路径。共享盘为 guest 读写，故原始 GA4/GSC 档案**不是保密或抗恶意篡改的存储位置**。`.ready` 标记只用于拒绝半成品和意外不一致，不能防止可写者同时重写 JSON 与标记。首次路径预检只确认能打开指定根目录，不要用真实归档文件测试写入。

在 `private\oss.env` 中填写**一种**本机路径：

```dotenv
# 推荐：映射盘
OSS_ARCHIVE_ROOT=Z:\seo-report-portal

# 仅供复制到发布器 --source-archive-root；采集器和生成器不会隐式读取它。
GOOGLE_SOURCE_ARCHIVE_ROOT=Z:\seo-report-source-archive

# 或者：UNC
# OSS_ARCHIVE_ROOT=\\192.168.110.26\共享盘\seo-report-portal
# GOOGLE_SOURCE_ARCHIVE_ROOT=\\server\共享盘\seo-report-source-archive
```

不要填写 macOS 的 `/Volumes/共享盘/seo-report-portal`。SMB 用户名和密码由 Windows 凭据管理器处理，不能写入 `oss.env`。

## 3. OSS 配置与无写入验证

在 `private\ossutilconfig` 中填写该同事独立的 RAM AccessKey；在 `private\oss.env` 中指定 `ossutil.exe` 的实际路径或保持 `OSSUTIL_BIN=ossutil`（仅在它已加入 PATH 时）。不要把 AccessKey 贴入聊天。

Windows 必须直接使用 Python 发布器 `publish_oss_report.py`；`publish_oss_report.sh` 仅适用于 macOS。使用下列完整命令采集、生成和无写入发布：

```powershell
py -3 "$skill\scripts\google_api_collector.py" --config .\private\google-api.json --project-input .\config\project-input.json --archive-root 'Z:\seo-report-source-archive' --month 2026-08 --archive-only
py -3 "$skill\scripts\generate_dashboard_report.py" --type monthly --start-month 2026-08 --domain example.com --archive-root 'Z:\seo-report-source-archive' --output-root .\output\dashboards --diagnostics-root .\output\report-diagnostics
py -3 "$skill\scripts\dataforseo_keyword_enrichment.py" --config .\config\dataforseo-trial.json --archive-root 'Z:\seo-report-source-archive' --credentials .\private\dataforseo.env --dry-run
py -3 "$skill\scripts\publish_oss_report.py" --local-report-dir .\output\dashboards\example.com\monthly\2026-08 --client-slug example-com --type monthly --period 2026-08 --oss-env .\private\oss.env --source-archive-root 'Z:\seo-report-source-archive' --dry-run
```

补回已验证的 v2.2 本机原始档案时，使用导入器而不是手工复制共享盘文件：

```powershell
py -3 "$skill\scripts\import_google_archive.py" --archive-root 'Z:\seo-report-source-archive' --source-file 'C:\legacy\example.com\2026-07.json' --month 2026-07
```

导入只复制、不移动或删除本机旧 JSON，且不会覆盖已有目标。来源只能是旧版 GA4/GSC 原始 JSON，绝不能是 `dashboard-data.json`、`summary.md` 或 `index.html`。它会拒绝缺少 GA4、GSC、正确客户或自然月的文件；JSON 完整写入并同步后，才会独占写入同名非公开 `.json.ready` SHA-256 标记。报告、发布和自动选词只读取这两个文件均存在且哈希一致、存储周期恰为指定自然月的同一份内存快照。对 UNC，只把两处盘符路径替换为对应的单引号 UNC 路径。

如果命令提示某月份存在 `YYYY-MM.json.lock`，立即停止；它记录写入机器、进程与 UTC 开始时间。不要由普通同事删除锁，更不要删除、改名或手工补写目标 JSON 或 `.json.ready`。**只有指定维护负责人**在确认所有同事的采集/导入任务均已结束并已保存锁文件内容作为故障记录后，才可恢复：JSON 和 `.ready` 都存在时，先独立核对 `.ready` 的 SHA-256 与 JSON（导入时还须与本机源 JSON 相同）并记录结果，保留两者，随后才可移走遗留锁；只有 JSON 和 `.ready` 都不存在时，才可移走遗留锁并重试。只有其中一个文件存在或哈希不一致时是未就绪异常，任何工具都不会读取或覆盖它；保留现场并交给维护负责人处置，不能用资源管理器补写。

对于获明确批准的新客户仅当期例外，在生成和发布两条命令末尾都增加 `--allow-current-only`。对 UNC，不改变其它参数，仅把单引号内的 `Z:\seo-report-source-archive` 替换为 `'\\server\共享盘\seo-report-source-archive'`。

如果客户工作区已配置虚拟环境，也可把每条命令开头的 `py -3` 替换为以下 Python 运行器，其后的 `"$skill\scripts\..."` 和客户工作区参数不变：

```powershell
.\.venv\Scripts\python.exe
```

`--dry-run` 仅检查本地报告与 SMB 根路径，绝不写入 SMB、OSS 或线上链接。真实发布仍须先完成报告复核并取得本次报告的明确批准。

DataForSEO 的 `--dry-run` 也不访问付费接口；自动选词只会使用注册表中当前客户的完整共享 GA4/GSC 月档案。不要在配置中填写旧版 `source_archive` 本机路径；已确认的 `selected_keywords` 例外仍须通过同一客户注册表校验。
