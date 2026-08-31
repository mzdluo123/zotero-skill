#!/usr/bin/env python3
"""Operate Zotero Desktop's local API and connector server.

Most commands are Python-stdlib-only. Precise PDF annotation additionally uses
PyMuPDF for text coordinates. All Zotero calls go through the local Desktop HTTP surfaces on
http://127.0.0.1:23119.
"""

from __future__ import annotations

import argparse
import html
import configparser
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import unicodedata
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


def note_html(args: argparse.Namespace) -> str:
    if args.html is not None:
        return args.html
    if args.text is not None:
        text = args.text
    else:
        text = Path(args.file).expanduser().read_text(encoding="utf-8")
        if args.file_format == "html":
            return text
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return "".join(f"<p>{html.escape(part).replace(chr(10), '<br>')}</p>" for part in paragraphs)



def annotation_argument(args: argparse.Namespace, name: str) -> str:
    value = getattr(args, name)
    if value is not None:
        return value
    path = Path(getattr(args, f"{name}_file")).expanduser()
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        exit_with(f"{path} is empty.")
    return text


def normalize_pdf_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def pdf_attachment_path(attachment_key: str) -> Path:
    data = api_get(f"{LOCAL_USER}/items/{urllib.parse.quote(attachment_key)}")
    item = data.get("data") if isinstance(data, dict) else None
    if not isinstance(item, dict) or item.get("itemType") != "attachment":
        exit_with(f"Zotero item {attachment_key} is not an attachment.")
    if item.get("contentType") != "application/pdf":
        exit_with(f"Zotero attachment {attachment_key} is not a PDF.")
    file_url = api_get(
        f"{LOCAL_USER}/items/{urllib.parse.quote(attachment_key)}/file/view/url"
    )
    parsed = urllib.parse.urlparse(str(file_url))
    if parsed.scheme != "file":
        exit_with(f"Zotero attachment {attachment_key} is not a stored local PDF.")
    path = Path(urllib.request.url2pathname(urllib.parse.unquote(parsed.path)))
    if not path.is_file():
        exit_with(f"Zotero PDF file does not exist: {path}")
    return path


def find_pdf_quote(path: Path, quote: str, page_number: int | None) -> PdfQuoteMatch:
    try:
        import fitz
    except ImportError:
        exit_with(
            "Precise PDF annotation requires PyMuPDF. "
            "Install it with: python3 -m pip install -r requirements.txt"
        )

    normalized_quote = normalize_pdf_text(quote)
    if not normalized_quote:
        exit_with("The annotation quote is empty.")

    matches: list[PdfQuoteMatch] = []
    with fitz.open(path) as document:
        if page_number is not None and not 1 <= page_number <= document.page_count:
            exit_with(f"--page must be between 1 and {document.page_count}.")
        page_indexes = (
            [page_number - 1] if page_number is not None else range(document.page_count)
        )
        flags = (
            fitz.TEXT_DEHYPHENATE
            | fitz.TEXT_PRESERVE_WHITESPACE
            | fitz.TEXT_PRESERVE_LIGATURES
        )
        for page_index in page_indexes:
            page = document[page_index]
            if page.rotation:
                exit_with(
                    f"PDF page {page_index + 1} is rotated; precise annotation is not supported."
                )
            page_text = normalize_pdf_text(page.get_text("text", flags=flags))
            occurrence_count = page_text.count(normalized_quote)
            if occurrence_count == 0:
                continue
            if occurrence_count > 1:
                exit_with(
                    f"Quote occurs {occurrence_count} times on PDF page {page_index + 1}; "
                    "provide a longer unique quote."
                )
            found = page.search_for(quote, flags=flags)
            if not found:
                exit_with(
                    f"Quote text was found on PDF page {page_index + 1}, "
                    "but its coordinates could not be resolved."
                )
            height = page.rect.height
            rects = [
                [
                    round(rect.x0, 3),
                    round(height - rect.y1, 3),
                    round(rect.x1, 3),
                    round(height - rect.y0, 3),
                ]
                for rect in found
            ]
            top = min(rect.y0 for rect in found)
            left = min(rect.x0 for rect in found if abs(rect.y0 - top) < 1)
            sort_index = (
                f"{page_index:05d}|{min(int(top * 100), 999999):06d}|"
                f"{min(int(left * 100), 99999):05d}"
            )
            matches.append(
                PdfQuoteMatch(
                    page_index=page_index,
                    page_label=page.get_label() or str(page_index + 1),
                    rects=rects,
                    sort_index=sort_index,
                )
            )

    if not matches:
        page_detail = f" on PDF page {page_number}" if page_number is not None else ""
        exit_with(f"Exact quote not found{page_detail}.")
    if len(matches) > 1:
        pages = ", ".join(str(match.page_index + 1) for match in matches)
        exit_with(f"Quote occurs on multiple PDF pages ({pages}); specify --page.")
    return matches[0]


def existing_annotation(
    attachment_key: str, quote: str, comment: str, position: str
) -> str | None:
    annotations = api_get(
        f"{LOCAL_USER}/items?{urllib.parse.urlencode({'itemType': 'annotation'})}"
    )
    for child in annotations:
        data = child.get("data", {})
        if (
            data.get("itemType") == "annotation"
            and data.get("annotationType") == "highlight"
            and data.get("annotationText") == quote
            and data.get("annotationComment") == comment
            and data.get("annotationPosition") == position
        ):
            return data.get("key")
    return None

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


def creators_from_item(data: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for creator in data.get("creators", []) or []:
        name = creator.get("name") or " ".join(
            part for part in [creator.get("firstName"), creator.get("lastName")] if part
        )
        if name:
            names.append(name)
    return names


def year_from_date(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(r"(\d{4})", raw)
    return match.group(1) if match else None


def summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data", item)
    return {
        "key": item.get("key") or data.get("key"),
        "itemType": data.get("itemType"),
        "title": data.get("title"),
        "creators": creators_from_item(data),
        "year": year_from_date(data.get("date")),
    }


def summarize_collection(collection: dict[str, Any]) -> dict[str, Any]:
    data = collection.get("data", collection)
    return {
        "key": collection.get("key") or data.get("key"),
        "name": data.get("name"),
        "parentCollection": data.get("parentCollection"),
        "version": collection.get("version"),
    }


def summarize_tag(tag: dict[str, Any]) -> dict[str, Any]:
    return {"tag": tag.get("tag"), "numItems": (tag.get("meta") or {}).get("numItems")}


def summarize_group(group: dict[str, Any]) -> dict[str, Any]:
    data = group.get("data", group)
    return {
        "id": group.get("id") or data.get("id"),
        "name": data.get("name"),
        "type": data.get("type"),
    }


def print_items(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        creators = ", ".join(row.get("creators") or [])
        print(
            f"{row.get('key') or '':10} "
            f"{row.get('itemType') or '':14} "
            f"{row.get('year') or '':4} "
            f"{row.get('title') or ''} | {creators}"
        )


def extract_bibtex_keys(text: str) -> list[str]:
    return re.findall(r"@\w+\s*\{\s*([^,\s]+)", text)


def count_bibtex_entries(text: str) -> int:
    return len(extract_bibtex_keys(text))


def total_results(response: Response) -> int | None:
    raw = response.headers.get("Total-Results")
    return int(raw) if raw and raw.isdigit() else None


def export_bibtex(item_key: str | None = None, *, include_children: bool = False) -> str:
    if item_key:
        params = query({"itemKey": item_key, "format": "bibtex", "limit": API_PAGE_LIMIT})
        return api_response(f"{LOCAL_USER}/items?{params}").text

    endpoint = "items" if include_children else "items/top"
    start = 0
    chunks: list[str] = []
    while True:
        params = query(
            {
                "format": "bibtex",
                "sort": "title",
                "direction": "asc",
                "limit": API_PAGE_LIMIT,
                "start": start,
            }
        )
        response = api_response(f"{LOCAL_USER}/{endpoint}?{params}")
        if response.text.strip():
            chunks.append(response.text.strip())

        total = total_results(response)
        start += API_PAGE_LIMIT
        if total is not None and start >= total:
            break
        if total is None and count_bibtex_entries(response.text) < API_PAGE_LIMIT:
            break

    text = "\n\n".join(chunks)
    return text + "\n" if text else ""


def write_text_output(text: str, out: str | None) -> None:
    if out is None:
        print(text, end="" if text.endswith("\n") else "\n")
        return

    path = Path(out).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    dump_json(
        {
            "path": str(path),
            "bytes": len(text.encode("utf-8")),
            "bibtex_entries": count_bibtex_entries(text),
        }
    )


def append_bib_entry(bib_path: Path, entry: str) -> tuple[str, bool]:
    keys = extract_bibtex_keys(entry)
    if not keys:
        exit_with("Could not extract a BibTeX key from Zotero export")
    key = keys[0]

    existing = bib_path.read_text(encoding="utf-8", errors="replace") if bib_path.exists() else ""
    already_present = re.search(r"@\w+\s*\{\s*" + re.escape(key) + r"\s*,", existing) is not None
    if already_present:
        return key, False

    bib_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = existing.rstrip("\n") + "\n\n" if existing else ""
    bib_path.write_text(prefix + entry.strip() + "\n", encoding="utf-8")
    return key, True


def insert_citation(target: Path, citation: str, marker: str | None) -> None:
    text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    if marker:
        if marker not in text:
            exit_with(f"Marker not found in {target}: {marker!r}")
        target.write_text(text.replace(marker, citation, 1), encoding="utf-8")
        return

    suffix = "" if not text or text.endswith("\n") else "\n"
    target.write_text(text + suffix + citation + "\n", encoding="utf-8")


def find_item(*, item_key: str | None, query_text: str | None) -> dict[str, Any]:
    if item_key:
        return api_get(f"{LOCAL_USER}/items/{urllib.parse.quote(item_key)}")
    if not query_text:
        exit_with("Provide --item-key or --query")

    params = query({"q": query_text})
    matches = api_get(f"{LOCAL_USER}/items/top?{params}")
    if not matches:
        exit_with(f"No top-level Zotero items matched query: {query_text}")
    if len(matches) > 1:
        print(
            f"warning: {len(matches)} matches; using first result {matches[0].get('key')}",
            file=sys.stderr,
        )
    return matches[0]


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


def cmd_probe(args: argparse.Namespace) -> None:
    endpoints = [
        ("root", "/api/"),
        ("schema", "/api/schema"),
        ("itemTypes", "/api/itemTypes"),
        ("itemFields", "/api/itemFields"),
        ("creatorFields", "/api/creatorFields"),
        ("collections", f"{LOCAL_USER}/collections"),
        ("topCollections", f"{LOCAL_USER}/collections/top"),
        ("topItems", f"{LOCAL_USER}/items/top"),
        ("tags", f"{LOCAL_USER}/tags"),
        ("searches", f"{LOCAL_USER}/searches"),
        ("groups", f"{LOCAL_USER}/groups"),
        ("fulltextVersions", f"{LOCAL_USER}/fulltext?since=0"),
        ("connectorPing", "/connector/ping"),
    ]
    rows: list[dict[str, Any]] = []
    for label, path in endpoints:
        response = request(path)
        parsed = parse_body(response)
        if isinstance(parsed, list):
            summary: Any = {"type": "array", "len": len(parsed)}
        elif isinstance(parsed, dict):
            summary = {"type": "object", "keys": list(parsed)[:8]}
        else:
            summary = str(parsed)[:160]
        rows.append(
            {
                "label": label,
                "path": path,
                "status": response.status,
                "content_type": response.content_type,
                "total": response.headers.get("Total-Results"),
                "summary": summary,
            }
        )

    if args.json:
        dump_json(rows)
        return
    for row in rows:
        print(
            f"{row['status'] or 'ERR':>3} {row['label']:18} {row['path']:45} total={row['total']} {row['summary']}"
        )


def cmd_inventory(args: argparse.Namespace) -> None:
    endpoint = "items" if args.include_children else "items/top"
    params = query({"sort": "title", "direction": "asc"})
    rows = [summarize_item(item) for item in api_get(f"{LOCAL_USER}/{endpoint}?{params}")]
    dump_json(rows) if args.json else print_items(rows)


def cmd_collections(args: argparse.Namespace) -> None:
    rows = [summarize_collection(collection) for collection in api_get(f"{LOCAL_USER}/collections")]
    if args.json:
        dump_json(rows)
        return
    for row in rows:
        parent = f" parent={row['parentCollection']}" if row.get("parentCollection") else ""
        print(f"{row.get('key') or '':10} {row.get('name') or ''}{parent}")


def cmd_tags(args: argparse.Namespace) -> None:
    rows = [summarize_tag(tag) for tag in api_get(f"{LOCAL_USER}/tags")]
    if args.json:
        dump_json(rows)
        return
    for row in rows:
        print(f"{row.get('tag') or ''} ({row.get('numItems') or 0})")


def cmd_groups(args: argparse.Namespace) -> None:
    rows = [summarize_group(group) for group in api_get(f"{LOCAL_USER}/groups")]
    if args.json:
        dump_json(rows)
        return
    for row in rows:
        print(f"{row.get('id') or '':>10} {row.get('type') or '':12} {row.get('name') or ''}")


def cmd_search(args: argparse.Namespace) -> None:
    params = query({"q": args.query})
    rows = [summarize_item(item) for item in api_get(f"{LOCAL_USER}/items/top?{params}")]
    if args.with_bibtex_keys:
        for row in rows:
            bibtex = export_bibtex(row.get("key")) if row.get("key") else ""
            keys = extract_bibtex_keys(bibtex)
            row["bibtexKey"] = keys[0] if keys else None
    dump_json(rows) if args.json else print_items(rows)


def cmd_export_bibtex(args: argparse.Namespace) -> None:
    write_text_output(
        export_bibtex(args.item_key, include_children=args.include_children), args.out
    )


def cmd_sync_bib(args: argparse.Namespace) -> None:
    text = export_bibtex(include_children=args.include_children)
    path = Path(args.out).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    dump_json({"path": str(path), "entries": count_bibtex_entries(text)})


def cmd_citations(args: argparse.Namespace) -> None:
    params = query({"include": "data,citation", "style": args.style})
    rows: list[dict[str, Any]] = []
    for item in api_get(f"{LOCAL_USER}/items/top?{params}"):
        row = summarize_item(item)
        row["citation"] = item.get("citation")
        rows.append(row)
    if args.json:
        dump_json(rows)
        return
    for row in rows:
        print(f"{row.get('key')} {row.get('citation')}")


def cmd_children(args: argparse.Namespace) -> None:
    data = api_get(f"{LOCAL_USER}/items/{urllib.parse.quote(args.item_key)}/children")
    rows = [summarize_item(item) for item in data]
    dump_json(rows) if args.json else print_items(rows)


def cmd_fulltext(args: argparse.Namespace) -> None:
    data = api_get(f"{LOCAL_USER}/items/{urllib.parse.quote(args.attachment_key)}/fulltext")
    content = data.get("content", "") if isinstance(data, dict) else str(data)
    if args.out is None:
        print(content)
        return
    path = Path(args.out).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    dump_json(
        {
            "path": str(path),
            "chars": len(content),
            "indexedPages": data.get("indexedPages") if isinstance(data, dict) else None,
            "totalPages": data.get("totalPages") if isinstance(data, dict) else None,
        }
    )


def cmd_file_url(args: argparse.Namespace) -> None:
    print(api_get(f"{LOCAL_USER}/items/{urllib.parse.quote(args.attachment_key)}/file/view/url"))

def require_confirmed_write(args: argparse.Namespace, action: str) -> None:
    if not args.yes:
        exit_with(f"Refusing to {action} without --yes.")


def cmd_authorize_writes(_: argparse.Namespace) -> None:
    server_id = local_server_id()
    _, remembered = authorize_local_writes(server_id)
    dump_json(
        {
            "authorized": True,
            "remembered": remembered,
            "server_id": server_id,
            "credentials_file": str(authorization_file()),
        }
    )


def cmd_create_note(args: argparse.Namespace) -> None:
    require_confirmed_write(args, "create a Zotero note")
    payload: dict[str, Any] = {
        "itemType": "note",
        "note": note_html(args),
        "tags": [{"tag": tag} for tag in args.tag],
        "collections": args.collection,
    }
    if args.parent_item:
        payload["parentItem"] = args.parent_item
    response = local_api_write(
        f"{LOCAL_USER}/items",
        method="POST",
        data=[payload],
        headers={"Zotero-Write-Token": uuid.uuid4().hex},
    )
    result = parse_body(response)
    item_key = result.get("success", {}).get("0") if isinstance(result, dict) else None
    dump_json(
        {
            "created": bool(item_key),
            "item_key": item_key,
            "parent_item": args.parent_item,
            "response": result,
        }
    )


def get_note_item(item_key: str) -> dict[str, Any]:
    quoted_key = urllib.parse.quote(item_key)
    item = api_get(f"{LOCAL_USER}/items/{quoted_key}")
    data = item.get("data") if isinstance(item, dict) else None
    if not isinstance(data, dict) or data.get("itemType") != "note":
        exit_with(f"Zotero item {item_key} is not a note.")
    return data


def cmd_update_note(args: argparse.Namespace) -> None:
    require_confirmed_write(args, "update a Zotero note")
    current = get_note_item(args.note_key)
    version = current.get("version")
    if not isinstance(version, int):
        exit_with(f"Zotero note {args.note_key} has no valid version.")
    response = local_api_write(
        f"{LOCAL_USER}/items/{urllib.parse.quote(args.note_key)}",
        method="PATCH",
        data={"note": note_html(args)},
        headers={"If-Unmodified-Since-Version": str(version)},
    )
    dump_json(
        {
            "updated": True,
            "item_key": args.note_key,
            "previous_version": version,
            "new_version": response_header(response, "Last-Modified-Version"),
        }
    )


def cmd_delete_note(args: argparse.Namespace) -> None:
    require_confirmed_write(args, "delete a Zotero note")
    current = get_note_item(args.note_key)
    version = current.get("version")
    if not isinstance(version, int):
        exit_with(f"Zotero note {args.note_key} has no valid version.")
    response = local_api_write(
        f"{LOCAL_USER}/items/{urllib.parse.quote(args.note_key)}",
        method="DELETE",
        headers={"If-Unmodified-Since-Version": str(version)},
    )
    dump_json(
        {
            "deleted": True,
            "item_key": args.note_key,
            "previous_version": version,
            "new_version": response_header(response, "Last-Modified-Version"),
        }
    )

def cmd_annotate(args: argparse.Namespace) -> None:
    require_confirmed_write(args, "create a Zotero PDF annotation")
    quote = annotation_argument(args, "quote")
    comment = annotation_argument(args, "comment")
    pdf_path = pdf_attachment_path(args.attachment_key)
    match = find_pdf_quote(pdf_path, quote, args.page)
    position = json.dumps(
        {"pageIndex": match.page_index, "rects": match.rects},
        separators=(",", ":"),
    )
    duplicate_key = existing_annotation(
        args.attachment_key, quote, comment, position
    )
    if duplicate_key:
        dump_json(
            {
                "created": False,
                "unchanged": True,
                "annotation_key": duplicate_key,
                "attachment_key": args.attachment_key,
                "page_index": match.page_index,
                "page_label": match.page_label,
            }
        )
        return

    payload = {
        "itemType": "annotation",
        "parentItem": args.attachment_key,
        "annotationType": "highlight",
        "annotationText": quote,
        "annotationComment": comment,
        "annotationColor": ANNOTATION_COLORS[args.color],
        "annotationPageLabel": match.page_label,
        "annotationSortIndex": match.sort_index,
        "annotationPosition": position,
        "tags": [{"tag": tag} for tag in args.tag],
    }
    response = local_api_write(
        f"{LOCAL_USER}/items",
        method="POST",
        data=[payload],
        headers={"Zotero-Write-Token": uuid.uuid4().hex},
    )
    result = parse_body(response)
    annotation_key = (
        result.get("success", {}).get("0") if isinstance(result, dict) else None
    )
    if not annotation_key:
        exit_with(f"Zotero did not create the annotation: {result}")
    saved = api_get(
        f"{LOCAL_USER}/items/{urllib.parse.quote(annotation_key)}"
    ).get("data", {})
    if (
        saved.get("parentItem") != args.attachment_key
        or saved.get("annotationPosition") != position
        or saved.get("annotationText") != quote
        or saved.get("annotationComment") != comment
    ):
        exit_with(
            f"Annotation {annotation_key} was created but failed read-back verification."
        )
    dump_json(
        {
            "created": True,
            "annotation_key": annotation_key,
            "attachment_key": args.attachment_key,
            "pdf_path": str(pdf_path),
            "page_index": match.page_index,
            "page_label": match.page_label,
            "rects": match.rects,
            "color": args.color,
            "comment": comment,
        }
    )


def cmd_cite(args: argparse.Namespace) -> None:
    item = find_item(item_key=args.item_key, query_text=args.query)
    item_key = item.get("key")
    if not item_key:
        exit_with("Matched Zotero item has no key")

    citekey, added = append_bib_entry(
        Path(args.bib).expanduser().resolve(), export_bibtex(item_key)
    )
    citation = f"\\cite{{{citekey}}}" if args.tex else f"[@{citekey}]"
    target = Path(args.tex or args.markdown).expanduser().resolve()
    insert_citation(target, citation, args.marker)
    dump_json(
        {
            "item_key": item_key,
            "title": summarize_item(item).get("title"),
            "bibtex_key": citekey,
            "bib_path": str(Path(args.bib).expanduser().resolve()),
            "bib_entry_added": added,
            "edited_file": str(target),
            "inserted": citation,
        }
    )


def connector_post(path: str, payload: Any, *, content_type: str = "application/json") -> Response:
    return request(path, method="POST", data=payload, headers={"Content-Type": content_type})


def cmd_selected_target(args: argparse.Namespace) -> None:
    response = require_ok(
        connector_post("/connector/getSelectedCollection", {}),
        "POST /connector/getSelectedCollection",
    )
    payload = parse_body(response)
    print(json.dumps(payload, indent=2) if args.json else payload)


def cmd_import_records(args: argparse.Namespace, kind: str) -> None:
    if not args.yes:
        exit_with(
            f"Refusing to write to Zotero without --yes. "
            f"This imports {kind} into the selected Zotero library/collection."
        )
    text = Path(args.file).expanduser().read_text(encoding="utf-8") if args.file else args.text
    if not text:
        exit_with("Provide --file or --text")

    session = args.session or f"codex-{uuid.uuid4().hex}"
    path = f"/connector/import?{query({'session': session})}"
    response = require_ok(connector_post(path, text, content_type="text/plain"), f"POST {path}")
    dump_json({"status": response.status, "session": session, "response": parse_body(response)})


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="Print JSON instead of a compact text summary"
    )

def add_note_content_args(parser: argparse.ArgumentParser) -> None:
    content = parser.add_mutually_exclusive_group(required=True)
    content.add_argument("--html", help="Zotero note HTML")
    content.add_argument("--text", help="Plain text converted to escaped HTML paragraphs")
    content.add_argument("--file", help="UTF-8 note content file")
    parser.add_argument(
        "--file-format",
        choices=("text", "html"),
        default="text",
        help="Interpret --file as plain text or HTML (default: text)",
    )
    parser.add_argument("--yes", action="store_true", help="Confirm Zotero library write")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate Zotero Desktop local API and connector server."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    status = subcommands.add_parser("status", help="Show Zotero local API and connector readiness")
    add_json_flag(status)
    status.set_defaults(func=cmd_status)

    enable = subcommands.add_parser("enable", help="Enable Zotero's local Desktop API preference")
    enable.add_argument(
        "--restart", action="store_true", help="Restart Zotero after editing prefs.js"
    )
    enable.set_defaults(func=lambda args: cmd_set_pref(args, True))

    disable = subcommands.add_parser(
        "disable", help="Disable Zotero's local Desktop API preference"
    )
    disable.add_argument(
        "--restart", action="store_true", help="Restart Zotero after editing prefs.js"
    )
    disable.set_defaults(func=lambda args: cmd_set_pref(args, False))

    restart = subcommands.add_parser("restart", help="Restart Zotero and wait for the local API")
    restart.set_defaults(func=cmd_restart)

    probe = subcommands.add_parser("probe", help="Probe common safe local API routes")
    add_json_flag(probe)
    probe.set_defaults(func=cmd_probe)

    inventory = subcommands.add_parser("inventory", help="List Zotero items")
    inventory.add_argument(
        "--include-children", action="store_true", help="Include child notes and attachments"
    )
    inventory.add_argument(
        "--all", action="store_true", dest="include_children", help=argparse.SUPPRESS
    )
    add_json_flag(inventory)
    inventory.set_defaults(func=cmd_inventory)

    collections = subcommands.add_parser("collections", help="List collections")
    add_json_flag(collections)
    collections.set_defaults(func=cmd_collections)

    tags = subcommands.add_parser("tags", help="List tags")
    add_json_flag(tags)
    tags.set_defaults(func=cmd_tags)

    groups = subcommands.add_parser("groups", help="List synced group libraries visible locally")
    add_json_flag(groups)
    groups.set_defaults(func=cmd_groups)

    search = subcommands.add_parser("search", help="Search top-level Zotero items")
    search.add_argument("query")
    search.add_argument("--with-bibtex-keys", action="store_true")
    add_json_flag(search)
    search.set_defaults(func=cmd_search)

    export = subcommands.add_parser("export-bibtex", help="Export Zotero items as BibTeX")
    export.add_argument("--item-key")
    export.add_argument("--include-children", action="store_true")
    export.add_argument(
        "--all", action="store_true", dest="include_children", help=argparse.SUPPRESS
    )
    export.add_argument("--out")
    export.set_defaults(func=cmd_export_bibtex)

    sync_bib = subcommands.add_parser("sync-bib", help="Write a references.bib export")
    sync_bib.add_argument("--out", default="references.bib")
    sync_bib.add_argument("--include-children", action="store_true")
    sync_bib.add_argument(
        "--all", action="store_true", dest="include_children", help=argparse.SUPPRESS
    )
    sync_bib.set_defaults(func=cmd_sync_bib)

    citations = subcommands.add_parser("citations", help="Render formatted citations")
    citations.add_argument("--style", default="apa")
    add_json_flag(citations)
    citations.set_defaults(func=cmd_citations)

    children = subcommands.add_parser("children", help="List child notes/attachments for an item")
    children.add_argument("item_key")
    add_json_flag(children)
    children.set_defaults(func=cmd_children)

    fulltext = subcommands.add_parser(
        "fulltext", help="Print or save indexed full text for an attachment"
    )
    fulltext.add_argument("attachment_key")
    fulltext.add_argument("--out")
    fulltext.set_defaults(func=cmd_fulltext)

    file_url = subcommands.add_parser(
        "file-url", help="Print Zotero's local file URL for an attachment"
    )
    file_url.add_argument("attachment_key")
    file_url.set_defaults(func=cmd_file_url)

    authorize_writes = subcommands.add_parser(
        "authorize-writes", help="Ask Zotero to authorize local library writes"
    )
    authorize_writes.set_defaults(func=cmd_authorize_writes)

    create_note = subcommands.add_parser("create-note", help="Create a Zotero note")
    add_note_content_args(create_note)
    create_note.add_argument("--parent-item", help="Create a child note under this item key")
    create_note.add_argument(
        "--collection", action="append", default=[], help="Add standalone note to collection key"
    )
    create_note.add_argument("--tag", action="append", default=[], help="Add tag; repeat as needed")
    create_note.set_defaults(func=cmd_create_note)

    update_note = subcommands.add_parser("update-note", help="Replace a Zotero note's content")
    update_note.add_argument("note_key")
    add_note_content_args(update_note)
    update_note.set_defaults(func=cmd_update_note)

    delete_note = subcommands.add_parser("delete-note", help="Delete a Zotero note")
    delete_note.add_argument("note_key")
    delete_note.add_argument("--yes", action="store_true", help="Confirm destructive Zotero write")
    delete_note.set_defaults(func=cmd_delete_note)

    annotate = subcommands.add_parser(
        "annotate", help="Highlight an exact PDF quote and attach a comment"
    )
    annotate.add_argument("attachment_key", help="Stored Zotero PDF attachment key")
    quote_source = annotate.add_mutually_exclusive_group(required=True)
    quote_source.add_argument("--quote", help="Exact PDF text to highlight")
    quote_source.add_argument("--quote-file", help="UTF-8 file containing the exact quote")
    comment_source = annotate.add_mutually_exclusive_group(required=True)
    comment_source.add_argument("--comment", help="Comment attached to the highlight")
    comment_source.add_argument("--comment-file", help="UTF-8 file containing the comment")
    annotate.add_argument(
        "--page", type=int, help="Restrict matching to this 1-based physical PDF page"
    )
    annotate.add_argument(
        "--color",
        choices=tuple(ANNOTATION_COLORS),
        default="yellow",
        help="Highlight color (default: yellow)",
    )
    annotate.add_argument("--tag", action="append", default=[], help="Add tag; repeat as needed")
    annotate.add_argument("--yes", action="store_true", help="Confirm Zotero library write")
    annotate.set_defaults(func=cmd_annotate)

    cite = subcommands.add_parser(
        "cite", help="Insert a citation into a TeX or Markdown file and update a .bib file"
    )
    source = cite.add_mutually_exclusive_group(required=True)
    source.add_argument("--item-key")
    source.add_argument("--query")
    target = cite.add_mutually_exclusive_group(required=True)
    target.add_argument("--tex")
    target.add_argument("--markdown")
    cite.add_argument("--bib", default="references.bib")
    cite.add_argument(
        "--marker", help="Replace this marker with the citation; otherwise append the citation"
    )
    cite.set_defaults(func=cmd_cite)

    selected = subcommands.add_parser(
        "selected-target", help="Show the currently selected Zotero library/collection"
    )
    add_json_flag(selected)
    selected.set_defaults(func=cmd_selected_target)

    for command, kind in [("import-bibtex", "BibTeX"), ("import-ris", "RIS")]:
        import_cmd = subcommands.add_parser(command, help=f"Import {kind} through Zotero Connector")
        input_group = import_cmd.add_mutually_exclusive_group(required=True)
        input_group.add_argument("--file")
        input_group.add_argument("--text")
        import_cmd.add_argument("--session")
        import_cmd.add_argument("--yes", action="store_true", help="Confirm Zotero library write")
        import_cmd.set_defaults(func=lambda args, kind=kind: cmd_import_records(args, kind))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
