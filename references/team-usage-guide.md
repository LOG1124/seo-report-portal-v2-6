# 团队使用说明

本说明覆盖每月工作流；同事首次配置 Google、第三方数据、SMB、公盘归档、RAM、ossutil 和发布校验时，先阅读 `references/team-first-run-guide.md`。所有凭据只保存在本机私密目录，不写进 Skill 包、报告或聊天。

同事安装或升级 v2.5 时，只按 `references/team-first-run-guide.md` 的“安装或升级 v2.5”替换全局 Skill 目录。不要重新创建或覆盖客户工作区的 `private/`、Google 服务账号、第三方归档、报告输出或 `~/.codex/config.toml`；旧全局目录必须先移动到备份目录，更新后重启 Codex 即可。

## 管理员可提前完成

在同事开始前，管理员只需准备以下四项；这能把同事的首次配置缩减为“填本机私密文件 + 重启 Codex”。

1. **DataForSEO 账户**：确认账户已可用、已启用 API Access 且有可用余额；决定使用“每人独立凭据”还是“受控团队凭据”。推荐独立凭据，便于额度与权限追踪。
2. **安全交付**：通过密码管理器共享 DataForSEO API Login 与 API Password；不要发送到聊天、邮件正文、ZIP 或共享表格。
3. **SEOAgent 访问权**：为每位同事发放个人 Token（优先）或批准的团队 Token，并确认其有 SEOAgent MCP 使用权限。不要复用管理员的个人 Token。
4. **共同默认范围**：先约定首次试用范围为 United States / English / Google desktop、最多 5 个 GSC 已筛选机会词的市场指标 + 1 个 SERP 快照；每次执行前仍须单独确认域名、范围和费用上限。

将负责人、凭据位置名称和审批人填入 `references/company-access-handover.template.md`；该清单不记录任何密钥本身。

## 首次配置 A：DataForSEO（3 步）

### 第 1 步：建立仅本机可见的凭据文件

在**同事自己的私有工作区**中执行以下命令。以下命令适用于 macOS/Linux；Windows 请改按 [Windows 配置](windows-first-run.md)。若技能安装位置不同，只替换第一行的来源路径；不要修改文件内容之外的任何项目配置。

```bash
mkdir -p private
cp ~/.codex/skills/seo-report-portal-v2-4/assets/dataforseo.env.example private/dataforseo.env
chmod 600 private/dataforseo.env
```

打开 `private/dataforseo.env`，通过密码管理器粘贴管理员提供的两项值：

```dotenv
DATAFORSEO_LOGIN=<API_LOGIN>
DATAFORSEO_PASSWORD=<API_PASSWORD>
```

保存后关闭文件。这个文件必须保持在 `private/`，不能提交、上传、打包或贴进聊天。

### 第 2 步：让 Codex 先生成范围与预算，不执行付费请求

在客户工作区对 Codex 发送：

```text
使用 $seo-report-portal-v2-4 为 <domain> 准备 DataForSEO 试用配置。
只从 <YYYY-MM> 的 GSC 归档中挑选看板需要的机会词；市场为 United States、语言 English、设备 Google desktop。
先列出关键词数、SERP 数、用途与费用上限，并只执行 dry-run；不要发起付费请求。
```

同事应核对：域名、报告月份、关键词确实来自本期 GSC、关键词数不超过 5、SERP 数不超过 1，以及费用上限明确。`dry-run` 不调用外部接口，也不扣费。

### 第 3 步：明确确认后才执行一次

仅在负责人明确回复“确认”且范围与费用上限未变时，才让 Codex 执行。完成后应回报实际请求范围、实际费用（保留原币种）、归档路径和是否成功；失败即停止，**不得自动重试**。

DataForSEO 只提供搜索需求、CPC、付费竞争度、趋势与有限 SERP 快照；它不替代 GSC 的点击、展示、CTR、平均排名，也不替代 GA4 的会话和事件。

## 首次配置 B：SEOAgent MCP（3 步）

### 第 1 步：安全取得 Token

从管理员的密码管理器取得自己的 `<PERSONAL_OR_TEAM_TOKEN>`。不要把真实 Token 发给 Codex、写入报告或放进工作区。管理员应优先提供个人 Token；若使用团队 Token，必须由指定负责人管理轮换与撤销。

### 第 2 步：只追加本机 Codex 配置

打开 `~/.codex/config.toml`，保留所有既有内容，在**文件末尾**追加以下内容；仅把尖括号中的占位符替换成自己从密码管理器取得的 Token：

```toml
[mcp_servers.seoagent]
enabled = true
url = "https://www.seoagent.vip/mcp"

[mcp_servers.seoagent.http_headers]
Authorization = "Bearer <PERSONAL_OR_TEAM_TOKEN>"
```

不要重复添加同名 `[mcp_servers.seoagent]` 表。若已有该表，只核对 `enabled`、`url` 与 `Authorization` 三项并更新 Token；不要删除其他 MCP 配置。

### 第 3 步：重启并做无消费验收

**重启 Codex 桌面应用或 CLI 后再新开任务。**仅新开对话通常不足以重新加载全局 MCP 配置。重启后先检查 MCP 是否显示为 `seoagent`；若未显示，停止并检查 TOML 是否有重复表或引号错误，切勿用真实查询“试试看”。

首次真正采集时，先对 Codex 发送：

```text
使用 $seo-report-portal-v2-5 为 <domain> 的 <YYYY-MM[, YYYY-MM...]> 报告期准备 SEOAgent 策略快照。
查询范围：United States / English；本站关键词最多 20、机会主题最多 20；最多 3 个竞品、每个最多 5 个关键词。
先只给出查询范围、预计费用和归档路径，不发起查询。
```

负责人确认费用上限后才可执行。建议将真实响应规范化后保存在 `workflows/automation/input/seoagent_archive/<domain>/<YYYY-MM>.json`，结构以 `assets/seoagent-archive.example.json` 为准。

SEOAgent 的优先优化主题、竞品关键词方向和本站外部关键词发现属于策略快照；其排名、流量、搜索量或 CPC 估算不能写入 GSC/GA4 核心 KPI，也不能覆盖 DataForSEO 市场验证列。

## 每月工作流

1. 先连接共享原始档案根目录（macOS 示例：`/Volumes/共享盘/seo-report-source-archive`；Windows 使用映射盘或 UNC），并从 `assets/customer-registry.example.json` 创建 `<共享根目录>/customer-registry.json`。每个客户采集前，先登记一条 active 的“真实域名 ↔ 报告 slug”记录。新客户 slug 只能使用小写字母、数字和连字符；只有已存在且目录名刚好等于真实域名的旧公开路径，才可显式加 `legacy_public_slug: true` 保留，不能把该标记用于新客户。
2. 补回 v2.2 本机旧档案时，使用 `import_google_archive.py --archive-root <共享根目录> --source-file <旧 JSON> --month YYYY-MM`；它先验证客户、自然月和非空 GA4/GSC，再按原始字节导入，绝不手工复制、移动、删除或覆盖共享盘文件。来源只能是旧版 GA4/GSC 原始 JSON，不能是 `dashboard-data.json`、`summary.md` 或 `index.html`。采集器/导入器先独占写入 `<共享根目录>/ga4-gsc/<真实域名>/YYYY-MM.json` 并完成同步，再独占写入同名非公开 `.json.ready` SHA-256 标记；只有两者存在且哈希一致才可被生成、发布或自动选词读取，任一异常都停止且绝不覆盖。非 dry-run 的共享归档必须同时采集 GA4 和 GSC；`--dry-run` 可单平台且不写本机数据或共享档案；`--archive-only` 只写共享档案，不更新本机 `collected_data.json`。
3. 生成报告时必须指定同一个 `--archive-root`。月报、季度报告、年度报告分别只接受连续 1、3、12 个月；非标准连续跨度使用 `period`（阶段报告）。缺少任一前序对比月只会标记“对比不可用”，不会伪造或部分比较；当前报告期缺数据仍停止。生成前先复用同客户、同 `reporting_period`、范围一致且已批准的两类第三方快照；缺少任一快照时，先确认新的付费范围和上限，或由用户明确传入 `--without-third-party`。
4. 如要加入市场机会验证，按上面的 DataForSEO 流程：范围与预算 → 明确确认 → 以 `--archive-root <共享根目录>` 从注册表对应的完整当月 GA4/GSC 档案选词 → 执行一次 → 归档；配置不得包含 `source_archive`。
5. 如要加入策略机会，按上面的 SEOAgent 流程：范围与预算 → 明确确认 → 采集 → 按示例结构归档。
6. 使用报告生成器的 `--dataforseo-archive-dir` 和 `--seoagent-archive-dir` 显式载入第三方归档。每份归档须记录本次完整 `reporting_period` 与 `approval.approved: true`；不匹配的客户、范围或快照绝不能替代。
7. 审核本地 HTML、`summary.md` 与内部诊断；得到明确发布授权后，使用 `publish_oss_report.py --source-archive-root <共享根目录>` 发布。它先验证 `source-archive-usage.json`，但仍只发布三件套。若生成使用了仅当期例外，发布命令也必须显式增加 `--allow-current-only`。最终客户回复中的“文字总结”只逐字复制该份已审核 `summary.md` 的 `## 运营总结` 标题与编号正文，不得改写、删减、重排、补充或替换。客户可见的根路径 `/` 一律显示为“首页”，但不改写原始数据；运营总结的页面排行按 GSC 点击量，月报取当月，季报/年报取整个报告期合计；运营总结关键词第 2 条按 GSC 非品牌查询的报告期平均排名，数值越小越靠前；第 6 条国家/地区只按 GA4 `organicGoogleSearchClicks`（Google 搜索自然点击次数）选择，缺失时显示“暂无可用数据”，不得改用会话、GSC 点击或展示。

共享盘使用 guest 读写权限，故原始档案不是保密或抗恶意篡改的存储位置。`oss.env` 中的 `GOOGLE_SOURCE_ARCHIVE_ROOT` 只是方便复制到发布器 `--source-archive-root` 参数的值；采集器和生成器不会隐式读取它，仍必须各自传入 `--archive-root`。本版本以 JSON 和同名非公开 `.json.ready` SHA-256 标记共同定义可用档案；只有两个文件存在且哈希一致、其存储周期恰为该自然月并且 GA4/GSC 均非空时，生成、发布和自动选词才会读取同一份内存快照。该标记用于拒绝半成品和意外不一致，不能防止具有共享写权限的人同时改写两份文件。

若某月出现 `YYYY-MM.json.lock`，停止该客户该月份的所有采集/导入；锁文件记录 hostname、PID 和 UTC 创建时间。任何普通同事都不得删除锁、删除/改名目标 JSON 或用文件管理器手工补写。仅指定维护负责人可恢复，并须先保存锁内容作为故障记录、确认团队没有该月活跃任务：若目标 `YYYY-MM.json` **不存在**，才可移走遗留锁并重试原命令；若目标 **已经存在**，说明不可覆盖提交可能已完成但清理失败，先独立核对目标 SHA-256（导入时必须与本机源 JSON 相同）并记录结果，保留目标文件，随后才可移走锁。若共享盘不支持安全的不可覆盖提交，工具会失败且不创建目标；维护负责人应更换为已验证的 SMB 位置，而不是绕过工具复制文件。

本版本的下列规则取代上段仅检查 JSON 的恢复描述：以 JSON 与 `.json.ready` 为准。两者都不存在时才能移走锁并重试；两者都存在时，先核对 `.ready` 内 SHA-256 与 JSON（导入时还须与本机源 JSON 相同），保留两者后才可移走锁；只存在其中一个、或哈希不一致时是未就绪异常，任何工具都不会读取或覆盖，必须保留现场交维护负责人处理。普通同事同样不得删除、改名或手工补写 `.json.ready`。

## 月报与季报

- 月报使用一个自然月的官方归档。首次归档月不伪造环比。
- 季报要求连续三个月的官方归档；点击、展示、会话等求和，CTR 和平均排名按正式聚合规则计算。
- DataForSEO 的季度快照默认是在季度机会词筛选完成后执行一次，不等于每个月自动重复采集。
- SEOAgent 是采集时点的策略快照，应显示采集时间和市场；它不等于报告期内的官方表现。

## 安全与故障处理

- 第三方归档按域名和采集月份分开保存，绝不改写 Google 月度原始档案。
- DataForSEO 付费调用失败时停止并报告；不得自动重试。
- SEOAgent 估算值不能覆盖 GSC、GA4 或 DataForSEO 的正式字段。
- 缺少任一第三方归档时，先停止并请求付费范围确认；仅在用户明确放弃时用 `--without-third-party` 生成，不用零值伪造第三方结果。
