"""Exact PDF quote matching and native Zotero annotations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import unicodedata
import urllib.parse
import urllib.request
import uuid

from .core import (
    ANNOTATION_COLORS,
    LOCAL_USER,
    PdfQuoteMatch,
    api_get,
    api_get_all,
    dump_json,
    exit_with,
    local_api_write,
    parse_body,
)
from .writes import require_confirmed_write


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
    annotations = api_get_all(
        f"{LOCAL_USER}/items", {"itemType": "annotation"}
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

