"""Shared Zotero profile, HTTP, authorization, and status support."""

from __future__ import annotations

import argparse
import configparser
import json
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = os.environ.get("ZOTERO_LOCAL_BASE_URL", "http://127.0.0.1:23119")
LOCAL_API_PREF = "extensions.zotero.httpServer.localAPI.enabled"
LOCAL_USER = "/api/users/0"
API_VERSION_HEADERS = {"Zotero-API-Version": "3"}
CONNECTOR_HEADERS = {"X-Zotero-Connector-API-Version": "3"}
TEXT_LIMIT = 300
API_PAGE_LIMIT = 100
WRITE_AUTH_TIMEOUT = 120.0
WRITE_AUTH_APP_NAME = "Zotero Skill"
ANNOTATION_COLORS = {
    "yellow": "#ffd400",
    "red": "#ff6666",
    "green": "#5fb236",
    "blue": "#2ea8e5",
    "purple": "#a28ae5",
    "magenta": "#e56eee",
    "orange": "#f19837",
    "gray": "#aaaaaa",
}


@dataclass(frozen=True)
class Response:
    status: int | None
    headers: dict[str, str]
    text: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def content_type(self) -> str:
        return self.headers.get("Content-Type", "")

@dataclass(frozen=True)
class PdfQuoteMatch:
    page_index: int
    page_label: str
    rects: list[list[float]]
    sort_index: str


def dump_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=False))


def exit_with(message: str) -> None:
    raise SystemExit(message)


def zotero_roots() -> list[Path]:
    home = Path.home()
    system = platform.system()
    roots: list[Path] = []

    if system == "Darwin":
        roots.append(home / "Library/Application Support/Zotero")
    elif system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.extend([Path(appdata) / "Zotero/Zotero", Path(appdata) / "Zotero"])
    else:
        roots.extend(
            [
                home / ".zotero/zotero",
                home / ".var/app/org.zotero.Zotero/data/zotero",
            ]
        )

    # Useful fallback when scripts run under shells whose platform config is odd.
    roots.append(home / "Library/Application Support/Zotero")
    return list(dict.fromkeys(roots))


def profiles_ini_path() -> Path | None:
    for root in zotero_roots():
        candidate = root / "profiles.ini"
        if candidate.exists():
            return candidate
    return None


def profile_dir() -> Path | None:
    ini = profiles_ini_path()
    if ini is None:
        return None

    parser = configparser.RawConfigParser()
    parser.read(ini)
    root = ini.parent
    candidates: list[tuple[int, Path]] = []

    for section in parser.sections():
        if not section.lower().startswith("profile") or not parser.has_option(section, "Path"):
            continue
        raw_path = parser.get(section, "Path")
        path = (
            root / raw_path
            if parser.get(section, "IsRelative", fallback="1") == "1"
            else Path(raw_path)
        )
        score = 0
        if parser.get(section, "Default", fallback="0") == "1":
            score += 10
        if (path / "prefs.js").exists():
            score += 5
        candidates.append((score, path))

    if candidates:
        return max(candidates, key=lambda item: item[0])[1]

    profiles = sorted((root / "Profiles").glob("*.default*"))
    return profiles[0] if profiles else None


def prefs_file() -> Path | None:
    profile = profile_dir()
    if profile is None:
        return None
    candidate = profile / "prefs.js"
    return candidate if candidate.exists() else None


def pref_pattern() -> re.Pattern[str]:
    return re.compile(r'user_pref\("' + re.escape(LOCAL_API_PREF) + r'",\s*(true|false)\s*\);')


def read_local_api_pref() -> bool | None:
    prefs = prefs_file()
    if prefs is None:
        return None
    match = pref_pattern().search(prefs.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        return None
    return match.group(1) == "true"


def set_local_api_pref(enabled: bool) -> Path:
    prefs = prefs_file()
    if prefs is None:
        exit_with("Could not find Zotero prefs.js. Start Zotero once, then retry.")

    backup = prefs.with_suffix(prefs.suffix + f".zotero-skill-backup-{int(time.time())}")
    shutil.copy2(prefs, backup)

    text = prefs.read_text(encoding="utf-8", errors="replace")
    new_line = f'user_pref("{LOCAL_API_PREF}", {str(enabled).lower()});'
    pattern = pref_pattern()
    if pattern.search(text):
        text = pattern.sub(new_line, text, count=1)
    else:
        text = text.rstrip("\n") + "\n" + new_line + "\n"
    prefs.write_text(text, encoding="utf-8")
    return backup


def url_for(path: str, base_url: str = DEFAULT_BASE_URL) -> str:
    return base_url.rstrip("/") + path


def request(
    path: str,
    *,
    method: str = "GET",
    data: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> Response:
    req_headers = dict(headers or {})
    body: bytes | None = None

    if path.startswith("/api"):
        req_headers.update({k: v for k, v in API_VERSION_HEADERS.items() if k not in req_headers})
    if path.startswith("/connector"):
        req_headers.update({k: v for k, v in CONNECTOR_HEADERS.items() if k not in req_headers})

    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, bytes):
            body = data
        else:
            body = str(data).encode("utf-8")

    try:
        req = urllib.request.Request(url_for(path), data=body, method=method, headers=req_headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return Response(
                status=response.status,
                headers=dict(response.headers.items()),
                text=response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return Response(
            status=exc.code,
            headers=dict(exc.headers.items()),
            text=exc.read().decode("utf-8", errors="replace"),
            error=str(exc),
        )
    except Exception as exc:  # local server down, Zotero closed, malformed URL, etc.
        return Response(status=None, headers={}, text="", error=str(exc))


def parse_body(response: Response) -> Any:
    if "json" not in response.content_type.lower():
        return response.text
    try:
        return json.loads(response.text or "null")
    except json.JSONDecodeError:
        return response.text


def require_ok(response: Response, action: str) -> Response:
    if response.ok:
        return response
    detail = response.text[:TEXT_LIMIT] or response.error or "no response body"
    exit_with(f"{action} failed: status={response.status} detail={detail}")
    raise AssertionError("unreachable")


def api_response(path: str) -> Response:
    api_path = path if path.startswith("/api") else "/api" + path
    return require_ok(request(api_path), f"GET {api_path}")


def api_get(path: str) -> Any:
    return parse_body(api_response(path))

def response_header(response: Response, name: str) -> str | None:
    wanted = name.lower()
    return next((value for key, value in response.headers.items() if key.lower() == wanted), None)

def api_get_all(
    path: str, params: dict[str, str | int | bool | None] | None = None
) -> list[Any]:
    rows: list[Any] = []
    start = 0
    while True:
        page_params = dict(params or {})
        page_params.update({"limit": API_PAGE_LIMIT, "start": start})
        separator = "&" if "?" in path else "?"
        response = api_response(f"{path}{separator}{query(page_params)}")
        page = parse_body(response)
        if not isinstance(page, list):
            exit_with(f"Expected a list response from {path}")

        rows.extend(page)
        total = total_results(response)
        if not page or (total is not None and len(rows) >= total):
            return rows
        if total is None and len(page) < API_PAGE_LIMIT:
            return rows
        start += len(page)



def authorization_file() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "zotero-skill" / "local-api-authorizations.json"


def load_authorizations() -> dict[str, str]:
    path = authorization_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        exit_with(f"Could not read local API authorizations: {path}")
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in data.items()
    ):
        exit_with(f"Invalid local API authorizations file: {path}")
    return data


def save_authorizations(authorizations: dict[str, str]) -> None:
    path = authorization_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(authorizations, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def local_server_id() -> str:
    response = require_ok(request("/api/"), "GET /api/")
    server_id = response_header(response, "Zotero-Server-ID")
    if not server_id:
        exit_with("Zotero did not return Zotero-Server-ID; note writes require Zotero 10+.")
    return server_id


def authorize_local_writes(server_id: str) -> tuple[str, bool]:
    response = require_ok(
        request(
            "/api/local/authorize",
            method="POST",
            data={"appName": WRITE_AUTH_APP_NAME},
            headers={"Zotero-Server-ID": server_id},
            timeout=WRITE_AUTH_TIMEOUT,
        ),
        "POST /api/local/authorize",
    )
    payload = parse_body(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("key"), str):
        exit_with("Zotero returned an invalid local write authorization.")
    key = payload["key"]
    remembered = payload.get("remember") is True
    authorizations = load_authorizations()
    authorizations[server_id] = key
    save_authorizations(authorizations)
    return key, remembered


def local_write_credentials(*, authorize_if_missing: bool = True) -> tuple[str, str]:
    server_id = local_server_id()
    key = load_authorizations().get(server_id)
    if key:
        return server_id, key
    if not authorize_if_missing:
        exit_with("No local write authorization. Run authorize-writes first.")
    key, _ = authorize_local_writes(server_id)
    return server_id, key


def clear_local_authorization(server_id: str) -> None:
    authorizations = load_authorizations()
    if server_id not in authorizations:
        return
    del authorizations[server_id]
    save_authorizations(authorizations)


def local_api_write(
    path: str,
    *,
    method: str,
    data: Any = None,
    headers: dict[str, str] | None = None,
) -> Response:
    api_path = path if path.startswith("/api") else "/api" + path
    server_id, key = local_write_credentials()
    write_headers = {
        "Zotero-Server-ID": server_id,
        "Zotero-API-Key": key,
        **(headers or {}),
    }
    response = request(api_path, method=method, data=data, headers=write_headers)
    if response.status == 401:
        clear_local_authorization(server_id)
        key, _ = authorize_local_writes(server_id)
        write_headers["Zotero-API-Key"] = key
        response = request(api_path, method=method, data=data, headers=write_headers)
    return require_ok(response, f"{method} {api_path}")


def query(params: dict[str, str | int | bool | None]) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return urllib.parse.urlencode(clean)


def restart_zotero(wait_for_api: bool = True) -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(
                ["osascript", "-e", 'tell application "Zotero" to quit'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            time.sleep(1)
            subprocess.run(["open", "-a", "Zotero"], check=False)
        elif system == "Windows":
            subprocess.run(
                ["taskkill", "/IM", "zotero.exe", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            time.sleep(1)
            subprocess.Popen(["zotero.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(
                ["pkill", "-f", "zotero"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            time.sleep(1)
            subprocess.Popen(["zotero"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False

    if not wait_for_api:
        return True
    for _ in range(30):
        if request("/api/", timeout=1).ok:
            return True
        time.sleep(0.5)
    return False


def total_results(response: Response) -> int | None:
    raw = response_header(response, "Total-Results")
    return int(raw) if raw and raw.isdigit() else None


def status_payload() -> dict[str, Any]:
    root = request("/api/", timeout=2)
    connector = request("/connector/ping", timeout=2)
    profile = profile_dir()
    prefs = prefs_file()
    return {
        "profile": str(profile) if profile else None,
        "prefs_file": str(prefs) if prefs else None,
        "local_api_enabled_pref": read_local_api_pref(),
        "api_running": root.ok,
        "api_status": root.status,
        "api_error": root.error,
        "zotero_version": root.headers.get("X-Zotero-Version")
        or connector.headers.get("X-Zotero-Version"),
        "api_version": root.headers.get("Zotero-API-Version"),
        "schema_version": root.headers.get("Zotero-Schema-Version"),
        "connector_running": connector.ok,
        "connector_status": connector.status,
        "connector_error": connector.error,
        "base_url": DEFAULT_BASE_URL,
    }


def cmd_status(args: argparse.Namespace) -> None:
    payload = status_payload()
    if args.json:
        dump_json(payload)
        return
    print(f"Zotero local API pref: {payload['local_api_enabled_pref']} ({payload['prefs_file']})")
    print(
        "API running: "
        f"{payload['api_running']} status={payload['api_status']} "
        f"version={payload['api_version']} zotero={payload['zotero_version']}"
    )
    print(f"Connector running: {payload['connector_running']} status={payload['connector_status']}")


def cmd_set_pref(args: argparse.Namespace, enabled: bool) -> None:
    backup = set_local_api_pref(enabled)
    restarted = restart_zotero(wait_for_api=enabled) if args.restart else False
    dump_json(
        {
            "enabled": enabled,
            "backup": str(backup),
            "restarted": restarted,
            "status": status_payload(),
        }
    )


def cmd_restart(_: argparse.Namespace) -> None:
    dump_json({"restarted": restart_zotero(wait_for_api=True)})
