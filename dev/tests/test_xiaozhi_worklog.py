import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "worklog_lib.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("worklog_lib", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_session(path, cwd, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {
            "timestamp": "2026-03-25T01:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "session-1",
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

    def test_accepts_real_final_answer_phase(self):
        module = load_module()
        lines = [
            json.dumps(user_message("整理周报入口")),
            json.dumps(assistant_message("已补周报入口和触发命令。", phase="final_answer")),
        ]

        records, pending = module.extract_turn_records(
            lines=lines,
            session_id="session-2",
            cwd="/Users/lh/work/funenc/demo",
            source_file="/tmp/session.jsonl",
            start_line=2,
            pending_user=None,
        )

        self.assertIsNone(pending)
        self.assertEqual(1, len(records))
        self.assertEqual("整理周报入口", records[0]["request"])


class SyncTests(unittest.TestCase):
    def test_sync_records_only_monitored_sessions(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            session_root = base / "sessions"
            record_root = base / "data"

            monitored = session_root / "2026" / "03" / "25" / "one.jsonl"
            ignored = session_root / "2026" / "03" / "25" / "two.jsonl"

            write_session(
                monitored,
                "/Users/lh/work/funenc/project-a",
                [
                    user_message("实现订单页"),
                    assistant_message("已完成订单页首屏结构。"),
                ],
            )
            write_session(
                ignored,
                "/Users/lh/work/other/project-b",
                [
                    user_message("实现别的项目"),
                    assistant_message("已完成。"),
                ],
            )

            settings = {
                "session_root": str(session_root),
                "data_root": str(record_root),
                "timezone": "Asia/Shanghai",
                "monitored_roots": ["/Users/lh/work/funenc"],
                "records_weeks": 2,
            }

            result = module.sync_sessions(
                settings=settings,
                current_cwd="/Users/lh/work/funenc/project-a",
                now=datetime.fromisoformat("2026-03-25T12:00:00+08:00"),
            )

            self.assertEqual(1, result["new_records"])
            weekly_file = record_root / "records" / "2026-W13" / "worklog.jsonl"
            rows = [
                json.loads(line)
                for line in weekly_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(1, len(rows))
            self.assertEqual("/Users/lh/work/funenc/project-a", rows[0]["cwd"])
            self.assertEqual("已完成订单页首屏结构。", rows[0]["response"])

    def test_prune_keeps_only_two_latest_weeks(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            records_dir = Path(tmp) / "data" / "records"
            for week in ("2026-W11", "2026-W12", "2026-W13"):
                week_dir = records_dir / week
                week_dir.mkdir(parents=True, exist_ok=True)
                (week_dir / "worklog.jsonl").write_text("", encoding="utf-8")

            module.prune_weekly_records(
                record_root=records_dir,
                keep_weeks=2,
                now=datetime.fromisoformat("2026-03-25T12:00:00+08:00"),
                timezone_name="Asia/Shanghai",
            )

            self.assertFalse((records_dir / "2026-W11").exists())
            self.assertTrue((records_dir / "2026-W12").exists())
            self.assertTrue((records_dir / "2026-W13").exists())


class ReportTests(unittest.TestCase):
    def test_prepare_report_groups_paths_by_mapping(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            weekly_dir = base / "data" / "records" / "2026-W13"
            weekly_dir.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "record_id": "a",
                    "week": "2026-W13",
                    "cwd": "/Users/lh/work/funenc/alpha/app",
                    "request": "实现登录页",
                    "response": "已完成登录页骨架和表单校验。",
                    "timestamp": "2026-03-25T01:00:02Z",
                },
                {
                    "record_id": "b",
                    "week": "2026-W13",
                    "cwd": "/Users/lh/work/funenc/alpha/admin",
                    "request": "补管理台筛选",
                    "response": "已补管理台筛选和列表空态。",
                    "timestamp": "2026-03-25T02:00:02Z",
                },
                {
                    "record_id": "c",
                    "week": "2026-W13",
                    "cwd": "/Users/lh/work/funenc/beta",
                    "request": "修复图表",
                    "response": "已修复图表缩放和图例重叠。",
                    "timestamp": "2026-03-25T03:00:02Z",
                },
            ]
            with (weekly_dir / "worklog.jsonl").open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

            mapping = {
                "projects": [
                    {
                        "name": "Alpha 项目",
                        "paths": [
                            "/Users/lh/work/funenc/alpha/app",
                            "/Users/lh/work/funenc/alpha/admin",
                        ],
                    }
                ]
            }

            report = module.prepare_weekly_source(
                records_root=base / "data" / "records",
                week_id="2026-W13",
                mapping=mapping,
            )

            self.assertEqual("2026-W13", report["week"])
            self.assertEqual(2, len(report["projects"]))
            self.assertEqual("Alpha 项目", report["projects"][0]["name"])
            self.assertEqual(2, len(report["projects"][0]["items"]))
            self.assertEqual("beta", report["projects"][1]["name"])

    def test_prepare_report_uses_exact_pwd_mapping_only(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            weekly_dir = base / "data" / "records" / "2026-W13"
            weekly_dir.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "record_id": "a",
                    "week": "2026-W13",
                    "cwd": "/Users/lh/work/funenc/alpha",
                    "request": "实现登录页",
                    "response": "已完成登录页。",
                    "timestamp": "2026-03-25T01:00:02Z",
                },
                {
                    "record_id": "b",
                    "week": "2026-W13",
                    "cwd": "/Users/lh/work/funenc/alpha/sub",
                    "request": "补二级页面",
                    "response": "已完成二级页面。",
                    "timestamp": "2026-03-25T02:00:02Z",
                },
            ]
            with (weekly_dir / "worklog.jsonl").open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

            mapping = {
                "path_map": {
                    "/Users/lh/work/funenc/alpha": "Alpha 项目",
                }
            }

            report = module.prepare_weekly_source(
                records_root=base / "data" / "records",
                week_id="2026-W13",
                mapping=mapping,
            )

            self.assertEqual("Alpha 项目", report["projects"][0]["name"])
            self.assertEqual("sub", report["projects"][1]["name"])

    def test_prepare_report_counts_distinct_work_days(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            weekly_dir = base / "data" / "records" / "2026-W13"
            weekly_dir.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "record_id": "a",
                    "week": "2026-W13",
                    "cwd": "/Users/lh/work/funenc/alpha",
                    "request": "实现登录页",
                    "response": "已完成登录页。",
                    "timestamp": "2026-03-24T01:00:02Z",
                },
                {
                    "record_id": "b",
                    "week": "2026-W13",
                    "cwd": "/Users/lh/work/funenc/alpha",
                    "request": "补管理台",
                    "response": "已补管理台。",
                    "timestamp": "2026-03-24T11:00:02Z",
                },
                {
                    "record_id": "c",
                    "week": "2026-W13",
                    "cwd": "/Users/lh/work/funenc/alpha",
                    "request": "修复图表",
                    "response": "已修复图表。",
                    "timestamp": "2026-03-25T03:00:02Z",
                },
            ]
            with (weekly_dir / "worklog.jsonl").open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

            report = module.prepare_weekly_source(
                records_root=base / "data" / "records",
                week_id="2026-W13",
                mapping={"path_map": {}},
            )

            self.assertEqual(2, report["projects"][0]["days"])

    def test_render_weekly_source_markdown_includes_project_days(self):
        module = load_module()
        source = {
            "week": "2026-W13",
            "projects": [
                {
                    "name": "香港DOS系统项目",
                    "days": 2,
                    "paths": ["/Users/lh/work/funenc/hongkong/dos-station"],
                    "items": [
                        {"request": "修复图表", "response": "已修复图表缩放。", "timestamp": "2026-03-24T01:00:02Z"},
                        {"request": "补打印主题", "response": "已补打印主题。", "timestamp": "2026-03-25T01:00:02Z"},
                    ],
                }
            ],
        }

        rendered = module.render_weekly_source_markdown(source)

        self.assertIn("## 香港DOS系统项目 2d", rendered)


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
