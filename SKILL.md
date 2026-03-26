---
name: xiaozhi-worklog
description: Use when work sessions from supported AI coding tools should be silently indexed by exact project `pwd`, or when the user asks `小志` for weekly reports, mappings, index status, skill info, or the one-shot workbench page.
---

# Xiaozhi Worklog

## Overview

This skill keeps a rolling two-week project-touch index from supported raw session providers and exposes the persona-style skill entry `小志`.

Silent sync records only which exact project `pwd` values were touched by which session in which week. Project-name mapping is applied later, only during weekly report generation.

## Silent Sync

Before any substantial response:

1. Read `settings.json`.
2. Run the sync command:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json sync --cwd "$PWD"
```

3. Do not mention the sync unless it fails or the user asks how logging works.
Sync behavior:

- Source of truth: configured `session_providers`
- Supported provider types: `codex`, `claude-code`
- Record scope: any session that has a `cwd`
- Record retention: keep the latest 2 weekly buckets
- Record content: lightweight weekly `pwd -> [{provider, session_id}]` touch index only
- Record storage defaults to `/Users/lh/.codex/memories/xiaozhi-worklog` so the sync can write without repeated sandbox friction
- If the harness allows it, `settings.json` may be changed to a different directory

## Xiaozhi Persona

`小志` is the skill persona name, not only the weekly-report trigger.

Supported intents include:

- `小志 提供周报`
- `小志 打开周报工作台`
- `小志 查看索引状态`
- `小志 查看技能信息`
- `小志 查看项目映射`
- `小志 设置项目映射 /a/project:Alpha`
- `小志 删除项目映射 /a/project`

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
9. Weekly report uses git as the primary source and raw sessions as supplemental context.
10. Only mapped paths participate in the grouped weekly report.
11. The final report format must follow this shape:

```text
${项目名} ${d}d
1. *
2. *
```

12. Here `d` means weekly effort converted from hours, where `8h = 1d`.
13. Do not interpret `d` as “how many calendar days touched this project”.
14. Weekly report writing style is mandatory:
   - group by `项目 + 模块级事项`, not by raw commit or conversation fragments
   - use result-oriented summary points, not timeline narration
   - merge the same problem domain, module, or delivery target into one item
   - treat `成果 / 进度 / 功能 / 测试 / 调研` as clustering signals, not as fixed output headings
   - keep each project within `3-7` points when possible; merge aggressively before adding new bullets
   - do not split one issue into separate points such as `排查 / 修改 / 测试 / 提交 / 推送`
   - verification, build, commit, and push are default closing actions, not standalone weekly items, unless they are independent deliverables
   - remove repeated wording such as `完成调整` / `收敛说明` / `相关内容收敛`
   - use concise management-facing verbs such as `完成` / `优化` / `推进` / `完善`
   - avoid流水线式表达 such as `先排查 / 再修改 / 然后测试 / 最后提交`
   - avoid concrete technical details such as commit messages, code symbols, or low-level implementation notes
   - each item should describe “what was accomplished”, not “what steps were taken”
15. Each numbered item must be a refined weekly summary point, not a raw dialogue replay and not a day-by-day timeline.
16. After drafting the report, stage it but do not archive it yet:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json stage-report <<'EOF'
[paste the final weekly report markdown here]
EOF
```

17. Show the draft to the user and wait for approval.
18. Only archive after the user clearly accepts the draft. Ordinary approval language counts, for example: `可以` / `确认` / `就这样` / `归档`.
19. When approved, archive the staged draft:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json archive-report
```

When the user asks for a specific week, pass `--week YYYY-Www` to `prepare-report`.

If the user requests changes before approval, rewrite the draft and run `stage-report` again so the staged copy matches the latest visible draft.

## Xiaozhi Workbench

Trigger this flow when the user asks `小志` to open the report workbench or asks for a page-based edit/confirm flow.

Start the one-shot local workbench:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json open-workbench --mapping report-mapping.json
```

Behavior:

- starts a one-shot local HTTP page
- shows the editable weekly report draft in a textarea
- provides actions for save draft, regenerate, copy, and archive
- keeps the page focused on draft editing and confirmation, without a right-side info panel
- prints the local URL to stdout so the caller can open it

The page uses server-sent events for live state refresh from the local runtime.

Example of the preferred style:

```text
厦门天马G5.5纯水BI系统 0.8d
1. 完成维保计划模块优化，完善周期信息呈现与相关业务规则。
2. 推进核心看板能力完善，补充关键场景下的数据支撑。
3. 优化模块联调与验证安排，保障阶段性成果稳定落地。
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

## Xiaozhi Status And Info

Useful commands:

```bash
python3 scripts/xiaozhi_worklog.py --settings settings.json info
python3 scripts/xiaozhi_worklog.py --settings settings.json index-status --mapping report-mapping.json
```

## Config Files

- `settings.json`
  - `session_providers`: provider list with exact `name`, `type`, and transcript `root`
  - `session_root`: legacy Codex-only compatibility field
  - `timezone`: weekly bucket timezone
  - `data_root`: where index, reports, and sync state live
  - `records_weeks`: weekly retention count for the project-touch index
- `report-mapping.json`
  - `path_map`: exact `pwd: 项目名` dictionary
  - multiple different `pwd` keys may map to one project name

## Data Layout

- `data/index/<week>/projects.json`
  - value shape: `pwd -> [{provider, session_id}]`
- `data/reports/<week>/xiaozhi-weekly-report-*.md`
- `data/state/sync-state.json`
- `data/state/pending-reports/<week>.md`

When `data_root` points outside the skill directory, the same layout applies under that configured root.
