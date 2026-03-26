import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "worklog_lib.py"
)
CLI_MODULE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "xiaozhi_worklog.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("worklog_lib", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_cli_module():
    sys.path.insert(0, str(CLI_MODULE_PATH.parent))
    spec = importlib.util.spec_from_file_location("xiaozhi_worklog", CLI_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {CLI_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_session(path, cwd, session_id, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {
            "timestamp": "2026-03-25T01:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": "2026-03-25T01:00:00Z",
                "cwd": cwd,
            },
        }
    ]
    lines.extend(events)
    with path.open("w", encoding="utf-8") as fh:
        for item in lines:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def user_message(text, timestamp="2026-03-25T01:00:01Z"):
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def assistant_message(text, phase="final", timestamp="2026-03-25T01:00:02Z"):
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
            "phase": phase,
        },
    }


def write_claude_session(path, cwd, session_id, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {
            "type": "system",
            "subtype": "init",
            "session_id": session_id,
            "cwd": cwd,
            "timestamp": "2026-03-25T01:00:00Z",
        }
    ]
    lines.extend(events)
    with path.open("w", encoding="utf-8") as fh:
        for item in lines:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def claude_user_message(text, timestamp="2026-03-25T01:00:01Z"):
    return {
        "type": "user",
        "timestamp": timestamp,
        "message": {
            "content": [{"type": "text", "text": text}],
        },
    }


def claude_assistant_message(text, timestamp="2026-03-25T01:00:02Z"):
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "content": [{"type": "text", "text": text}],
        },
    }


def git(repo, *args, env=None):
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def git_output(repo, *args, env=None):
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout


class ExtractTurnRecordsTests(unittest.TestCase):
    def test_pairs_latest_user_request_with_final_assistant_message(self):
        module = load_module()
        lines = [
            json.dumps(user_message("<environment_context>\n<cow>skip</cow>")),
            json.dumps(user_message("修复登录页样式")),
            json.dumps(assistant_message("我先检查现有样式。", phase="commentary")),
            json.dumps(assistant_message("已修复登录页样式，并补了移动端对齐。")),
        ]

        records, pending = module.extract_turn_records(
            lines=lines,
            session_id="session-1",
            cwd="/Users/lh/work/funenc/demo",
            source_file="/tmp/session.jsonl",
            start_line=2,
            pending_user=None,
        )

        self.assertIsNone(pending)
        self.assertEqual(1, len(records))
        self.assertEqual("修复登录页样式", records[0]["request"])
        self.assertEqual("已修复登录页样式，并补了移动端对齐。", records[0]["response"])
        self.assertEqual("session-1:5", records[0]["record_id"])

    def test_extracts_claude_code_turns(self):
        module = load_module()
        lines = [
            json.dumps(claude_user_message("梳理发布步骤")),
            json.dumps(claude_assistant_message("已整理发布步骤和回滚方案。")),
        ]

        records, pending = module.extract_turn_records_for_provider(
            provider_type="claude-code",
            lines=lines,
            session_id="claude-1",
            cwd="/Users/lh/work/project-alpha",
            source_file="/tmp/claude.jsonl",
            start_line=2,
            pending_user=None,
        )

        self.assertIsNone(pending)
        self.assertEqual(1, len(records))
        self.assertEqual("梳理发布步骤", records[0]["request"])
        self.assertEqual("已整理发布步骤和回滚方案。", records[0]["response"])


class SettingsTests(unittest.TestCase):
    def test_resolve_settings_migrates_legacy_session_root_to_codex_provider(self):
        module = load_module()

        resolved = module.resolve_settings(
            {
                "session_root": "/tmp/codex-sessions",
                "data_root": "/tmp/data",
                "timezone": "Asia/Shanghai",
                "records_weeks": 2,
            }
        )

        self.assertEqual(1, len(resolved["session_providers"]))
        self.assertEqual("codex", resolved["session_providers"][0]["type"])
        self.assertEqual("/tmp/codex-sessions", resolved["session_providers"][0]["root"])

    def test_open_workbench_defaults_to_port_5555(self):
        module = load_cli_module()
        parser = module.build_parser()

        args = parser.parse_args(["open-workbench"])

        self.assertEqual(5555, args.port)


class SyncTests(unittest.TestCase):
    def test_sync_indexes_projects_without_monitored_root_filter(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            session_root = base / "sessions"
            data_root = base / "data"

            write_session(
                session_root / "2026" / "03" / "25" / "one.jsonl",
                "/Users/lh/work/project-alpha",
                "session-1",
                [
                    user_message("实现订单页"),
                    assistant_message("已完成订单页首屏结构。"),
                ],
            )
            write_session(
                session_root / "2026" / "03" / "25" / "two.jsonl",
                "/Users/lh/work/project-beta",
                "session-2",
                [
                    user_message("整理分析结论"),
                    assistant_message("已整理本周分析结论。"),
                ],
            )

            settings = {
                "session_root": str(session_root),
                "data_root": str(data_root),
                "timezone": "Asia/Shanghai",
                "monitored_roots": [],
                "records_weeks": 2,
            }

            result = module.sync_sessions(
                settings=settings,
                current_cwd="/Users/lh/work/anything",
                now=datetime.fromisoformat("2026-03-25T12:00:00+08:00"),
            )

            self.assertEqual(2, result["projects_touched"])
            index = json.loads(
                (data_root / "index" / "2026-W13" / "projects.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [{"provider": "codex", "session_id": "session-1"}],
                index["projects"]["/Users/lh/work/project-alpha"],
            )
            self.assertEqual(
                [{"provider": "codex", "session_id": "session-2"}],
                index["projects"]["/Users/lh/work/project-beta"],
            )

    def test_sync_keeps_session_ids_unique_per_project_week(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            session_root = base / "sessions"
            data_root = base / "data"
            session_path = session_root / "2026" / "03" / "25" / "one.jsonl"

            write_session(
                session_path,
                "/Users/lh/work/project-alpha",
                "session-1",
                [
                    user_message("实现订单页"),
                    assistant_message("已完成订单页首屏结构。"),
                ],
            )

            settings = {
                "session_root": str(session_root),
                "data_root": str(data_root),
                "timezone": "Asia/Shanghai",
                "monitored_roots": [],
                "records_weeks": 2,
            }

            now = datetime.fromisoformat("2026-03-25T12:00:00+08:00")
            module.sync_sessions(settings=settings, current_cwd="/tmp", now=now)
            module.sync_sessions(settings=settings, current_cwd="/tmp", now=now)

            index = json.loads(
                (data_root / "index" / "2026-W13" / "projects.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [{"provider": "codex", "session_id": "session-1"}],
                index["projects"]["/Users/lh/work/project-alpha"],
            )

    def test_sync_indexes_multiple_providers(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_root = base / "codex"
            claude_root = base / "claude"
            data_root = base / "data"

            write_session(
                codex_root / "2026" / "03" / "25" / "one.jsonl",
                "/Users/lh/work/project-alpha",
                "session-1",
                [
                    user_message("实现订单页"),
                    assistant_message("已完成订单页首屏结构。"),
                ],
            )
            write_claude_session(
                claude_root / "project-alpha" / "claude-1.jsonl",
                "/Users/lh/work/project-alpha",
                "claude-1",
                [
                    claude_user_message("梳理验收步骤"),
                    claude_assistant_message("已梳理验收步骤和注意事项。"),
                ],
            )

            settings = {
                "session_providers": [
                    {"name": "codex", "type": "codex", "root": str(codex_root)},
                    {"name": "claude-code", "type": "claude-code", "root": str(claude_root)},
                ],
                "data_root": str(data_root),
                "timezone": "Asia/Shanghai",
                "records_weeks": 2,
            }

            result = module.sync_sessions(
                settings=settings,
                current_cwd="/tmp",
                now=datetime.fromisoformat("2026-03-25T12:00:00+08:00"),
            )

            self.assertEqual(2, result["projects_touched"])
            index = json.loads(
                (data_root / "index" / "2026-W13" / "projects.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [
                    {"provider": "claude-code", "session_id": "claude-1"},
                    {"provider": "codex", "session_id": "session-1"},
                ],
                sorted(
                    index["projects"]["/Users/lh/work/project-alpha"],
                    key=lambda item: (item["provider"], item["session_id"]),
                ),
            )


class ReportTests(unittest.TestCase):
    def test_prepare_report_uses_git_as_primary_source_and_sessions_as_supplement(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "alpha"
            repo.mkdir()
            git(repo, "init")
            git(repo, "config", "user.name", "Tester")
            git(repo, "config", "user.email", "tester@example.com")

            app_file = repo / "app.txt"
            app_file.write_text("first\n", encoding="utf-8")
            git(repo, "add", "app.txt")
            commit_env = {
                "GIT_AUTHOR_DATE": "2026-03-24T10:00:00+08:00",
                "GIT_COMMITTER_DATE": "2026-03-24T10:00:00+08:00",
            }
            git(repo, "commit", "-m", "feat: 完成订单页首屏", env=commit_env)

            app_file.write_text("first\nsecond\n", encoding="utf-8")
            (repo / "notes.md").write_text("draft\n", encoding="utf-8")

            session_root = base / "sessions"
            data_root = base / "data"
            write_session(
                session_root / "2026" / "03" / "25" / "one.jsonl",
                str(repo),
                "session-1",
                [
                    user_message("梳理订单页验收口径"),
                    assistant_message("已整理订单页验收口径和联调注意事项。"),
                ],
            )

            settings = {
                "session_root": str(session_root),
                "data_root": str(data_root),
                "timezone": "Asia/Shanghai",
                "monitored_roots": [],
                "records_weeks": 2,
            }
            module.sync_sessions(
                settings=settings,
                current_cwd="/tmp",
                now=datetime.fromisoformat("2026-03-25T12:00:00+08:00"),
            )

            report = module.prepare_weekly_source(
                week_id="2026-W13",
                mapping={"path_map": {str(repo): "Alpha 项目"}},
                settings=settings,
            )

            self.assertEqual("2026-W13", report["week"])
            self.assertEqual(1, len(report["projects"]))
            project = report["projects"][0]
            self.assertEqual("Alpha 项目", project["name"])
            self.assertEqual([str(repo)], project["paths"])
            self.assertEqual(1, len(project["git"]["commits"]))
            self.assertEqual("feat: 完成订单页首屏", project["git"]["commits"][0]["subject"])
            self.assertIn("app.txt", project["git"]["working_tree"]["modified"])
            self.assertIn("notes.md", project["git"]["working_tree"]["untracked"])
            self.assertEqual(1, len(project["sessions"]))
            self.assertIn("验收口径", project["sessions"][0]["response"])

    def test_prepare_report_keeps_only_personal_git_commits(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "alpha"
            repo.mkdir()
            git(repo, "init")
            git(repo, "config", "user.name", "Owner")
            git(repo, "config", "user.email", "owner@example.com")

            (repo / "mine.txt").write_text("mine\n", encoding="utf-8")
            git(repo, "add", "mine.txt")
            own_env = {
                "GIT_AUTHOR_DATE": "2026-03-24T10:00:00+08:00",
                "GIT_COMMITTER_DATE": "2026-03-24T10:00:00+08:00",
                "GIT_AUTHOR_NAME": "Owner",
                "GIT_AUTHOR_EMAIL": "owner@example.com",
                "GIT_COMMITTER_NAME": "Owner",
                "GIT_COMMITTER_EMAIL": "owner@example.com",
            }
            git(repo, "commit", "-m", "feat: 完成我的事项", env=own_env)

            (repo / "other.txt").write_text("other\n", encoding="utf-8")
            git(repo, "add", "other.txt")
            other_env = {
                "GIT_AUTHOR_DATE": "2026-03-25T10:00:00+08:00",
                "GIT_COMMITTER_DATE": "2026-03-25T10:00:00+08:00",
                "GIT_AUTHOR_NAME": "Other",
                "GIT_AUTHOR_EMAIL": "other@example.com",
                "GIT_COMMITTER_NAME": "Other",
                "GIT_COMMITTER_EMAIL": "other@example.com",
            }
            git(repo, "commit", "-m", "feat: 别人的提交", env=other_env)

            settings = {
                "session_root": str(base / "sessions"),
                "data_root": str(base / "data"),
                "timezone": "Asia/Shanghai",
                "records_weeks": 2,
                "git_identity": {
                    "emails": ["owner@example.com"],
                    "names": ["Owner"],
                },
            }

            report = module.prepare_weekly_source(
                week_id="2026-W13",
                mapping={"path_map": {str(repo): "Alpha 项目"}},
                settings=settings,
            )

            commits = report["projects"][0]["git"]["commits"]
            self.assertEqual(1, len(commits))
            self.assertEqual("feat: 完成我的事项", commits[0]["subject"])

    def test_prepare_report_reads_claude_code_sessions(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "alpha"
            repo.mkdir()
            git(repo, "init")
            git(repo, "config", "user.name", "Tester")
            git(repo, "config", "user.email", "tester@example.com")
            (repo / "app.txt").write_text("first\n", encoding="utf-8")
            git(repo, "add", "app.txt")
            commit_env = {
                "GIT_AUTHOR_DATE": "2026-03-24T10:00:00+08:00",
                "GIT_COMMITTER_DATE": "2026-03-24T10:00:00+08:00",
            }
            git(repo, "commit", "-m", "feat: 完成首页", env=commit_env)

            claude_root = base / "claude"
            write_claude_session(
                claude_root / "alpha" / "claude-1.jsonl",
                str(repo),
                "claude-1",
                [
                    claude_user_message("补充发布说明"),
                    claude_assistant_message("已补充发布说明和回滚预案。"),
                ],
            )

            settings = {
                "session_providers": [
                    {"name": "claude-code", "type": "claude-code", "root": str(claude_root)},
                ],
                "data_root": str(base / "data"),
                "timezone": "Asia/Shanghai",
                "records_weeks": 2,
            }
            module.sync_sessions(
                settings=settings,
                current_cwd="/tmp",
                now=datetime.fromisoformat("2026-03-25T12:00:00+08:00"),
            )

            report = module.prepare_weekly_source(
                week_id="2026-W13",
                mapping={"path_map": {str(repo): "Alpha 项目"}},
                settings=settings,
            )

            self.assertEqual(1, len(report["projects"][0]["sessions"]))
            self.assertEqual("claude-code", report["projects"][0]["sessions"][0]["provider"])

    def test_render_weekly_report_draft_generates_editable_markdown(self):
        module = load_module()
        draft = module.render_weekly_report_draft(
            {
                "week": "2026-W13",
                "projects": [
                    {
                        "name": "Alpha 项目",
                        "paths": ["/tmp/alpha"],
                        "git": {
                            "commits": [{"subject": "feat: 完成首页", "hash": "abc123", "path": "/tmp/alpha"}],
                            "working_tree": {"modified": ["app.txt"], "untracked": ["notes.md"]},
                        },
                        "sessions": [
                            {
                                "provider": "claude-code",
                                "session_id": "claude-1",
                                "request": "梳理发布说明",
                                "response": "已整理发布说明和回滚预案。",
                                "timestamp": "2026-03-25T01:00:02Z",
                            }
                        ],
                    }
                ],
            }
        )

        self.assertIn("本周工作内容", draft)
        self.assertIn("Alpha 项目", draft)
        self.assertNotIn("feat: 完成首页", draft)
        self.assertNotIn("已整理发布说明和回滚预案。", draft)
        self.assertNotIn("先", draft)
        self.assertNotIn("然后", draft)
        self.assertIn("首页", draft)
        self.assertIn("发布说明", draft)

    def test_render_weekly_report_draft_prefers_git_and_summarizes_in_chinese(self):
        module = load_module()
        draft = module.render_weekly_report_draft(
            {
                "week": "2026-W13",
                "projects": [
                    {
                        "name": "香港DOS系统项目",
                        "paths": ["/tmp/dos"],
                        "git": {
                            "commits": [
                                {"subject": "fix: 修复列车看板筛选异常", "hash": "a1", "path": "/tmp/dos"},
                                {"subject": "feat: 补充打印模板配置", "hash": "a2", "path": "/tmp/dos"},
                            ],
                            "working_tree": {"modified": ["src/print.ts"], "untracked": ["docs/train.md"]},
                        },
                        "sessions": [
                            {
                                "provider": "codex",
                                "session_id": "s1",
                                "request": "排查列车看板筛选异常",
                                "response": "已修复列车看板筛选异常并整理打印模板配置说明。",
                                "timestamp": "2026-03-25T01:00:02Z",
                            }
                        ],
                    }
                ],
            }
        )

        self.assertIn("香港DOS系统项目", draft)
        self.assertIn("列车看板筛选", draft)
        self.assertIn("打印模板", draft)
        self.assertNotIn("fix: 修复列车看板筛选异常", draft)
        self.assertNotIn("已修复列车看板筛选异常并整理打印模板配置说明。", draft)
        self.assertNotIn("相关内容收敛", draft)
        self.assertNotIn("技术", draft)

    def test_render_weekly_report_draft_groups_related_signals_into_one_result_item(self):
        module = load_module()
        draft = module.render_weekly_report_draft(
            {
                "week": "2026-W13",
                "projects": [
                    {
                        "name": "厦门天马G5.5纯水BI系统",
                        "paths": ["/tmp/bi"],
                        "git": {
                            "commits": [
                                {"subject": "feat: add cycle column to maintenance plan", "hash": "a1", "path": "/tmp/bi"},
                                {"subject": "docs: add view2 design spec", "hash": "a2", "path": "/tmp/bi"},
                            ],
                            "working_tree": {"modified": ["src/pages/maintenance/DataTable.jsx"], "untracked": []},
                        },
                        "sessions": [
                            {
                                "provider": "codex",
                                "session_id": "s1",
                                "request": "每年的 mock 数据七条数据出现一次即可",
                                "response": "已按规则补齐周期列、mock 数据分布和相关测试验证。",
                                "timestamp": "2026-03-25T01:00:02Z",
                            }
                        ],
                    }
                ],
            }
        )

        self.assertIn("维保计划", draft)
        self.assertIn("周期", draft)
        self.assertIn("mock", draft)
        self.assertIn("测试", draft)
        self.assertNotIn("docs: add view2 design spec", draft)
        self.assertNotIn("feat: add cycle column to maintenance plan", draft)
        self.assertLessEqual(draft.count("\n1. "), 1)
        self.assertNotIn("实现细节", draft)

    def test_build_workbench_payload_exposes_draft_info_and_index_status(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data_root = base / "data"
            index_dir = data_root / "index" / "2026-W13"
            index_dir.mkdir(parents=True, exist_ok=True)
            (index_dir / "projects.json").write_text(
                json.dumps(
                    {
                        "week": "2026-W13",
                        "projects": {
                            "/tmp/alpha": [
                                {"provider": "codex", "session_id": "session-1"},
                                {"provider": "claude-code", "session_id": "claude-1"},
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            settings = {
                "session_providers": [
                    {"name": "codex", "type": "codex", "root": str(base / "codex")},
                    {"name": "claude-code", "type": "claude-code", "root": str(base / "claude")},
                ],
                "data_root": str(data_root),
                "timezone": "Asia/Shanghai",
                "records_weeks": 2,
            }
            payload = module.build_workbench_payload(
                settings=settings,
                mapping={"path_map": {"/tmp/alpha": "Alpha 项目"}},
                week_id="2026-W13",
                draft="本周工作内容\n\nAlpha 项目 0.5d\n1. 完成首页。\n",
            )

            self.assertEqual("2026-W13", payload["week"])
            self.assertIn("Alpha 项目", payload["draft"])
            self.assertEqual("小志", payload["skill"]["name"])
            self.assertEqual(1, len(payload["index_status"]["projects"]))
            self.assertEqual(2, payload["index_status"]["projects"][0]["session_count"])

    def test_render_workbench_html_contains_textarea_and_actions(self):
        module = load_module()
        html = module.render_workbench_html(
            {
                "week": "2026-W13",
                "draft": "本周工作内容",
                "skill": {"name": "小志", "description": "统一入口"},
                "index_status": {"projects": []},
                "source": {"week": "2026-W13", "projects": []},
            }
        )

        self.assertIn("textarea", html)
        self.assertIn("复制", html)
        self.assertIn("确认归档", html)
        self.assertIn("/api/archive", html)
        self.assertNotIn("索引状态", html)
        self.assertNotIn("技能信息", html)
        self.assertNotIn("原始周报来源", html)

    def test_archive_marks_workbench_for_shutdown(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            now = datetime.fromisoformat("2026-03-25T12:00:00+08:00")
            module.stage_weekly_report(
                data_root=data_root,
                week_id="2026-W13",
                content="本周工作内容\n\nAlpha 0.1d\n1. 完成事项。\n",
                now=now,
            )

            settings = {
                "session_root": str(Path(tmp) / "sessions"),
                "data_root": str(data_root),
                "timezone": "Asia/Shanghai",
                "records_weeks": 2,
            }
            state = module.WorkbenchState(
                settings=module.resolve_settings(settings),
                mapping={"path_map": {}},
                week_id="2026-W13",
            )
            module.finalize_workbench_archive(
                state=state,
                content="本周工作内容\n\nAlpha 0.1d\n1. 完成事项。\n",
            )

            self.assertTrue(state.get_payload()["should_close"])

    def test_prepare_report_aggregates_multiple_paths_into_one_project(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo_a = base / "alpha-app"
            repo_b = base / "alpha-admin"
            repo_a.mkdir()
            repo_b.mkdir()

            for repo, subject in (
                (repo_a, "feat: 完成前台首页"),
                (repo_b, "fix: 修复管理台筛选"),
            ):
                git(repo, "init")
                git(repo, "config", "user.name", "Tester")
                git(repo, "config", "user.email", "tester@example.com")
                (repo / "main.txt").write_text(subject, encoding="utf-8")
                git(repo, "add", "main.txt")
                commit_env = {
                    "GIT_AUTHOR_DATE": "2026-03-24T10:00:00+08:00",
                    "GIT_COMMITTER_DATE": "2026-03-24T10:00:00+08:00",
                }
                git(repo, "commit", "-m", subject, env=commit_env)

            settings = {
                "session_root": str(base / "sessions"),
                "data_root": str(base / "data"),
                "timezone": "Asia/Shanghai",
                "monitored_roots": [],
                "records_weeks": 2,
            }

            report = module.prepare_weekly_source(
                week_id="2026-W13",
                mapping={
                    "path_map": {
                        str(repo_a): "Alpha 项目",
                        str(repo_b): "Alpha 项目",
                    }
                },
                settings=settings,
            )

            self.assertEqual(1, len(report["projects"]))
            project = report["projects"][0]
            self.assertEqual(2, len(project["paths"]))
            self.assertEqual(2, len(project["git"]["commits"]))

    def test_render_weekly_source_markdown_mentions_git_and_session_sections(self):
        module = load_module()
        source = {
            "week": "2026-W13",
            "projects": [
                {
                    "name": "Alpha 项目",
                    "paths": ["/tmp/alpha"],
                    "git": {
                        "commits": [{"subject": "feat: 完成首页", "hash": "abc123", "path": "/tmp/alpha"}],
                        "working_tree": {"modified": ["app.txt"], "untracked": ["notes.md"]},
                    },
                    "sessions": [
                        {
                            "request": "梳理验收口径",
                            "response": "已整理验收口径。",
                            "timestamp": "2026-03-25T01:00:02Z",
                            "session_id": "session-1",
                        }
                    ],
                }
            ],
        }

        rendered = module.render_weekly_source_markdown(source)

        self.assertIn("Git commits", rendered)
        self.assertIn("Session context", rendered)
        self.assertIn("feat: 完成首页", rendered)


class MappingTests(unittest.TestCase):
    def test_set_and_delete_mapping_persist_exact_pwd_mapping(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            mapping_path = Path(tmp) / "report-mapping.json"
            mapping_path.write_text('{"path_map": {}}', encoding="utf-8")

            updated = module.set_mapping(mapping_path, "/a/project", "Alpha")
            self.assertEqual({"path_map": {"/a/project": "Alpha"}}, updated)

            listed = module.load_mapping(mapping_path)
            self.assertEqual("Alpha", listed["path_map"]["/a/project"])

            updated = module.delete_mapping(mapping_path, "/a/project")
            self.assertEqual({"path_map": {}}, updated)


class DraftArchiveTests(unittest.TestCase):
    def test_stage_then_archive_report(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            now = datetime.fromisoformat("2026-03-25T12:00:00+08:00")

            draft_path = module.stage_weekly_report(
                data_root=data_root,
                week_id="2026-W13",
                content="# 本周工作内容\n\n## Alpha\n- 已完成接口联调。\n",
                now=now,
            )
            self.assertTrue(draft_path.exists())

            archived = module.archive_staged_report(
                data_root=data_root,
                week_id="2026-W13",
                now=now,
            )
            self.assertTrue(archived.exists())
            self.assertFalse(draft_path.exists())
            self.assertIn("本周工作内容", archived.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
