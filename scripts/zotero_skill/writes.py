"""Zotero note and connector write commands."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
from typing import Any
import urllib.parse
import uuid

from .core import (
    LOCAL_USER,
    Response,
    api_get,
    authorization_file,
    authorize_local_writes,
    dump_json,
    exit_with,
    local_api_write,
    local_server_id,
    parse_body,
    query,
    request,
    require_ok,
    response_header,
)


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

