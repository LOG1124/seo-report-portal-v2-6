# 第三方数据使用规则

## 固定分工

- **DataForSEO**：GSC 已筛选机会词的搜索量、CPC、付费竞争度、搜索趋势与少量 SERP 快照。
- **SEOAgent**：优先优化主题、竞品关键词方向与本站外部关键词发现。

两类第三方数据都不能替代 GSC 的搜索表现或 GA4 的流量、互动和关键事件。

## DataForSEO：先确认，再执行

1. 工具只从 `--archive-root` 下、客户注册表中 active 客户的 `<共享根>/ga4-gsc/<真实域名>/<YYYY-MM>.json` 读取当前报告期 GSC 查询词；只有同名非公开 `.json.ready` 能解析且 SHA-256 与单次读取的 JSON 字节一致、存储周期恰为该自然月并含非空 GA4/GSC 时才可读取，不接受配置中的 `source_archive` 路径。
2. 在执行前列出域名、国家/语言、词数、SERP 数、用途和费用上限。
3. 等待明确确认后，先运行 `dataforseo_keyword_enrichment.py --archive-root <共享原始档案根> --dry-run`。它会在读取凭据或请求接口前，验证该月档案的客户、自然月及非空 GA4/GSC 区段。
4. 只有确认仍有效时才运行 `--execute`。
5. 失败时停止并报告；不得自动重试付费请求。

默认试水范围为“5 个重点词市场指标 + 1 个重点词 SERP”。把响应保存到域名隔离的 DataForSEO 归档目录；每个归档必须写入与本次报告完全相同的 `reporting_period` 月份数组。`--execute` 写入 `approval.approved: true`，表示该次执行已经过人工确认。生成报告时通过 `--dataforseo-archive-dir` 显式加载。

## SEOAgent：归档而非核心指标

每位同事在自己电脑上配置其获授权的 SEOAgent MCP。不要将 MCP 地址、Token 或导出的凭据放入工作区、技能包或聊天。

把已批准的查询结果按 `assets/seoagent-archive.example.json` 结构保存到域名隔离的 SEOAgent 归档目录。至少提供：`provider`、`domain`、`collection_month`、`status`、查询范围和三类响应数据，以及精确的 `reporting_period` 和 `approval.approved: true`。

生成报告时通过 `--seoagent-archive-dir` 显式加载。没有两类完全匹配快照时，生成器在付费调用前停止并返回 `THIRD_PARTY_APPROVAL_REQUIRED`；只有用户明确放弃时才可加 `--without-third-party`，并隐藏相应模块。

SEOAgent 的排名、流量、搜索量或 CPC 等估算字段只可作为策略观察，不得写入 GSC/GA4 核心 KPI 或 DataForSEO 市场验证列。
