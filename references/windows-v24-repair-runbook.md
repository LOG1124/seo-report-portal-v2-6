---
meta:
  contentType: How-to
title: Let Codex update v2.5 and recover all local archives on Windows
---

# Let Codex update v2.5 and recover all local archives on Windows

Attach this file to a new Codex task opened from the top-level folder that contains the colleague’s customer projects. Codex updates v2.5 from GitHub, tests the UNC share with synthetic data, and imports valid legacy archives from every project below that workspace. The colleague only approves narrowly scoped filesystem actions and restarts Codex after the final report.

## What this task completes

Codex installs the current GitHub `main` version of v2.5, runs the no-customer-data UNC safety test, and recovers eligible local v2.2 GA4 and GSC monthly archives to the shared source archive. The update includes the 小语种首页 display rule: only the unparameterized English homepage on the customer’s primary domain displays as `首页`; language homepages display their complete GSC URL in the next newly generated report.

This task does not regenerate or publish a dashboard. It also does not collect missing Google data. A later, separately approved report run can use the imported archives.

## What the colleague does

1. Open a new Codex task from the top-level folder containing the colleague’s customer projects and attach this file
2. Send: `请严格执行附件。完成后只返回最终中文汇总。`
3. Approve only the file and Git actions described in this file
4. Restart Codex after its final report

If Codex reports that Git or `py -3` is missing, the colleague must arrange that prerequisite. Codex must not install software itself.

## Task instruction for Codex

Complete this repair without asking the colleague to select customer projects, files, or months. Set the current Codex workspace as the workspace root and record its absolute path. Work in PowerShell and follow every boundary below.

### Scope and safety boundaries

- Update only from `https://github.com/LOG1124/seo-report-portal-v2-4.git`, branch `main`
- Follow the Windows GitHub update procedure in `references/team-first-run-guide.md`; use its Git source directory, safety checks, backup procedure, and install target exactly
- 不得读取、输出、复制或改写任何密钥，包括 `private/`、Google 服务账号文件、DataForSEO 凭据、OSS 凭据、SEOAgent Token 或 `~/.codex/config.toml`
- Do not modify the existing `seo-report-portal-v2-2` Skill directory
- 不得扫描整个磁盘。只在当前 Codex 工作区根目录内递归查找 `**\workflows\automation\input\google_api_archive\*.json` 的旧 JSON 候选，不得访问该根目录以外的位置
- Do not edit `\\192.168.110.26\共享盘\seo-report-source-archive\customer-registry.json`
- Do not call Google, GA4, GSC, DataForSEO, SEOAgent, OSS, or any paid service
- Do not publish, regenerate, move, or delete customer reports
- Do not use File Explorer, `Copy-Item`, or any manual copy method to write shared raw archives

If Git or `py -3` is unavailable, stop before changing files and report the missing prerequisite. Do not install software automatically.

### Update v2.5 from GitHub

First complete the guide’s Windows GitHub update procedure. It must stop if the Git source, staging content, or existing v2.5 Skill directory contains `private/`. Keep the Git source outside the installed Skill directory. Verify that this installed script exists before continuing:

```text
%USERPROFILE%\.codex\skills\seo-report-portal-v2-5\scripts\import_google_archive.py
```

Record the checked-out commit ID. Do not use a ZIP distributed from chat or a local folder as the update source.

### Test the UNC share without customer data

Before processing any customer file, run one synthetic test under the exact UNC root:

```text
\\192.168.110.26\共享盘\seo-report-source-archive
```

Create a unique GUID child directory beginning `.v2-3-windows-unc-pilot-`. Inside that child only, create a one-record `customer-registry.json` for `example.com` with slug `example-com`. Create one temporary local JSON with exactly these safe values:

```json
{
  "domain": "example.com",
  "period": ["2026-07-01", "2026-07-31"],
  "ga4": {"session_count": 1},
  "gsc": {"organic_clicks": 1}
}
```

Use the installed `import_google_archive.py` to import that file for `2026-07`. Confirm all of these conditions:

1. The JSON appears only below the GUID child directory
2. A sibling `.json.ready` file appears
3. The local source SHA-256 equals the shared JSON SHA-256
4. A second import of the same file and month fails because the archive already exists
5. The shared JSON SHA-256 remains unchanged after the rejected second import

Delete only the GUID child directory and the temporary local synthetic JSON in a `finally` cleanup step. If any test condition fails, stop. Do not touch real customer directories. Return `WINDOWS_UNC_PILOT_PASS` only after every condition and cleanup succeeds.

### Recover valid local v2.2 archives

After the UNC pilot passes, recursively inspect only `**\workflows\automation\input\google_api_archive\*.json` below the current Codex workspace root. Do not depend on customer project folder names. Record every discovered archive directory, then read each JSON file without printing its content. Import it only when all conditions pass:

1. The JSON object has a registered active `domain` in the shared `customer-registry.json`
2. Its `period` is exactly one natural calendar month
3. Both `ga4` and `gsc` are present and non-empty
4. The target shared month does not already exist

For every valid candidate, call the installed `import_google_archive.py` with the exact UNC root, source file, and derived `YYYY-MM`. The importer must retain the local source file and create the destination plus `.ready` marker. Independently compare the source and destination SHA-256 after each successful import.

If a target already exists, never overwrite it. Compare hashes only when safe, then report either `duplicate: identical` or `conflict: different`; leave both source and target unchanged. If a candidate is invalid, unregistered, partial, malformed, or not a natural month, skip it and report the reason. Continue with other candidates.

If no matching legacy archive directory exists or no valid file is found, report the workspace root and the discovered archive-directory count. Do not use dashboard output as a source. Do not create substitute data. Do not search elsewhere on the disk.

### Stop before re-collection or publication

不得自行重新采集 Google 数据。对每个没有有效旧档案的客户月份，只回报域名和月份为 `NEEDS_RECOLLECTION_APPROVAL`。必须由负责人单独明确授权该客户月份的 GA4/GSC 只读采集。

Do not generate or publish reports during this task. A migrated archive only repairs the source-history prerequisite for a later, separately approved report run.

### Final report and handoff

Return a concise Chinese report with these fields:

- GitHub update status, checked-out commit, and whether the previous v2.5 Skill was backed up
- Workspace root and discovered legacy archive directories
- UNC pilot status, GUID path, source and destination SHA-256, repeated-import rejection, and cleanup status
- Imported archives: domain, month, local source path, shared destination path, and SHA-256
- Skipped or conflicting archives: path, non-sensitive reason, and whether any shared file was changed
- `NEEDS_RECOLLECTION_APPROVAL` items, if any
- Confirmation that no credential, Google, third-party provider, OSS, report publication, or customer-report modification occurred

Do not include JSON content, credentials, tokens, cookies, service-account details, or report content in the final report. Ask the colleague only to restart Codex after the task finishes.
