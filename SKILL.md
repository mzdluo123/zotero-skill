---
name: Zotero
description: Use Zotero Desktop from Codex to enable/probe the local API, search a local Zotero library, list items/collections/tags, read and write notes with user-authorized local API access, export BibTeX, insert citation keys into LaTeX or Markdown drafts, read indexed full text when requested, and import BibTeX/RIS records into Zotero through the connector server. Use when the user mentions Zotero, notes, citations, references.bib, BibTeX export, local Zotero API, localhost:23119, or adding citations from a Zotero library.
---

# Zotero

Use this skill to operate a user's local Zotero Desktop library from Codex.

Core helper:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py <command>
```

Resolve `<plugin-root>` by going two directories up from this `SKILL.md` file.

The helper follows the repo convention of running plugin Python helpers with `python3` / `#!/usr/bin/env python3`. Most commands are stdlib-only. Exact PDF highlighting requires PyMuPDF from `requirements.txt`; install it with `python3 -m pip install -r <skill-root>/requirements.txt` when `annotate` reports that it is missing.

## Fast starts

Check readiness in one command:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py status --json
```

Enable the local API and restart Zotero if needed:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py enable --restart
```

Search and export citation data:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py search "transformer" --json
python3 <plugin-root>/skills/zotero/scripts/zotero.py export-bibtex --out references.bib
```

Insert a citation from Zotero into a draft and keep `references.bib` in sync:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py cite --query "Attention Is All You Need" --tex paper.tex --bib references.bib --marker '<cite>'
```

## Workflow

1. Start with `status --json`. Do not rediscover prefs, ports, or profile paths manually unless the helper fails.
2. If `local_api_enabled_pref` is false, run `enable --restart` when the user asked you to operate Zotero. This updates Zotero's local preference and restarts Zotero so port `23119` comes up.
3. Use read-only local API commands for normal work:
   - `inventory` for item/collection/tag summaries.
   - `search <query>` for papers/items.
   - `export-bibtex` or `sync-bib` for `.bib` files.
   - `cite` for inserting a citation into a draft.
4. Only retrieve attachment file URLs or full text when the user asks for PDFs, attachment paths, or full-text content. Importing a new article is the exception: import its PDF together with the bibliographic record as required by step 5.
5. When importing a new article, import both the bibliographic record and an available full-text PDF. Prefer the publisher's official PDF, then an author-hosted or preprint PDF. Store the PDF as a child attachment of the imported parent item; do not leave it as a standalone attachment or URL-only attachment. After import, use `children <parent-key> --json` and `file-url <attachment-key>` to verify the parent-child relation and that Zotero has a local stored file. If no legitimate PDF is accessible, import the metadata, report the exact PDF access blocker, and do not substitute an unrelated file.
6. Treat Zotero library writes as explicit write actions. Before `annotate`, `create-note`, `update-note`, `delete-note`, `import-bibtex`, or `import-ris`, confirm the exact content and destination unless the user's prompt already explicitly requested the write. The helper still requires `--yes`.

## Common commands

```bash
# Readiness and route map
python3 <plugin-root>/skills/zotero/scripts/zotero.py status --json
python3 <plugin-root>/skills/zotero/scripts/zotero.py probe --json

# Library inventory
python3 <plugin-root>/skills/zotero/scripts/zotero.py inventory
python3 <plugin-root>/skills/zotero/scripts/zotero.py collections
python3 <plugin-root>/skills/zotero/scripts/zotero.py tags

# Search and export
python3 <plugin-root>/skills/zotero/scripts/zotero.py search "BERT"
python3 <plugin-root>/skills/zotero/scripts/zotero.py export-bibtex --out references.bib
python3 <plugin-root>/skills/zotero/scripts/zotero.py export-bibtex --item-key PXW99EKT
python3 <plugin-root>/skills/zotero/scripts/zotero.py citations --style apa --json

# Draft editing
python3 <plugin-root>/skills/zotero/scripts/zotero.py cite --item-key PXW99EKT --tex paper.tex --bib references.bib --marker '<cite>'
python3 <plugin-root>/skills/zotero/scripts/zotero.py cite --query "BERT" --markdown notes.md --bib references.bib --marker '<cite>'

# Attachments and full text; use only on request
python3 <plugin-root>/skills/zotero/scripts/zotero.py children PXW99EKT --json
python3 <plugin-root>/skills/zotero/scripts/zotero.py fulltext 2JAZS9U8 --out attention-fulltext.txt
python3 <plugin-root>/skills/zotero/scripts/zotero.py file-url 2JAZS9U8

# Notes; Zotero displays an authorization dialog on the first local API write
python3 <plugin-root>/skills/zotero/scripts/zotero.py authorize-writes
python3 <plugin-root>/skills/zotero/scripts/zotero.py create-note --text 'Research note' --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py create-note --parent-item PXW99EKT --file note.html --file-format html --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py update-note NOTEKEY --text 'Revised note' --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py delete-note NOTEKEY --yes

# Exact native PDF highlight plus attached comment
python3 <plugin-root>/skills/zotero/scripts/zotero.py annotate 2JAZS9U8 --quote 'Attention functions can be described as mapping a query' --comment '注意力机制的定义起点。' --color yellow --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py annotate 2JAZS9U8 --quote-file exact-quote.txt --comment-file chinese-comment.txt --page 2 --yes

# Writes to Zotero; confirm first unless explicitly requested
python3 <plugin-root>/skills/zotero/scripts/zotero.py selected-target --json
python3 <plugin-root>/skills/zotero/scripts/zotero.py import-bibtex --file new-reference.bib --yes
python3 <plugin-root>/skills/zotero/scripts/zotero.py import-ris --file new-reference.ris --yes

# A new-article import is complete only after its PDF is stored as a child attachment
python3 <plugin-root>/skills/zotero/scripts/zotero.py children PARENTKEY --json
python3 <plugin-root>/skills/zotero/scripts/zotero.py file-url ATTACHMENTKEY
```

## Output standards

- For inventory/search, return title, creators, year, Zotero item key, and BibTeX key when available.
- Explain the two-key distinction when relevant: Zotero item keys like `PXW99EKT` are not the same as exported BibTeX keys like `vaswani_attention_2023`.
- For `.bib` export, return the absolute output path and entry count.
- For draft citation insertion, report the edited file, inserted citation key, and updated `.bib` path.
- For new article imports, report the parent item key, PDF attachment key, PDF source, and successful local `file-url` verification. Metadata-only import is incomplete when a legitimate PDF is available.
- For note writes, report the note item key, parent item key when applicable, and resulting local version when available.
- Zotero note bodies are HTML. Use `--text` for escaped plain text or `--html`/`--file-format html` only for trusted HTML.
- For PDF annotations, report the annotation key, PDF attachment key, physical page index, displayed page label, color, and resolved rectangles.
- `annotate` accepts only stored PDF attachments, requires one unique exact quote, and refuses ambiguous matches. `--page` is a 1-based physical PDF page used for disambiguation.
- For blockers, name the exact gate: Zotero app missing, local API disabled, port closed, connector unavailable, no matching item, or write not confirmed.

## Route details

Read `references/local-api-routes.md` only when you need endpoint details beyond the helper commands.
