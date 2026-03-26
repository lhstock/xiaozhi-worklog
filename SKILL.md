---
name: xiaozhi-worklog
description: Use when the current working directory is inside monitored work roots and work sessions should be silently logged, or when the user asks "小志 提供周报" to generate a concise weekly report from those logs.
---

# Xiaozhi Worklog

## Overview

This skill keeps a rolling two-week worklog for monitored project roots and supports the explicit weekly-report persona `小志`.

The worklog records only path-based session results. Project-name mapping is applied later, only during weekly report generation.

## Silent Sync

Before any substantial response:

1. Read `settings.json`.
2. If the current `cwd` is under any `monitored_roots`, run the sync command:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json sync --cwd "$PWD"
```

3. Do not mention the sync unless it fails or the user asks how logging works.
4. If the current `cwd` is not monitored, do nothing.

Sync behavior:

- Source of truth: `~/.codex/sessions`
- Record scope: only monitored project paths
- Record retention: keep the latest 2 weekly buckets
- Record content: concise `request + response` turn pairs keyed by session path and line offset
- Record storage defaults to `/Users/lh/.codex/memories/xiaozhi-worklog` so the sync can write without repeated sandbox friction
- If the harness allows it, `settings.json` may be changed to a different directory

## Xiaozhi Weekly Report

Trigger this flow when the user explicitly asks for `小志 提供周报` or equivalent wording.

Required sequence:

1. Run the silent sync command first.
2. Build the weekly source:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json prepare-report --format markdown
```

3. Read the generated weekly source and write the final report in Chinese.
4. Output only `本周工作内容`.
5. Keep the writing concise but complete.
6. Do not output:
   - timeline narration
   - raw dialogue replay
   - risk/blocker section
   - next-step section
   - chatty openings or closings
7. Group report items by report project name from `report-mapping.json`.
8. Mapping semantics are exact `pwd: 项目名`. Do not use prefix matching.
9. For unmapped paths, fall back to the path basename.
10. The final report format must follow this shape:

```text
${项目名} ${d}d
1. *
2. *
```

11. Here `d` means weekly effort converted from hours, where `8h = 1d`.
12. Do not interpret `d` as “how many calendar days touched this project”.
13. Weekly report writing style is mandatory:
   - use result-oriented summary points, not timeline narration
   - merge the same problem domain, module, or delivery target into one item
   - do not split one issue into separate points such as `排查 / 修改 / 测试 / 提交 / 推送`
   - verification, build, commit, and push are default closing actions, not standalone weekly items, unless they are independent deliverables
   - prefer concise issue-summary wording such as `修复图片文件名重复追加问题并清理 prefix 无效传参`
   - avoid流水线式表达 such as `先排查 / 再修改 / 然后测试 / 最后提交`
   - each item should describe “what was accomplished”, not “what steps were taken”
14. Each numbered item must be a refined weekly summary point, not a raw dialogue replay and not a day-by-day timeline.
15. After drafting the report, stage it but do not archive it yet:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json stage-report <<'EOF'
[paste the final weekly report markdown here]
EOF
```

16. Show the draft to the user and wait for approval.
17. Only archive after the user clearly accepts the draft. Ordinary approval language counts, for example: `可以` / `确认` / `就这样` / `归档`.
18. When approved, archive the staged draft:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json archive-report
```

When the user asks for a specific week, pass `--week YYYY-Www` to `prepare-report`.

If the user requests changes before approval, rewrite the draft and run `stage-report` again so the staged copy matches the latest visible draft.

Example of the preferred style:

```text
odoo-mobile 0.2d
1. 修复图片文件名重复追加问题并清理 prefix 无效传参，完成相关验证后提交代码并推送远端分支。
```

## Project Mapping Management

Trigger this flow when the user asks `小志` to view, set, or delete a project mapping, including natural-language forms such as:

- `小志 查看项目映射`
- `小志 把 /a/project 设为 Alpha`
- `小志 设置项目映射 /a/project:Alpha`
- `小志 删除项目映射 /a/project`

Required behavior:

1. Persist mapping changes to `report-mapping.json`.
2. Use exact `pwd` matching only.
3. Support multiple different `pwd` values pointing to the same project name.

Useful commands:

```bash
python3 scripts/xiaozhi_worklog.py list-mappings --mapping report-mapping.json
python3 scripts/xiaozhi_worklog.py set-mapping --mapping report-mapping.json --pwd "/a/project" --project "Alpha"
python3 scripts/xiaozhi_worklog.py delete-mapping --mapping report-mapping.json --pwd "/a/project"
```

## Config Files

- `settings.json`
  - `monitored_roots`: monitored work roots
  - `session_root`: Codex session directory
  - `timezone`: weekly bucket timezone
  - `data_root`: where records, reports, and sync state live
  - `records_weeks`: weekly record retention count
- `report-mapping.json`
  - `path_map`: exact `pwd: 项目名` dictionary
  - multiple different `pwd` keys may map to one project name

## Data Layout

- `data/records/<week>/worklog.jsonl`
- `data/reports/<week>/xiaozhi-weekly-report-*.md`
- `data/state/sync-state.json`
- `data/state/pending-reports/<week>.md`

When `data_root` points outside the skill directory, the same layout applies under that configured root.
