# Xiaozhi Worklog Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a global Codex skill that silently syncs monitored project session logs into weekly records and supports the `小志 提供周报` weekly-report workflow.

**Architecture:** Stage the skill inside this workspace under `.codex/skills/xiaozhi-worklog`, with a small Python runtime that performs incremental session syncing, weekly source preparation, and final report backup. The skill itself stays thin: it silently runs sync on monitored paths, and when explicitly asked for `小志 提供周报`, it loads prepared weekly context, writes the concise report, and saves the exact output.

**Tech Stack:** Markdown skill files, JSON config/state files, Python 3 stdlib (`json`, `pathlib`, `datetime`, `zoneinfo`, `argparse`), `unittest`.

---

## Chunk 1: Scaffold And Tests

### Task 1: Create the staged skill layout

**Files:**
- Create: `.codex/skills/xiaozhi-worklog/SKILL.md`
- Create: `.codex/skills/xiaozhi-worklog/agents/openai.yaml`
- Create: `.codex/skills/xiaozhi-worklog/settings.json`
- Create: `.codex/skills/xiaozhi-worklog/report-mapping.json`
- Create: `.codex/skills/xiaozhi-worklog/scripts/xiaozhi_worklog.py`
- Create: `.codex/skills/xiaozhi-worklog/scripts/worklog_lib.py`
- Create: `tests/test_xiaozhi_worklog.py`

- [ ] **Step 1: Write the failing test**

```python
def test_placeholder():
    raise AssertionError("scaffold pending")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_xiaozhi_worklog -v`
Expected: FAIL with the placeholder assertion.

- [ ] **Step 3: Replace placeholder with real failing tests**

```python
class ExtractTurnRecordsTests(unittest.TestCase):
    ...
```

- [ ] **Step 4: Run tests to verify they fail for missing implementation**

Run: `python3 -m unittest tests.test_xiaozhi_worklog -v`
Expected: FAIL with import or missing-function errors.

## Chunk 2: Incremental Sync Core

### Task 2: Implement session parsing and incremental state

**Files:**
- Modify: `.codex/skills/xiaozhi-worklog/scripts/worklog_lib.py`
- Modify: `.codex/skills/xiaozhi-worklog/scripts/xiaozhi_worklog.py`
- Test: `tests/test_xiaozhi_worklog.py`

- [ ] **Step 1: Write the failing sync tests**

```python
def test_sync_records_only_monitored_sessions(self):
    ...
```

- [ ] **Step 2: Run the sync tests to verify they fail**

Run: `python3 -m unittest tests.test_xiaozhi_worklog.SyncTests -v`
Expected: FAIL because sync code does not exist yet.

- [ ] **Step 3: Write minimal sync implementation**

```python
def sync_sessions(...):
    ...
```

- [ ] **Step 4: Run the sync tests to verify they pass**

Run: `python3 -m unittest tests.test_xiaozhi_worklog.SyncTests -v`
Expected: PASS.

## Chunk 3: Weekly Source And Backup

### Task 3: Implement weekly source preparation and report backup

**Files:**
- Modify: `.codex/skills/xiaozhi-worklog/scripts/worklog_lib.py`
- Modify: `.codex/skills/xiaozhi-worklog/scripts/xiaozhi_worklog.py`
- Modify: `.codex/skills/xiaozhi-worklog/SKILL.md`
- Modify: `.codex/skills/xiaozhi-worklog/agents/openai.yaml`
- Test: `tests/test_xiaozhi_worklog.py`

- [ ] **Step 1: Write the failing report tests**

```python
def test_prepare_report_groups_paths_by_mapping(self):
    ...
```

- [ ] **Step 2: Run the report tests to verify they fail**

Run: `python3 -m unittest tests.test_xiaozhi_worklog.ReportTests -v`
Expected: FAIL because report preparation or backup is missing.

- [ ] **Step 3: Write minimal report implementation**

```python
def prepare_weekly_source(...):
    ...
```

- [ ] **Step 4: Run the report tests to verify they pass**

Run: `python3 -m unittest tests.test_xiaozhi_worklog.ReportTests -v`
Expected: PASS.

## Chunk 4: Validation And Install

### Task 4: Validate the skill package and install it globally

**Files:**
- Modify: `.codex/skills/xiaozhi-worklog/**`

- [ ] **Step 1: Run the full local test suite**

Run: `python3 -m unittest tests.test_xiaozhi_worklog -v`
Expected: PASS.

- [ ] **Step 2: Run skill validation**

Run: `python3 /Users/lh/.codex/skills/.system/skill-creator/scripts/quick_validate.py .codex/skills/xiaozhi-worklog`
Expected: `Skill is valid!`

- [ ] **Step 3: Install the staged skill into the global skills directory**

Run: `cp -R .codex/skills/xiaozhi-worklog /Users/lh/.codex/skills/xiaozhi-worklog`
Expected: skill files copied into the global personal skills directory.

- [ ] **Step 4: Summarize the installed paths and usage**

```text
Report the skill path, config files, and the `小志 提供周报` trigger.
```
