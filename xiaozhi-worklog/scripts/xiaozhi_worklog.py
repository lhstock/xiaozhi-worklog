#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from worklog_lib import (
    archive_staged_report,
    delete_mapping,
    load_mapping,
    load_json,
    prepare_weekly_source,
    render_weekly_source_markdown,
    resolve_settings,
    save_weekly_report,
    set_mapping,
    stage_weekly_report,
    sync_sessions,
    week_id_for,
)


def load_settings_file(path):
    return resolve_settings(load_json(path, {}), settings_path=path)


def cmd_sync(args):
    settings = load_settings_file(args.settings)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now().astimezone()
    result = sync_sessions(settings=settings, current_cwd=args.cwd, now=now)
    print(json.dumps(result, ensure_ascii=False))


def cmd_prepare_report(args):
    settings = load_settings_file(args.settings)
    mapping = load_mapping(args.mapping)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now().astimezone()
    week_id = args.week or week_id_for(now, settings["timezone"])
    source = prepare_weekly_source(
        records_root=Path(settings["data_root"]) / "records",
        week_id=week_id,
        mapping=mapping,
    )
    if args.format == "json":
        print(json.dumps(source, ensure_ascii=False, indent=2))
        return
    print(render_weekly_source_markdown(source))


def cmd_save_report(args):
    settings = load_settings_file(args.settings)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now().astimezone()
    week_id = args.week or week_id_for(now, settings["timezone"])
    content = sys.stdin.read()
    target = save_weekly_report(settings["data_root"], week_id, content, now)
    print(str(target))


def cmd_stage_report(args):
    settings = load_settings_file(args.settings)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now().astimezone()
    week_id = args.week or week_id_for(now, settings["timezone"])
    content = sys.stdin.read()
    target = stage_weekly_report(settings["data_root"], week_id, content, now)
    print(str(target))


def cmd_archive_report(args):
    settings = load_settings_file(args.settings)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now().astimezone()
    week_id = args.week or week_id_for(now, settings["timezone"])
    target = archive_staged_report(settings["data_root"], week_id, now)
    print(str(target))


def cmd_list_mappings(args):
    mapping = load_mapping(args.mapping)
    print(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_set_mapping(args):
    updated = set_mapping(args.mapping, args.pwd, args.project)
    print(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_delete_mapping(args):
    updated = delete_mapping(args.mapping, args.pwd)
    print(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--settings",
        default=str(Path(__file__).resolve().parent.parent / "settings.json"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--cwd", required=True)
    sync_parser.add_argument("--now")
    sync_parser.set_defaults(func=cmd_sync)

    report_parser = subparsers.add_parser("prepare-report")
    report_parser.add_argument(
        "--mapping",
        default=str(Path(__file__).resolve().parent.parent / "report-mapping.json"),
    )
    report_parser.add_argument("--week")
    report_parser.add_argument("--now")
    report_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    report_parser.set_defaults(func=cmd_prepare_report)

    save_parser = subparsers.add_parser("save-report")
    save_parser.add_argument("--week")
    save_parser.add_argument("--now")
    save_parser.set_defaults(func=cmd_save_report)

    stage_parser = subparsers.add_parser("stage-report")
    stage_parser.add_argument("--week")
    stage_parser.add_argument("--now")
    stage_parser.set_defaults(func=cmd_stage_report)

    archive_parser = subparsers.add_parser("archive-report")
    archive_parser.add_argument("--week")
    archive_parser.add_argument("--now")
    archive_parser.set_defaults(func=cmd_archive_report)

    mapping_default = str(Path(__file__).resolve().parent.parent / "report-mapping.json")

    list_mapping_parser = subparsers.add_parser("list-mappings")
    list_mapping_parser.add_argument("--mapping", default=mapping_default)
    list_mapping_parser.set_defaults(func=cmd_list_mappings)

    set_mapping_parser = subparsers.add_parser("set-mapping")
    set_mapping_parser.add_argument("--mapping", default=mapping_default)
    set_mapping_parser.add_argument("--pwd", required=True)
    set_mapping_parser.add_argument("--project", required=True)
    set_mapping_parser.set_defaults(func=cmd_set_mapping)

    delete_mapping_parser = subparsers.add_parser("delete-mapping")
    delete_mapping_parser.add_argument("--mapping", default=mapping_default)
    delete_mapping_parser.add_argument("--pwd", required=True)
    delete_mapping_parser.set_defaults(func=cmd_delete_mapping)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
