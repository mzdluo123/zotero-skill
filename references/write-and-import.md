# Write and import

Read this file only for Zotero library writes. If the user's prompt does not
already request the exact write, confirm its content and destination first.
Every write command requires `--yes` where supported.

## Local write authorization

Zotero displays an authorization dialog on the first local API write.

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py authorize-writes
python3 <plugin-root>/skills/zotero/scripts/zotero.py selected-target --json
```

## Notes

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py create-note --text 'Research note' --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py create-note --parent-item PXW99EKT --file note.html --file-format html --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py update-note NOTEKEY --text 'Revised note' --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py delete-note NOTEKEY --yes
```

Zotero note bodies are HTML. Use `--text` for escaped plain text. Use `--html`
or `--file-format html` only for trusted HTML. Report the note key, parent item
key when applicable, and resulting local version when available.

## Native PDF highlights

Exact highlighting requires PyMuPDF. Install it only if `annotate` reports that
it is missing:

```bash
python3 -m pip install -r <skill-root>/requirements.txt
```

Create a highlight and attached comment:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py annotate 2JAZS9U8 --quote 'Exact text from the PDF' --comment 'Research comment' --color yellow --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py annotate 2JAZS9U8 --quote-file exact-quote.txt --comment-file comment.txt --page 2 --yes
```

`annotate` accepts only stored PDF attachments. It requires one unique exact
quote and refuses ambiguous matches. `--page` is a 1-based physical PDF page
used for disambiguation. Report the annotation key, attachment key, physical
page index, displayed page label, color, and resolved rectangles.

## BibTeX and RIS imports

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py selected-target --json
python3 <plugin-root>/skills/zotero/scripts/zotero.py import-bibtex --file new-reference.bib --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py import-ris --file new-reference.ris --yes
```

A new-article import is complete only when an available legitimate full-text
PDF is stored as a child attachment of the imported parent item. Prefer the
publisher's official PDF, then an author-hosted copy or preprint. Do not
substitute an unrelated file or leave an available PDF as a standalone or
URL-only attachment.

Verify the result:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py children PARENTKEY --json
python3 <plugin-root>/skills/zotero/scripts/zotero.py file-url ATTACHMENTKEY
```

Report the parent item key, PDF attachment key, PDF source, and successful local
file verification. If no legitimate PDF is accessible, report the exact access
blocker and state that the import is metadata-only.

For other blockers, identify the exact gate: Zotero missing, local API disabled,
port closed, connector unavailable, no matching item, write not authorized, or
write not confirmed.
