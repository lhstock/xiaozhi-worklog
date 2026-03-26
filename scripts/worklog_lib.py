import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def load_json(path, default):
    file_path = Path(path)
    if not file_path.exists():
        return default
    with file_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, payload):
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)


def resolve_settings(settings, settings_path=None):
    if settings_path is None:
        base_dir = Path.cwd()
    else:
        base_dir = Path(settings_path).resolve().parent
    data_root = Path(settings.get("data_root", "./data"))
    if not data_root.is_absolute():
        data_root = (base_dir / data_root).resolve()
    session_root = Path(settings.get("session_root", "/Users/lh/.codex/sessions"))
    if not session_root.is_absolute():
        session_root = (base_dir / session_root).resolve()
    resolved = dict(settings)
    resolved["data_root"] = str(data_root)
    resolved["session_root"] = str(session_root)
    resolved["timezone"] = settings.get("timezone", "Asia/Shanghai")
    resolved["records_weeks"] = int(settings.get("records_weeks", 2))
    resolved["monitored_roots"] = list(settings.get("monitored_roots", []))
    return resolved


def week_start_for(now, timezone_name):
    tz = ZoneInfo(timezone_name)
    current = now.astimezone(tz)
    start = current - timedelta(days=current.weekday())
    return current.replace(
        year=start.year,
        month=start.month,
        day=start.day,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def week_id_for(now, timezone_name):
    current = now.astimezone(ZoneInfo(timezone_name))
    iso_year, iso_week, _ = current.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def is_monitored_cwd(cwd, monitored_roots):
    try:
        current = Path(cwd).resolve()
    except FileNotFoundError:
        current = Path(cwd)
    for root in monitored_roots:
        try:
            root_path = Path(root).resolve()
        except FileNotFoundError:
            root_path = Path(root)
        if current == root_path or root_path in current.parents:
            return True
    return False


def iter_candidate_session_files(session_root, now, keep_weeks, timezone_name):
    root = Path(session_root)
    if not root.exists():
        return []
    start = week_start_for(now, timezone_name) - timedelta(weeks=max(keep_weeks - 1, 0))
    cursor = start.date()
    end = now.astimezone(ZoneInfo(timezone_name)).date()
    files = []
    while cursor <= end:
        day_dir = root / f"{cursor.year:04d}" / f"{cursor.month:02d}" / f"{cursor.day:02d}"
        if day_dir.exists():
            files.extend(sorted(day_dir.glob("*.jsonl")))
        cursor += timedelta(days=1)
    return files


def flatten_message_text(payload):
    text_parts = []
    for item in payload.get("content", []):
        text = item.get("text")
        if isinstance(text, str):
            text_parts.append(text.strip())
    return "\n".join(part for part in text_parts if part).strip()


def normalize_user_text(text):
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("<environment_context>"):
        return None
    return stripped


def normalize_assistant_text(text):
    stripped = text.strip()
    if not stripped:
        return None
    return stripped


def extract_turn_records(
    lines,
    session_id,
    cwd,
    source_file,
    start_line,
    pending_user,
    timezone_name="Asia/Shanghai",
):
    records = []
    current_pending = pending_user
    for line_no, raw_line in enumerate(lines, start=start_line):
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "response_item":
            continue
        payload = row.get("payload", {})
        if payload.get("type") != "message":
            continue
        role = payload.get("role")
        text = flatten_message_text(payload)
        if role == "user":
            normalized = normalize_user_text(text)
            if normalized:
                current_pending = normalized
            continue
        if role != "assistant" or payload.get("phase") not in {"final", "final_answer"}:
            continue
        normalized = normalize_assistant_text(text)
        if not normalized:
            continue
        timestamp = row.get("timestamp")
        week = week_id_for(
            datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
            timezone_name,
        )
        records.append(
            {
                "record_id": f"{session_id}:{line_no}",
                "session_id": session_id,
                "cwd": cwd,
                "request": current_pending or "",
                "response": normalized,
                "timestamp": timestamp,
                "week": week,
                "source_file": source_file,
                "line_no": line_no,
            }
        )
        current_pending = None
    return records, current_pending


def parse_session_meta(session_path):
    with Path(session_path).open("r", encoding="utf-8") as fh:
        first_line = fh.readline()
    row = json.loads(first_line)
    payload = row.get("payload", {})
    return {
        "session_id": payload.get("id"),
        "cwd": payload.get("cwd"),
    }


def append_records(records_root, records):
    for record in records:
        week_dir = Path(records_root) / record["week"]
        week_dir.mkdir(parents=True, exist_ok=True)
        target = week_dir / "worklog.jsonl"
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def prune_weekly_records(record_root, keep_weeks, now, timezone_name):
    root = Path(record_root)
    if not root.exists():
        return
    keep = set()
    current = week_start_for(now, timezone_name)
    for offset in range(max(keep_weeks, 0)):
        keep.add(week_id_for(current - timedelta(weeks=offset), timezone_name))
    for child in root.iterdir():
        if child.is_dir() and child.name not in keep:
            for nested in child.rglob("*"):
                if nested.is_file():
                    nested.unlink()
            for nested in sorted(child.rglob("*"), reverse=True):
                if nested.is_dir():
                    nested.rmdir()
            child.rmdir()


def load_state(data_root):
    return load_json(Path(data_root) / "state" / "sync-state.json", {"sessions": {}})


def save_state(data_root, state):
    save_json(Path(data_root) / "state" / "sync-state.json", state)


def load_mapping(path):
    data = load_json(path, {"path_map": {}})
    if "path_map" in data and isinstance(data["path_map"], dict):
        return {"path_map": dict(data["path_map"])}

    path_map = {}
    for project in data.get("projects", []):
        name = project.get("name")
        for item in project.get("paths", []):
            if isinstance(item, str) and isinstance(name, str):
                path_map[item] = name
    return {"path_map": path_map}


def save_mapping(path, mapping):
    normalized = {"path_map": dict(mapping.get("path_map", {}))}
    save_json(path, normalized)
    return normalized


def set_mapping(path, pwd, project):
    mapping = load_mapping(path)
    mapping.setdefault("path_map", {})[pwd] = project
    return save_mapping(path, mapping)


def delete_mapping(path, pwd):
    mapping = load_mapping(path)
    mapping.setdefault("path_map", {}).pop(pwd, None)
    return save_mapping(path, mapping)


def sync_sessions(settings, current_cwd, now):
    resolved = resolve_settings(settings)
    if not is_monitored_cwd(current_cwd, resolved["monitored_roots"]):
        return {"status": "skipped", "new_records": 0}

    state = load_state(resolved["data_root"])
    sessions_state = state.setdefault("sessions", {})
    new_records = 0

    for session_path in iter_candidate_session_files(
        resolved["session_root"],
        now,
        resolved["records_weeks"],
        resolved["timezone"],
    ):
        session_path = Path(session_path)
        file_key = str(session_path.resolve())
        file_stat = session_path.stat()
        previous = sessions_state.get(file_key, {})
        if (
            previous.get("mtime_ns") == file_stat.st_mtime_ns
            and previous.get("size") == file_stat.st_size
        ):
            continue
        meta = parse_session_meta(session_path)
        cwd = meta.get("cwd")
        if not cwd or not is_monitored_cwd(cwd, resolved["monitored_roots"]):
            sessions_state[file_key] = {
                "last_line": previous.get("last_line", 0),
                "pending_user": previous.get("pending_user"),
                "mtime_ns": file_stat.st_mtime_ns,
                "size": file_stat.st_size,
            }
            continue

        with session_path.open("r", encoding="utf-8") as fh:
            all_lines = fh.read().splitlines()

        start_line = previous.get("last_line", 1) + 1
        if start_line < 2:
            start_line = 2
        new_lines = all_lines[start_line - 1 :]
        records, pending_user = extract_turn_records(
            lines=new_lines,
            session_id=meta["session_id"],
            cwd=cwd,
            source_file=file_key,
            start_line=start_line,
            pending_user=previous.get("pending_user"),
            timezone_name=resolved["timezone"],
        )
        if records:
            append_records(Path(resolved["data_root"]) / "records", records)
            new_records += len(records)

        sessions_state[file_key] = {
            "last_line": len(all_lines),
            "pending_user": pending_user,
            "mtime_ns": file_stat.st_mtime_ns,
            "size": file_stat.st_size,
            "cwd": cwd,
            "session_id": meta["session_id"],
        }

    save_state(resolved["data_root"], state)
    prune_weekly_records(
        Path(resolved["data_root"]) / "records",
        resolved["records_weeks"],
        now,
        resolved["timezone"],
    )
    return {"status": "ok", "new_records": new_records}


def project_name_for_path(cwd, mapping):
    normalized = load_mapping_from_object(mapping)
    if cwd in normalized["path_map"]:
        return normalized["path_map"][cwd]
    return Path(cwd).name or cwd


def load_mapping_from_object(mapping):
    if "path_map" in mapping and isinstance(mapping["path_map"], dict):
        return {"path_map": dict(mapping["path_map"])}
    return load_mapping_object_legacy(mapping)


def load_mapping_object_legacy(mapping):
    path_map = {}
    for project in mapping.get("projects", []):
        name = project.get("name")
        for item in project.get("paths", []):
            if isinstance(item, str) and isinstance(name, str):
                path_map[item] = name
    return {"path_map": path_map}


def prepare_weekly_source(records_root, week_id, mapping):
    weekly_file = Path(records_root) / week_id / "worklog.jsonl"
    rows = []
    seen = set()
    normalized_mapping = load_mapping_from_object(mapping)
    if weekly_file.exists():
        with weekly_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                record_id = row.get("record_id")
                if record_id in seen:
                    continue
                seen.add(record_id)
                rows.append(row)

    grouped = defaultdict(lambda: {"paths": set(), "items": [], "dates": set()})
    for row in rows:
        name = project_name_for_path(row["cwd"], normalized_mapping)
        grouped[name]["paths"].add(row["cwd"])
        timestamp = row.get("timestamp")
        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            local_date = dt.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            grouped[name]["dates"].add(local_date)
        grouped[name]["items"].append(
            {
                "request": row.get("request", ""),
                "response": row.get("response", ""),
                "timestamp": row.get("timestamp"),
            }
        )

    projects = []
    for name in sorted(grouped):
        projects.append(
            {
                "name": name,
                "days": len(grouped[name]["dates"]),
                "dates": sorted(grouped[name]["dates"]),
                "paths": sorted(grouped[name]["paths"]),
                "items": grouped[name]["items"],
            }
        )
    return {"week": week_id, "projects": projects}


def render_weekly_source_markdown(source):
    lines = [f"# Weekly Source {source['week']}"]
    if not source["projects"]:
        lines.append("")
        lines.append("无可用记录。")
        return "\n".join(lines) + "\n"

    for project in source["projects"]:
        lines.append("")
        lines.append(f"## {project['name']} {project.get('days', 0)}d")
        lines.append(f"路径: {', '.join(project['paths'])}")
        if project.get("dates"):
            lines.append(f"日期: {', '.join(project['dates'])}")
        for item in project["items"]:
            lines.append(f"- 请求: {item['request']}")
            lines.append(f"  结果: {item['response']}")
    return "\n".join(lines) + "\n"


def save_weekly_report(data_root, week_id, content, now):
    report_dir = Path(data_root) / "reports" / week_id
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone().strftime("%Y%m%dT%H%M%S%z")
    target = report_dir / f"xiaozhi-weekly-report-{stamp}.md"
    target.write_text(content, encoding="utf-8")
    return target


def stage_weekly_report(data_root, week_id, content, now):
    draft_dir = Path(data_root) / "state" / "pending-reports"
    draft_dir.mkdir(parents=True, exist_ok=True)
    target = draft_dir / f"{week_id}.md"
    target.write_text(content, encoding="utf-8")
    metadata = {
        "week": week_id,
        "updated_at": now.astimezone().isoformat(),
        "draft_path": str(target),
    }
    save_json(draft_dir / f"{week_id}.json", metadata)
    return target


def archive_staged_report(data_root, week_id, now):
    draft_dir = Path(data_root) / "state" / "pending-reports"
    draft_path = draft_dir / f"{week_id}.md"
    if not draft_path.exists():
        raise FileNotFoundError(f"No staged report for {week_id}")
    content = draft_path.read_text(encoding="utf-8")
    target = save_weekly_report(data_root, week_id, content, now)
    draft_path.unlink()
    metadata_path = draft_dir / f"{week_id}.json"
    if metadata_path.exists():
        metadata_path.unlink()
    return target
