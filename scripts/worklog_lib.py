import json
import re
import threading
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
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


def resolve_config_relative_path(raw_path, base_dir):
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    if base_dir.name == "config" and candidate.parts[:1] == (".xiaozhi",):
        return (base_dir.parent.parent / candidate).resolve()
    return (base_dir / candidate).resolve()


def resolve_settings(settings, settings_path=None):
    if settings_path is None:
        base_dir = Path.cwd()
    else:
        base_dir = Path(settings_path).resolve().parent
    default_runtime_root = base_dir.parent / "runtime" if base_dir.name == "config" else base_dir / ".xiaozhi" / "runtime"
    data_root = resolve_config_relative_path(settings.get("data_root", default_runtime_root), base_dir)
    default_identity_path = (
        base_dir / "git-identity.json" if base_dir.name == "config" else base_dir / ".xiaozhi" / "config" / "git-identity.json"
    )
    git_identity_path = resolve_config_relative_path(
        settings.get("git_identity_path", default_identity_path),
        base_dir,
    )
    resolved = dict(settings)
    resolved["data_root"] = str(data_root)
    resolved["git_identity_path"] = str(git_identity_path)
    resolved["timezone"] = settings.get("timezone", "Asia/Shanghai")
    resolved["records_weeks"] = int(settings.get("records_weeks", 2))
    resolved["monitored_roots"] = list(settings.get("monitored_roots", []))
    resolved["session_providers"] = resolve_session_providers(settings, base_dir)
    if resolved["session_providers"]:
        resolved["session_root"] = resolved["session_providers"][0]["root"]
    else:
        resolved["session_root"] = str(
            (base_dir / settings.get("session_root", "/Users/lh/.codex/sessions")).resolve()
        )
    return resolved


def resolve_session_providers(settings, base_dir):
    providers = []
    configured = settings.get("session_providers", [])
    if configured:
        for item in configured:
            root = Path(item["root"]).expanduser()
            if not root.is_absolute():
                root = (base_dir / root).resolve()
            providers.append(
                {
                    "name": item.get("name") or item.get("type"),
                    "type": item["type"],
                    "root": str(root),
                }
            )
        return providers

    legacy_root = settings.get("session_root", "~/.codex/sessions")
    root = Path(legacy_root).expanduser()
    if not root.is_absolute():
        root = (base_dir / root).resolve()
    return [{"name": "codex", "type": "codex", "root": str(root)}]


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


def week_bounds_for_id(week_id, timezone_name):
    year_part, week_part = week_id.split("-W", 1)
    start = datetime.fromisocalendar(int(year_part), int(week_part), 1).replace(
        tzinfo=ZoneInfo(timezone_name),
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    end = start + timedelta(days=7)
    return start, end


def month_week_start(year, month, week_number, timezone_name):
    tz = ZoneInfo(timezone_name)
    cursor = datetime(year, month, 1, tzinfo=tz, hour=0, minute=0, second=0, microsecond=0)
    while cursor.weekday() != 0:
        cursor += timedelta(days=1)
    return cursor + timedelta(weeks=week_number - 1)


def resolve_week_spec(week_spec, now, timezone_name):
    if not week_spec or week_spec == "本周":
        return week_id_for(now, timezone_name)
    if week_spec == "上周":
        return week_id_for(now - timedelta(weeks=1), timezone_name)
    if re.fullmatch(r"\d{4}-W\d{2}", week_spec):
        return week_spec
    match = re.fullmatch(r"(?:(\d{4})-)?(\d{2})-w([1-5])", week_spec, flags=re.IGNORECASE)
    if match:
        year = int(match.group(1) or now.astimezone(ZoneInfo(timezone_name)).year)
        month = int(match.group(2))
        week_number = int(match.group(3))
        start = month_week_start(year, month, week_number, timezone_name)
        return week_id_for(start, timezone_name)
    raise ValueError(f"Unsupported week spec: {week_spec}")


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


def iter_recursive_session_files(root):
    session_root = Path(root)
    if not session_root.exists():
        return []
    files = []
    for pattern in ("*.jsonl", "*.json"):
        files.extend(session_root.rglob(pattern))
    return sorted({path.resolve() for path in files})


def iter_week_session_files(session_root, week_id, timezone_name):
    start, end = week_bounds_for_id(week_id, timezone_name)
    root = Path(session_root)
    files = []
    cursor = start.date()
    while cursor < end.date():
        day_dir = root / f"{cursor.year:04d}" / f"{cursor.month:02d}" / f"{cursor.day:02d}"
        if day_dir.exists():
            files.extend(sorted(day_dir.glob("*.jsonl")))
        cursor += timedelta(days=1)
    return files


def iter_provider_candidate_session_files(provider, now, keep_weeks, timezone_name):
    if provider["type"] == "codex":
        return iter_candidate_session_files(provider["root"], now, keep_weeks, timezone_name)
    if provider["type"] == "claude-code":
        return iter_recursive_session_files(provider["root"])
    raise ValueError(f"Unsupported provider type: {provider['type']}")


def iter_provider_lookup_session_files(provider, week_id, timezone_name):
    if provider["type"] == "codex":
        return iter_week_session_files(provider["root"], week_id, timezone_name)
    if provider["type"] == "claude-code":
        return iter_recursive_session_files(provider["root"])
    raise ValueError(f"Unsupported provider type: {provider['type']}")


def flatten_message_text(payload):
    text_parts = []
    for item in payload.get("content", []):
        text = item.get("text")
        if isinstance(text, str):
            text_parts.append(text.strip())
    return "\n".join(part for part in text_parts if part).strip()


def flatten_content_blocks(content):
    text_parts = []
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    for item in content:
        if isinstance(item, str):
            text_parts.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            text_parts.append(text.strip())
    return "\n".join(part for part in text_parts if part).strip()


def normalize_user_text(text):
    stripped = text.strip()
    if not stripped or stripped.startswith("<environment_context>"):
        return None
    return stripped


def normalize_assistant_text(text):
    stripped = text.strip()
    if not stripped:
        return None
    return stripped


def normalize_summary_text(text):
    return " ".join((text or "").strip().lower().split())


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


def extract_turn_records_for_provider(
    provider_type,
    lines,
    session_id,
    cwd,
    source_file,
    start_line,
    pending_user,
    timezone_name="Asia/Shanghai",
):
    if provider_type == "codex":
        return extract_turn_records(
            lines=lines,
            session_id=session_id,
            cwd=cwd,
            source_file=source_file,
            start_line=start_line,
            pending_user=pending_user,
            timezone_name=timezone_name,
        )
    if provider_type == "claude-code":
        return extract_claude_turn_records(
            lines=lines,
            session_id=session_id,
            cwd=cwd,
            source_file=source_file,
            start_line=start_line,
            pending_user=pending_user,
            timezone_name=timezone_name,
        )
    raise ValueError(f"Unsupported provider type: {provider_type}")


def extract_claude_turn_records(
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
        row_type = row.get("type")
        if row_type == "user":
            normalized = normalize_user_text(
                flatten_content_blocks(row.get("message", {}).get("content"))
            )
            if normalized:
                current_pending = normalized
            continue
        if row_type != "assistant":
            continue
        normalized = normalize_assistant_text(
            flatten_content_blocks(row.get("message", {}).get("content"))
        )
        if not normalized:
            continue
        timestamp = row.get("timestamp")
        if not timestamp:
            continue
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
        "timestamp": row.get("timestamp") or payload.get("timestamp"),
    }


def parse_session_meta_for_provider(provider_type, session_path):
    if provider_type == "codex":
        return parse_session_meta(session_path)
    if provider_type == "claude-code":
        return parse_claude_session_meta(session_path)
    raise ValueError(f"Unsupported provider type: {provider_type}")


def parse_claude_session_meta(session_path):
    with Path(session_path).open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "system" and row.get("subtype") == "init":
                return {
                    "session_id": row.get("session_id"),
                    "cwd": row.get("cwd"),
                    "timestamp": row.get("timestamp"),
                }
    return {"session_id": None, "cwd": None, "timestamp": None}


def load_state(data_root):
    return load_json(Path(data_root) / "state" / "sync-state.json", {"sessions": {}})


def save_state(data_root, state):
    save_json(Path(data_root) / "state" / "sync-state.json", state)


def load_project_index(data_root, week_id):
    return load_json(
        Path(data_root) / "index" / week_id / "projects.json",
        {"week": week_id, "projects": {}},
    )


def save_project_index(data_root, week_id, payload):
    save_json(Path(data_root) / "index" / week_id / "projects.json", payload)


def normalize_index_refs(refs):
    normalized = []
    for ref in refs:
        if isinstance(ref, dict) and "provider" in ref and "session_id" in ref:
            normalized.append({"provider": ref["provider"], "session_id": ref["session_id"]})
        elif isinstance(ref, str):
            normalized.append({"provider": "codex", "session_id": ref})
    return normalized


def normalize_session_state_entry(provider_name, metadata):
    normalized = {
        "provider": provider_name,
        "mtime_ns": metadata.get("mtime_ns"),
        "size": metadata.get("size"),
        "cwd": metadata.get("cwd"),
        "session_id": metadata.get("session_id"),
        "timestamp": metadata.get("timestamp"),
    }
    timestamp = normalized.get("timestamp")
    if timestamp:
        try:
            normalized["week_id"] = week_id_for(
                datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
                "Asia/Shanghai",
            )
        except ValueError:
            normalized["week_id"] = None
    else:
        normalized["week_id"] = None
    return normalized


def rebuild_weekly_indexes(data_root, sessions_state, keep_weeks, now, timezone_name):
    root = Path(data_root) / "index"
    root.mkdir(parents=True, exist_ok=True)
    keep_weeks_ids = []
    current = week_start_for(now, timezone_name)
    for offset in range(max(keep_weeks, 0)):
        keep_weeks_ids.append(week_id_for(current - timedelta(weeks=offset), timezone_name))

    project_refs_by_week = {week_id: defaultdict(list) for week_id in keep_weeks_ids}
    for metadata in sessions_state.values():
        timestamp = metadata.get("timestamp")
        cwd = metadata.get("cwd")
        session_id = metadata.get("session_id")
        provider = metadata.get("provider")
        if not (timestamp and cwd and session_id and provider):
            continue
        try:
            week_id = week_id_for(
                datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
                timezone_name,
            )
        except ValueError:
            continue
        if week_id not in project_refs_by_week:
            continue
        ref = {"provider": provider, "session_id": session_id}
        refs = project_refs_by_week[week_id][cwd]
        if ref not in refs:
            refs.append(ref)

    for week_id in keep_weeks_ids:
        payload = {"week": week_id, "projects": {}}
        for cwd, refs in sorted(project_refs_by_week[week_id].items()):
            payload["projects"][cwd] = sorted(
                refs, key=lambda item: (item["provider"], item["session_id"])
            )
        save_project_index(data_root, week_id, payload)


def prune_weekly_index(data_root, keep_weeks, now, timezone_name):
    root = Path(data_root) / "index"
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


def load_mapping(path):
    data = load_json(path, {"path_map": {}, "personal_paths": []})
    if "path_map" in data and isinstance(data["path_map"], dict):
        return {
            "path_map": dict(data["path_map"]),
            "personal_paths": sorted(
                {item for item in data.get("personal_paths", []) if isinstance(item, str) and item}
            ),
        }

    path_map = {}
    for project in data.get("projects", []):
        name = project.get("name")
        for item in project.get("paths", []):
            if isinstance(item, str) and isinstance(name, str):
                path_map[item] = name
    return {"path_map": path_map, "personal_paths": []}


def save_mapping(path, mapping):
    normalized = {
        "path_map": dict(mapping.get("path_map", {})),
        "personal_paths": sorted(
            {item for item in mapping.get("personal_paths", []) if isinstance(item, str) and item}
        ),
    }
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


def set_personal_path(path, pwd):
    mapping = load_mapping(path)
    personal_paths = set(mapping.get("personal_paths", []))
    personal_paths.add(pwd)
    mapping["personal_paths"] = sorted(personal_paths)
    mapping.setdefault("path_map", {}).pop(pwd, None)
    return save_mapping(path, mapping)


def delete_personal_path(path, pwd):
    mapping = load_mapping(path)
    personal_paths = set(mapping.get("personal_paths", []))
    personal_paths.discard(pwd)
    mapping["personal_paths"] = sorted(personal_paths)
    return save_mapping(path, mapping)


def load_git_identity_map(path):
    if not path:
        return {"emails": [], "names": []}
    data = load_json(path, {"emails": [], "names": []})
    return {
        "emails": sorted({item for item in data.get("emails", []) if isinstance(item, str) and item}),
        "names": sorted({item for item in data.get("names", []) if isinstance(item, str) and item}),
    }


def save_git_identity_map(path, identity):
    normalized = {
        "emails": sorted({item for item in identity.get("emails", []) if item}),
        "names": sorted({item for item in identity.get("names", []) if item}),
    }
    save_json(path, normalized)
    return normalized


def set_git_identity(path, emails=None, names=None):
    return save_git_identity_map(
        path,
        {
            "emails": list(emails or []),
            "names": list(names or []),
        },
    )


def add_git_identity_alias(path, emails=None, names=None):
    current = load_git_identity_map(path)
    return save_git_identity_map(
        path,
        {
            "emails": current["emails"] + list(emails or []),
            "names": current["names"] + list(names or []),
        },
    )


def remove_git_identity_alias(path, emails=None, names=None):
    current = load_git_identity_map(path)
    remove_emails = set(emails or [])
    remove_names = set(names or [])
    return save_git_identity_map(
        path,
        {
            "emails": [item for item in current["emails"] if item not in remove_emails],
            "names": [item for item in current["names"] if item not in remove_names],
        },
    )


def sync_sessions(settings, current_cwd, now):
    del current_cwd
    resolved = resolve_settings(settings)
    state = load_state(resolved["data_root"])
    sessions_state = state.setdefault("sessions", {})
    touched = set()
    active_file_keys = set()
    active_provider_names = {provider["name"] for provider in resolved["session_providers"]}

    for provider in resolved["session_providers"]:
        for session_path in iter_provider_candidate_session_files(
            provider,
            now,
            resolved["records_weeks"],
            resolved["timezone"],
        ):
            session_path = Path(session_path)
            file_key = f"{provider['name']}::{session_path.resolve()}"
            active_file_keys.add(file_key)
            file_stat = session_path.stat()
            previous = sessions_state.get(file_key, {})
            if (
                previous.get("mtime_ns") == file_stat.st_mtime_ns
                and previous.get("size") == file_stat.st_size
            ):
                continue

            meta = parse_session_meta_for_provider(provider["type"], session_path)
            session_id = meta.get("session_id")
            cwd = meta.get("cwd")
            timestamp = meta.get("timestamp")
            if session_id and cwd and timestamp:
                week_id = week_id_for(
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
                    resolved["timezone"],
                )
                touched.add((week_id, cwd, provider["name"], session_id))

            sessions_state[file_key] = {
                "provider": provider["name"],
                "mtime_ns": file_stat.st_mtime_ns,
                "size": file_stat.st_size,
                "cwd": cwd,
                "session_id": session_id,
                "timestamp": timestamp,
            }

    for file_key in list(sessions_state):
        provider_name, _, _ = file_key.partition("::")
        if provider_name in active_provider_names and file_key not in active_file_keys:
            sessions_state.pop(file_key, None)

    rebuild_weekly_indexes(
        resolved["data_root"],
        sessions_state,
        resolved["records_weeks"],
        now,
        resolved["timezone"],
    )
    save_state(resolved["data_root"], state)
    prune_weekly_index(
        resolved["data_root"],
        resolved["records_weeks"],
        now,
        resolved["timezone"],
    )
    return {"status": "ok", "projects_touched": len(touched)}


def run_git(repo_path, args):
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def detect_git_identity(repo_path, settings):
    configured = settings.get("git_identity", {})
    file_identity = load_git_identity_map(settings.get("git_identity_path", ""))
    defaults = discover_git_identity_defaults(repo_path)
    emails = (
        list(file_identity.get("emails", []))
        + list(configured.get("emails", []))
        + list(defaults.get("emails", []))
    )
    names = (
        list(file_identity.get("names", []))
        + list(configured.get("names", []))
        + list(defaults.get("names", []))
    )

    return {
        "emails": sorted({item for item in emails if item}),
        "names": sorted({item for item in names if item}),
    }


def run_git_config(scope_args, key, cwd=None):
    try:
        completed = subprocess.run(
            ["git", "config", *scope_args, "--get", key],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def discover_git_identity_defaults(repo_path=None):
    local_email = run_git_config([], "user.email", cwd=repo_path)
    local_name = run_git_config([], "user.name", cwd=repo_path)
    global_email = run_git_config(["--global"], "user.email")
    global_name = run_git_config(["--global"], "user.name")
    emails = sorted({item for item in (local_email, global_email) if item})
    names = sorted({item for item in (local_name, global_name) if item})
    return {"emails": emails, "names": names}


def is_personal_commit(commit, identity):
    author_email = commit.get("author_email", "")
    author_name = commit.get("author_name", "")
    if identity["emails"] and author_email in identity["emails"]:
        return True
    if not identity["emails"] and identity["names"] and author_name in identity["names"]:
        return True
    return False


def collect_git_commits(repo_path, week_id, timezone_name, settings):
    start, end = week_bounds_for_id(week_id, timezone_name)
    identity = detect_git_identity(repo_path, settings)
    output = run_git(
        repo_path,
        [
            "log",
            "--since",
            start.isoformat(),
            "--until",
            end.isoformat(),
            "--pretty=format:%H%x1f%s%x1f%cI%x1f%an%x1f%ae",
        ],
    )
    commits = []
    if not output:
        return commits
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        commit = {
            "hash": parts[0],
            "subject": parts[1],
            "timestamp": parts[2],
            "author_name": parts[3],
            "author_email": parts[4],
            "path": str(repo_path),
        }
        if not is_personal_commit(commit, identity):
            continue
        commits.append(commit)
    return commits


def collect_working_tree(repo_path):
    output = run_git(repo_path, ["status", "--porcelain"])
    modified = []
    untracked = []
    if not output:
        return {"modified": modified, "untracked": untracked}
    for line in output.splitlines():
        if len(line) < 4:
            continue
        status = line[:2]
        path = line[3:]
        if status == "??":
            untracked.append(path)
        else:
            modified.append(path)
    return {
        "modified": sorted(dict.fromkeys(modified)),
        "untracked": sorted(dict.fromkeys(untracked)),
    }


def extract_session_items_for_refs(providers, week_id, timezone_name, session_refs):
    refs = normalize_index_refs(session_refs)
    if not refs:
        return []
    provider_map = {provider["name"]: provider for provider in providers}
    refs_by_provider = defaultdict(set)
    for ref in refs:
        refs_by_provider[ref["provider"]].add(ref["session_id"])
    items = []
    seen = set()
    for provider_name, target_ids in refs_by_provider.items():
        provider = provider_map.get(provider_name)
        if not provider:
            continue
        for session_path in iter_provider_lookup_session_files(provider, week_id, timezone_name):
            meta = parse_session_meta_for_provider(provider["type"], session_path)
            if meta.get("session_id") not in target_ids:
                continue
            with Path(session_path).open("r", encoding="utf-8") as fh:
                all_lines = fh.read().splitlines()[1:]
            records, _ = extract_turn_records_for_provider(
                provider_type=provider["type"],
                lines=all_lines,
                session_id=meta["session_id"],
                cwd=meta.get("cwd"),
                source_file=str(Path(session_path).resolve()),
                start_line=2,
                pending_user=None,
                timezone_name=timezone_name,
            )
            for record in records:
                if record["week"] != week_id:
                    continue
                dedupe_key = (
                    provider_name,
                    normalize_summary_text(record.get("request", "")),
                    normalize_summary_text(record.get("response", "")),
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                items.append(
                    {
                        "provider": provider_name,
                        "session_id": record["session_id"],
                        "request": record.get("request", ""),
                        "response": record.get("response", ""),
                        "timestamp": record.get("timestamp"),
                    }
                )
    return items


def collect_weekly_project_index_from_sessions(settings, week_id):
    resolved = resolve_settings(settings)
    projects = defaultdict(list)
    for provider in resolved["session_providers"]:
        for session_path in iter_provider_lookup_session_files(
            provider, week_id, resolved["timezone"]
        ):
            meta = parse_session_meta_for_provider(provider["type"], session_path)
            timestamp = meta.get("timestamp")
            cwd = meta.get("cwd")
            session_id = meta.get("session_id")
            if not (timestamp and cwd and session_id):
                continue
            try:
                record_week = week_id_for(
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
                    resolved["timezone"],
                )
            except ValueError:
                continue
            if record_week != week_id:
                continue
            ref = {"provider": provider["name"], "session_id": session_id}
            if ref not in projects[cwd]:
                projects[cwd].append(ref)
    payload = {"week": week_id, "projects": {}}
    for cwd in sorted(projects):
        payload["projects"][cwd] = sorted(
            projects[cwd], key=lambda item: (item["provider"], item["session_id"])
        )
    return payload


def load_mapping_from_object(mapping):
    if "path_map" in mapping and isinstance(mapping["path_map"], dict):
        return {
            "path_map": dict(mapping["path_map"]),
            "personal_paths": sorted(
                {item for item in mapping.get("personal_paths", []) if isinstance(item, str) and item}
            ),
        }
    return load_mapping_object_legacy(mapping)


def load_mapping_object_legacy(mapping):
    path_map = {}
    for project in mapping.get("projects", []):
        name = project.get("name")
        for item in project.get("paths", []):
            if isinstance(item, str) and isinstance(name, str):
                path_map[item] = name
    return {"path_map": path_map, "personal_paths": []}


def merge_project_rows(project_rows):
    commit_seen = set()
    session_seen = set()
    merged_commits = []
    merged_sessions = []
    merged_paths = []
    modified = []
    untracked = []

    for row in project_rows:
        merged_paths.extend(row["paths"])
        for commit in row["git"]["commits"]:
            if commit["hash"] in commit_seen:
                continue
            commit_seen.add(commit["hash"])
            merged_commits.append(commit)
        for item in row["sessions"]:
            key = (
                normalize_summary_text(item.get("request", "")),
                normalize_summary_text(item.get("response", "")),
            )
            if key in session_seen:
                continue
            session_seen.add(key)
            merged_sessions.append(item)
        modified.extend(row["git"]["working_tree"]["modified"])
        untracked.extend(row["git"]["working_tree"]["untracked"])

    return {
        "paths": sorted(dict.fromkeys(merged_paths)),
        "git": {
            "commits": merged_commits,
            "working_tree": {
                "modified": sorted(dict.fromkeys(modified)),
                "untracked": sorted(dict.fromkeys(untracked)),
            },
        },
        "sessions": merged_sessions,
    }


def prepare_weekly_source(week_id, mapping, settings):
    resolved = resolve_settings(settings)
    normalized_mapping = load_mapping_from_object(mapping)
    weekly_index = load_project_index(resolved["data_root"], week_id)
    if not weekly_index.get("projects"):
        weekly_index = collect_weekly_project_index_from_sessions(resolved, week_id)
        save_project_index(resolved["data_root"], week_id, weekly_index)
    personal_paths = set(normalized_mapping.get("personal_paths", []))
    unknown_paths = []

    by_project = defaultdict(list)
    touched_paths = weekly_index.get("projects", {})
    for cwd in sorted(touched_paths):
        if cwd in personal_paths:
            continue
        project_name = normalized_mapping["path_map"].get(cwd)
        if not project_name:
            unknown_paths.append(cwd)
            continue
        repo_path = Path(cwd)
        git_payload = {
            "commits": collect_git_commits(repo_path, week_id, resolved["timezone"], resolved),
            "working_tree": collect_working_tree(repo_path),
        }
        session_items = extract_session_items_for_refs(
            resolved["session_providers"],
            week_id,
            resolved["timezone"],
            touched_paths.get(cwd, []),
        )
        by_project[project_name].append(
            {
                "paths": [cwd],
                "git": git_payload,
                "sessions": session_items,
            }
        )

    projects = []
    for project_name in sorted(by_project):
        merged = merge_project_rows(by_project[project_name])
        projects.append(
            {
                "name": project_name,
                "paths": merged["paths"],
                "git": merged["git"],
                "sessions": merged["sessions"],
            }
        )
    return {"week": week_id, "projects": projects, "unknown_paths": unknown_paths}


def render_weekly_source_markdown(source):
    lines = [f"# Weekly Source {source['week']}"]
    if not source["projects"]:
        lines.extend(["", "无可用记录。"])
        return "\n".join(lines) + "\n"

    for project in source["projects"]:
        lines.extend(["", f"## {project['name']}", f"Paths: {', '.join(project['paths'])}"])
        lines.append("Git commits:")
        if project["git"]["commits"]:
            for commit in project["git"]["commits"]:
                lines.append(f"- {commit['subject']} ({commit['hash'][:7]})")
        else:
            lines.append("- 无")
        lines.append("Working tree:")
        lines.append(
            f"- modified: {', '.join(project['git']['working_tree']['modified']) or '无'}"
        )
        lines.append(
            f"- untracked: {', '.join(project['git']['working_tree']['untracked']) or '无'}"
        )
        lines.append("Session context:")
        if project["sessions"]:
            for item in project["sessions"]:
                lines.append(f"- 请求: {item['request']}")
                lines.append(f"  结果: {item['response']}")
        else:
            lines.append("- 无")
    return "\n".join(lines) + "\n"


def estimate_project_effort(project):
    work_units = (
        len(project["git"]["commits"])
        + len(project["sessions"])
        + len(project["git"]["working_tree"]["modified"])
        + len(project["git"]["working_tree"]["untracked"])
    )
    if work_units <= 0:
        return "0.0"
    return f"{max(0.1, round(work_units / 8, 1)):.1f}"


def strip_commit_prefix(subject):
    stripped = (subject or "").strip()
    for prefix in ("feat:", "fix:", "refactor:", "docs:", "chore:", "style:", "test:"):
        if stripped.lower().startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped


def summarize_path_label(path):
    name = Path(path).name
    stem = Path(path).stem
    return stem or name or path


def localize_phrase(text):
    localized = text
    replacements = (
        ("maintenance plan", "维保计划"),
        ("cycle column", "周期列"),
        ("view2 design spec", "view2 设计说明"),
        ("design spec", "设计说明"),
        ("DataTable", "表格"),
        ("mock data", "mock 数据"),
        ("mock", "mock"),
        ("test", "测试"),
        ("tests", "测试"),
        ("print template", "打印模板"),
        ("preview", "预览"),
        ("filter", "筛选"),
    )
    for old, new in replacements:
        localized = localized.replace(old, new).replace(old.title(), new)
    return localized


def infer_topic_key(text):
    lowered = text.lower()
    if "maintenance" in lowered or "周期" in text or "mock" in lowered:
        return "维保计划周期配置"
    if "print" in lowered or "打印" in text:
        return "打印与输出"
    if "filter" in lowered or "筛选" in text:
        return "筛选与列表交互"
    if "design spec" in lowered or "设计说明" in text or "调研" in text:
        return "方案与说明"
    if "test" in lowered or "测试" in text or "验证" in text:
        return "验证与质量"
    return localize_phrase(text)


def collect_project_topics(project):
    topics = []
    seen = set()

    for commit in project["git"]["commits"]:
        text = localize_phrase(strip_commit_prefix(commit["subject"]))
        normalized = normalize_summary_text(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        topics.append({"text": text, "source": "git"})

    for session in project["sessions"]:
        text = localize_phrase(session["response"] or session["request"])
        normalized = normalize_summary_text(text)
        overlap = False
        for item in topics:
            topic_text = normalize_summary_text(item["text"])
            if not topic_text:
                continue
            if topic_text in normalized or normalized in topic_text:
                overlap = True
                break
        if not normalized or overlap or normalized in seen:
            continue
        seen.add(normalized)
        topics.append({"text": text, "source": "session"})

    if project["git"]["working_tree"]["modified"]:
        text = "完善配套改动与联调验证"
        normalized = normalize_summary_text(text)
        if normalized not in seen:
            seen.add(normalized)
            topics.append({"text": text, "source": "working_tree"})

    if project["git"]["working_tree"]["untracked"]:
        text = "补充交付说明与相关材料"
        normalized = normalize_summary_text(text)
        if normalized not in seen:
            seen.add(normalized)
            topics.append({"text": text, "source": "working_tree"})

    return topics


def summarize_topic_text(text):
    stripped = (text or "").strip().rstrip("。")
    replacements = (
        ("已完成", ""),
        ("已补充", ""),
        ("已整理", ""),
        ("已修复", ""),
        ("已优化", ""),
        ("已", ""),
    )
    for old, new in replacements:
        if stripped.startswith(old):
            stripped = stripped.replace(old, new, 1).strip()
            break
    stripped = strip_commit_prefix(stripped)
    if not stripped:
        return "补充本周工作内容"
    if stripped.startswith("完成"):
        stripped = stripped[2:].strip()
    return localize_phrase(stripped)


def normalize_management_module(text):
    stripped = summarize_topic_text(text)
    stripped = re.sub(r"\b[a-z0-9_-]+\.(js|jsx|ts|tsx|md|json|py|java|vue)\b", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\b[a-z0-9_/-]{3,}\b", "", stripped, flags=re.IGNORECASE)
    for prefix in ("完成", "优化", "推进", "完善", "修复", "补充", "整理", "支持", "支撑"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].strip()
    stripped = re.sub(r"\s+", " ", stripped).strip(" ，、。")
    return stripped or "重点事项"


def group_topics(topics):
    grouped = []
    for topic in topics:
        summary = summarize_topic_text(topic["text"])
        group_key = infer_topic_key(summary)
        placed = False
        for group in grouped:
            existing = group["key"]
            if existing == group_key:
                if topic["source"] == "git":
                    group["summary"] = summary
                group["items"].append(topic)
                placed = True
                break
        if not placed:
            grouped.append({"key": group_key, "summary": summary, "items": [topic]})
    return grouped


def compress_topic_groups(groups, max_groups=7):
    if len(groups) <= max_groups:
        return groups
    head = groups[: max_groups - 1]
    tail_items = []
    for group in groups[max_groups - 1 :]:
        tail_items.extend(group["items"])
    head.append({"key": "配套支撑", "summary": "配套支撑", "items": tail_items})
    return head


def choose_group_action(group, guidance=""):
    combined = " ".join(summarize_topic_text(item["text"]) for item in group["items"])
    guidance_text = (guidance or "").strip()
    if group["key"] == "方案与说明":
        return "推进" if ("进度" in guidance_text or "推进" in guidance_text) else "完善"
    if group["key"] == "验证与质量":
        return "完善"
    if any(word in combined for word in ("优化", "修复", "筛选", "体验", "调整")):
        return "优化"
    if any(word in combined for word in ("方案", "说明", "调研", "预案", "规划")):
        return "推进"
    if any(word in combined for word in ("验证", "测试", "联调", "质量")):
        return "完善"
    return "完成"


def render_topic_bullet(group, guidance=""):
    texts = [summarize_topic_text(item["text"]) for item in group["items"]]
    combined = "、".join(dict.fromkeys(texts))
    key = group["key"]
    guidance_text = (guidance or "").strip()
    wants_testing = "测试" in guidance_text or "验证" in guidance_text
    wants_progress = "进度" in guidance_text or "推进" in guidance_text
    if key == "维保计划周期配置":
        suffix = "并完成相关测试验证" if wants_testing or "测试" in combined else "并补齐相关业务支撑"
        return f"完善维保计划周期配置，补齐 mock 数据分布{suffix}。"
    if key == "打印与输出":
        detail = "打印模板" if "打印模板" in combined else "打印与输出"
        return f"完善{detail}相关能力，补充配套说明并支撑业务使用。"
    if key == "筛选与列表交互":
        detail = "列车看板筛选" if "列车看板筛选" in combined else "筛选与列表交互"
        return f"完成{detail}相关优化，提升页面使用体验。"
    if key == "方案与说明":
        action = "推进" if wants_progress else "完善"
        return f"{action}方案与说明材料，为后续功能推进提供支持。"
    if key == "验证与质量":
        return f"完善相关验证工作，保障改动质量与可用性。"
    if key == "配套支撑":
        return "完善配套支撑事项，保障阶段交付顺畅推进。"
    module = normalize_management_module(group.get("summary") or key)
    action = choose_group_action(group, guidance=guidance)
    if action == "优化":
        return f"优化{module}相关能力，提升场景支撑与使用体验。"
    if action == "推进":
        return f"推进{module}相关事项，补齐方案与协同支撑。"
    if action == "完善":
        return f"完善{module}相关工作，保障阶段成果稳定落地。"
    return f"完成{module}相关工作，补齐配套支撑并推动阶段成果落地。"


def render_weekly_report_draft(source, guidance=""):
    lines = ["本周工作内容"]
    if not source["projects"]:
        unknown_paths = source.get("unknown_paths", [])
        if unknown_paths:
            lines.extend(
                [
                    "",
                    "发现待配置路径，请先补充项目映射或标记为个人目录：",
                    format_unknown_paths_hint(unknown_paths),
                    "",
                    "配置完成后再重新生成周报。",
                ]
            )
            return "\n".join(lines) + "\n"
        return "本周工作内容\n\n暂无可汇总内容。\n"

    for project in source["projects"]:
        lines.append("")
        lines.append(f"{project['name']} {estimate_project_effort(project)}d")
        groups = compress_topic_groups(group_topics(collect_project_topics(project)))
        if not groups:
            groups = [{"key": "本周工作内容", "summary": "本周工作内容", "items": []}]
        for index, group in enumerate(groups, start=1):
            lines.append(f"{index}. {render_topic_bullet(group, guidance=guidance)}")
    return "\n".join(lines) + "\n"


def load_staged_report(data_root, week_id):
    draft_path = Path(data_root) / "state" / "pending-reports" / f"{week_id}.md"
    if not draft_path.exists():
        return None
    return draft_path.read_text(encoding="utf-8")


def summarize_index_status(data_root, week_id, mapping):
    normalized_mapping = load_mapping_from_object(mapping)
    personal_paths = set(normalized_mapping.get("personal_paths", []))
    index = load_project_index(data_root, week_id)
    projects = []
    for cwd in sorted(index.get("projects", {})):
        refs = normalize_index_refs(index["projects"][cwd])
        if cwd in personal_paths:
            category = "personal"
            project_name = "个人目录"
        elif cwd in normalized_mapping["path_map"]:
            category = "project"
            project_name = normalized_mapping["path_map"][cwd]
        else:
            category = "unknown"
            project_name = Path(cwd).name or cwd
        projects.append(
            {
                "cwd": cwd,
                "project_name": project_name,
                "category": category,
                "session_count": len(refs),
                "providers": sorted({ref["provider"] for ref in refs}),
            }
        )
    return {"week": week_id, "projects": projects}


def build_skill_info(settings):
    providers = [
        {
            "name": provider["name"],
            "type": provider["type"],
            "root": provider["root"],
        }
        for provider in settings["session_providers"]
    ]
    return {
        "name": "小志",
        "description": "统一的项目会话与周报工作台入口",
        "providers": providers,
        "data_root": settings["data_root"],
    }


def summarize_source_for_workbench(source):
    projects = []
    for project in source["projects"]:
        projects.append(
            {
                "name": project["name"],
                "paths": project["paths"],
                "git_commit_count": len(project["git"]["commits"]),
                "working_tree": project["git"]["working_tree"],
                "session_count": len(project["sessions"]),
            }
        )
    return {"week": source["week"], "projects": projects}


def build_workbench_payload(settings, mapping, week_id, draft=None, regenerate_note=""):
    resolved = resolve_settings(settings)
    existing_index = load_project_index(resolved["data_root"], week_id)
    if not existing_index.get("projects"):
        _, week_end = week_bounds_for_id(week_id, resolved["timezone"])
        sync_sessions(
            settings=resolved,
            current_cwd=str(Path.cwd()),
            now=week_end - timedelta(seconds=1),
        )
    source = prepare_weekly_source(week_id=week_id, mapping=mapping, settings=resolved)
    staged = load_staged_report(resolved["data_root"], week_id)
    content = draft if draft is not None else (staged or render_weekly_report_draft(source))
    return {
        "week": week_id,
        "draft": content,
        "regenerate_note": regenerate_note,
        "skill": build_skill_info(resolved),
        "index_status": summarize_index_status(resolved["data_root"], week_id, mapping),
        "source": summarize_source_for_workbench(source),
        "mapping": load_mapping_from_object(mapping),
        "git_identity": detect_git_identity(Path.cwd(), resolved),
        "unknown_paths": source.get("unknown_paths", []),
        "unknown_paths_hint": format_unknown_paths_hint(source.get("unknown_paths", [])),
    }


def format_unknown_paths_hint(unknown_paths):
    return "\n".join(f'{path} - ""' for path in unknown_paths)


def render_workbench_html(payload):
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>小志工作台</title>
  <style>
    :root {{ --bg:#f5f1e8; --panel:#fffaf0; --ink:#1f2a1f; --accent:#1d6b57; --line:#d8cfbf; --muted:#6f7569; }}
    body {{ margin:0; font-family: "SF Mono","JetBrains Mono",monospace; color:var(--ink); background:linear-gradient(135deg,#f5f1e8,#efe7d5); }}
    main {{ padding:20px; }}
    section {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:16px; box-shadow:0 12px 30px rgba(0,0,0,.05); }}
    textarea {{ width:100%; min-height:70vh; border:1px solid var(--line); border-radius:12px; padding:12px; font:inherit; background:#fffdf7; box-sizing:border-box; }}
    .compact {{ min-height:240px; }}
    input {{ width:100%; border:1px solid var(--line); border-radius:12px; padding:12px; font:inherit; background:#fffdf7; box-sizing:border-box; }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0 0; }}
    button {{ border:0; border-radius:999px; padding:10px 14px; font:inherit; background:var(--accent); color:#fff; cursor:pointer; }}
    button.secondary {{ background:#d9d0bf; color:var(--ink); }}
    .meta {{ font-size:12px; opacity:.8; margin-bottom:8px; }}
    .helper {{ color:var(--muted); font-size:12px; margin-top:8px; white-space:pre-wrap; }}
    .status {{ min-height:20px; font-size:12px; color:var(--muted); white-space:pre-wrap; }}
    .status.error {{ color:#b42318; }}
    .stack {{ display:flex; flex-direction:column; gap:16px; }}
    .hidden {{ display:none; }}
    .label {{ font-size:12px; margin:0 0 8px; color:var(--muted); }}
    h1 {{ margin:0 0 10px; }}
    button[disabled] {{ opacity:.6; cursor:wait; }}
  </style>
</head>
<body>
  <main>
    <section>
      <h1>小志工作台</h1>
      <div class="meta" id="meta"></div>
      <div class="actions">
        <button id="reportViewBtn" class="secondary">周报</button>
        <button id="adminViewBtn" class="secondary">后台管理</button>
      </div>
      <div id="reportView" class="stack">
        <div>
          <div class="label">重新生成补充说明</div>
          <input id="regenNote" placeholder="例如：突出测试结果、压缩调研表述、偏管理视角" />
          <div class="helper">这段说明会在重新生成时作为补充提示一起提交。</div>
        </div>
        <div id="status" class="status"></div>
        <textarea id="draft"></textarea>
        <div class="actions">
          <button id="saveBtn" class="secondary">保存草稿</button>
          <button id="regenBtn" class="secondary">重新生成</button>
          <button id="copyBtn">复制</button>
          <button id="archiveBtn">确认归档</button>
        </div>
      </div>
      <div id="adminView" class="stack hidden">
        <div>
          <div class="label">项目映射 JSON</div>
          <div class="helper" id="unknownPaths"></div>
          <textarea id="mappingEditor" class="compact"></textarea>
          <div class="actions">
            <button id="saveMappingBtn" class="secondary">保存项目映射</button>
          </div>
        </div>
        <div>
          <div class="label">Git 用户 JSON</div>
          <textarea id="identityEditor" class="compact"></textarea>
          <div class="actions">
            <button id="saveIdentityBtn" class="secondary">保存 Git 用户</button>
          </div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const initial = JSON.parse({json.dumps(json.dumps(payload, ensure_ascii=False))});
    const draftEl = document.getElementById('draft');
    const metaEl = document.getElementById('meta');
    const regenNoteEl = document.getElementById('regenNote');
    const mappingEditorEl = document.getElementById('mappingEditor');
    const identityEditorEl = document.getElementById('identityEditor');
    const unknownPathsEl = document.getElementById('unknownPaths');
    const reportViewEl = document.getElementById('reportView');
    const adminViewEl = document.getElementById('adminView');
    const statusEl = document.getElementById('status');
    const actionButtons = [
      document.getElementById('saveBtn'),
      document.getElementById('regenBtn'),
      document.getElementById('copyBtn'),
      document.getElementById('archiveBtn'),
      document.getElementById('saveMappingBtn'),
      document.getElementById('saveIdentityBtn'),
    ];

    function render(state) {{
      draftEl.value = state.draft || '';
      regenNoteEl.value = state.regenerate_note || '';
      mappingEditorEl.value = JSON.stringify(state.mapping || {{ path_map: {{}} }}, null, 2);
      identityEditorEl.value = JSON.stringify(state.git_identity || {{ emails: [], names: [] }}, null, 2);
      metaEl.textContent = `周次: ${{state.week}}`;
      const unknownHint = state.unknown_paths_hint || '';
      unknownPathsEl.textContent = unknownHint
        ? `待配置路径:\n${{unknownHint}}`
        : '当前没有待配置的新路径。';
    }}

    function showView(view) {{
      reportViewEl.classList.toggle('hidden', view !== 'report');
      adminViewEl.classList.toggle('hidden', view !== 'admin');
    }}

    function setStatus(message, isError = false) {{
      statusEl.textContent = message || '';
      statusEl.classList.toggle('error', Boolean(isError));
    }}

    function setBusy(isBusy, message = '请求进行中...') {{
      for (const button of actionButtons) {{
        button.disabled = Boolean(isBusy);
      }}
      if (isBusy) {{
        setStatus(message, false);
      }} else if (statusEl.textContent === message) {{
        setStatus('', false);
      }}
    }}

    async function postJson(url, payload) {{
      try {{
        setBusy(true);
        const response = await fetch(url, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload || {{}})
        }});
        let body = null;
        try {{
          body = await response.json();
        }} catch (_error) {{
          body = null;
        }}
        if (!response.ok) {{
          const message = body && body.error ? body.error : `请求失败（${{response.status}}）`;
          setStatus(message, true);
          throw new Error(message);
        }}
        setStatus('');
        return body;
      }} catch (error) {{
        const message = error && error.message ? error.message : '请求失败';
        setStatus(message, true);
        throw error;
      }} finally {{
        setBusy(false);
      }}
    }}

    document.getElementById('saveBtn').onclick = async () => {{
      try {{
        const state = await postJson('/api/draft', {{ draft: draftEl.value }});
        render(state);
      }} catch (_error) {{}}
    }};

    document.getElementById('regenBtn').onclick = async () => {{
      try {{
        const state = await postJson('/api/regenerate', {{ note: regenNoteEl.value }});
        render(state);
      }} catch (_error) {{}}
    }};

    document.getElementById('copyBtn').onclick = async () => {{
      await navigator.clipboard.writeText(draftEl.value);
    }};

    document.getElementById('archiveBtn').onclick = async () => {{
      try {{
        const state = await postJson('/api/archive', {{ draft: draftEl.value }});
        render(state);
      }} catch (_error) {{}}
    }};

    document.getElementById('saveMappingBtn').onclick = async () => {{
      try {{
        const state = await postJson('/api/mapping', {{ mapping: JSON.parse(mappingEditorEl.value || '{{}}') }});
        render(state);
      }} catch (error) {{
        setStatus(error.message || '保存项目映射失败', true);
      }}
    }};

    document.getElementById('saveIdentityBtn').onclick = async () => {{
      try {{
        const state = await postJson('/api/git-identity', {{ git_identity: JSON.parse(identityEditorEl.value || '{{}}') }});
        render(state);
      }} catch (error) {{
        setStatus(error.message || '保存 Git 用户失败', true);
      }}
    }};

    document.getElementById('reportViewBtn').onclick = () => showView('report');
    document.getElementById('adminViewBtn').onclick = () => showView('admin');

    const stream = new EventSource('/events');
    stream.onmessage = (event) => render(JSON.parse(event.data));
    render(initial);
    showView('report');
  </script>
</body>
</html>
"""


class WorkbenchState:
    def __init__(self, settings, mapping, mapping_path, week_id):
        self.settings = settings
        self.mapping = mapping
        self.mapping_path = str(mapping_path)
        self.week_id = week_id
        self.regenerate_note = ""
        self.listeners = []
        self.lock = threading.Lock()
        self.payload = build_workbench_payload(settings, mapping, week_id, regenerate_note="")
        self.payload["should_close"] = False

    def _preserve_runtime_fields(self, payload):
        with self.lock:
            current = dict(self.payload)
        if current.get("should_close"):
            payload["should_close"] = True
        if "archived_path" in current:
            payload["archived_path"] = current["archived_path"]
        return payload

    def refresh_payload(self, draft=None):
        payload = build_workbench_payload(
            settings=self.settings,
            mapping=self.mapping,
            week_id=self.week_id,
            draft=draft,
            regenerate_note=self.regenerate_note,
        )
        payload = self._preserve_runtime_fields(payload)
        with self.lock:
            self.payload = payload
            return self.payload

    def get_payload(self):
        return self.refresh_payload()

    def replace_payload(self, payload):
        with self.lock:
            payload.setdefault("should_close", False)
            self.payload = payload
            listeners = list(self.listeners)
        for listener in listeners:
            listener.set()

    def subscribe(self):
        event = threading.Event()
        with self.lock:
            self.listeners.append(event)
        return event

    def unsubscribe(self, event):
        with self.lock:
            if event in self.listeners:
                self.listeners.remove(event)


def finalize_workbench_archive(state, content):
    stage_weekly_report(
        state.settings["data_root"],
        state.week_id,
        content,
        datetime.now().astimezone(),
    )
    target = archive_staged_report(
        state.settings["data_root"],
        state.week_id,
        datetime.now().astimezone(),
    )
    updated = build_workbench_payload(
        settings=state.settings,
        mapping=state.mapping,
        week_id=state.week_id,
        draft=content,
        regenerate_note=state.regenerate_note,
    )
    updated["archived_path"] = str(target)
    updated["should_close"] = True
    state.replace_payload(updated)
    return updated


def sync_workbench_week(state):
    _, week_end = week_bounds_for_id(state.week_id, state.settings["timezone"])
    sync_sessions(
        settings=state.settings,
        current_cwd=str(Path.cwd()),
        now=week_end,
    )


def regenerate_workbench_draft(state, note):
    state.regenerate_note = note
    sync_workbench_week(state)
    generated = render_weekly_report_draft(
        prepare_weekly_source(state.week_id, state.mapping, state.settings),
        guidance=note,
    )
    stage_weekly_report(
        state.settings["data_root"],
        state.week_id,
        generated,
        datetime.now().astimezone(),
    )
    updated = build_workbench_payload(
        settings=state.settings,
        mapping=state.mapping,
        week_id=state.week_id,
        draft=generated,
        regenerate_note=state.regenerate_note,
    )
    state.replace_payload(updated)
    return updated


def dispatch_workbench_post(state, path, payload):
    try:
        if path == "/api/draft":
            content = payload.get("draft", "")
            stage_weekly_report(
                state.settings["data_root"],
                state.week_id,
                content,
                datetime.now().astimezone(),
            )
            state.replace_payload(
                build_workbench_payload(
                    settings=state.settings,
                    mapping=state.mapping,
                    week_id=state.week_id,
                    draft=content,
                    regenerate_note=state.regenerate_note,
                )
            )
            return state.get_payload(), HTTPStatus.OK, False
        if path == "/api/regenerate":
            note = payload.get("note", "")
            regenerate_workbench_draft(state, note)
            return state.get_payload(), HTTPStatus.OK, False
        if path == "/api/mapping":
            mapping = load_mapping_from_object(payload.get("mapping", {}))
            save_mapping(state.mapping_path, mapping)
            state.mapping = mapping
            state.replace_payload(
                build_workbench_payload(
                    settings=state.settings,
                    mapping=state.mapping,
                    week_id=state.week_id,
                    draft=state.get_payload()["draft"],
                    regenerate_note=state.regenerate_note,
                )
            )
            return state.get_payload(), HTTPStatus.OK, False
        if path == "/api/git-identity":
            identity = payload.get("git_identity", {})
            save_git_identity_map(state.settings["git_identity_path"], identity)
            state.replace_payload(
                build_workbench_payload(
                    settings=state.settings,
                    mapping=state.mapping,
                    week_id=state.week_id,
                    draft=state.get_payload()["draft"],
                    regenerate_note=state.regenerate_note,
                )
            )
            return state.get_payload(), HTTPStatus.OK, False
        if path == "/api/archive":
            content = payload.get("draft", state.get_payload()["draft"])
            updated = finalize_workbench_archive(state, content)
            return updated, HTTPStatus.OK, True
        return {"error": "Not found"}, HTTPStatus.NOT_FOUND, False
    except Exception as exc:
        return {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR, False


def create_workbench_handler(state):
    class WorkbenchHandler(BaseHTTPRequestHandler):
        def _write_json(self, payload, status=HTTPStatus.OK):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            body = self.rfile.read(length)
            return json.loads(body.decode("utf-8"))

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                html = render_workbench_html(state.get_payload()).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return
            if parsed.path == "/api/state":
                self._write_json(state.get_payload())
                return
            if parsed.path == "/events":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                listener = state.subscribe()
                try:
                    self.wfile.write(f"data: {json.dumps(state.get_payload(), ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    while True:
                        listener.wait()
                        listener.clear()
                        self.wfile.write(f"data: {json.dumps(state.get_payload(), ensure_ascii=False)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    state.unsubscribe(listener)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            parsed = urlparse(self.path)
            payload = self._read_json()
            body, status, should_shutdown = dispatch_workbench_post(state, parsed.path, payload)
            self._write_json(body, status=status)
            if should_shutdown:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format, *args):
            return

    return WorkbenchHandler


def open_workbench(settings, mapping, mapping_path, week_id, host="127.0.0.1", port=0):
    state = WorkbenchState(
        settings=settings,
        mapping=mapping,
        mapping_path=mapping_path,
        week_id=week_id,
    )
    server = ThreadingHTTPServer((host, port), create_workbench_handler(state))
    return {
        "server": server,
        "url": f"http://{host}:{server.server_port}/",
        "state": state,
    }


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
