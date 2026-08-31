"""Command-line interface for the Zotero Desktop helper."""

from __future__ import annotations

import argparse

from .annotations import cmd_annotate
from .core import ANNOTATION_COLORS, cmd_restart, cmd_set_pref, cmd_status
from .library import (
    cmd_children,
    cmd_citations,
    cmd_cite,
    cmd_collections,
    cmd_export_bibtex,
    cmd_file_url,
    cmd_fulltext,
    cmd_groups,
    cmd_inventory,
    cmd_probe,
    cmd_search,
    cmd_sync_bib,
    cmd_tags,
)
from .writes import (
    cmd_authorize_writes,
    cmd_create_note,
    cmd_delete_note,
    cmd_import_records,
    cmd_selected_target,
    cmd_update_note,
)


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
