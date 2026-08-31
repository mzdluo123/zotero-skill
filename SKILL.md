---
name: Zotero
description: Use Zotero Desktop from Codex to enable/probe the local API, search a local Zotero library, list items/collections/tags, read and write notes with user-authorized local API access, export BibTeX, insert citation keys into LaTeX or Markdown drafts, read indexed full text when requested, and import BibTeX/RIS records into Zotero through the connector server. Use when the user mentions Zotero, notes, citations, references.bib, BibTeX export, local Zotero API, localhost:23119, or adding citations from a Zotero library.
---

# Zotero

Use this skill to operate a user's local Zotero Desktop library.

Core helper:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py <command>
```

Resolve `<plugin-root>` by going two directories up from this `SKILL.md`.
Run `python3 <plugin-root>/skills/zotero/scripts/zotero.py <command> --help`
when exact options are needed. Most commands are stdlib-only. `annotate`
requires PyMuPDF from `requirements.txt`.

## Required workflow

1. Start with `status --json`. Do not rediscover preferences, ports, or profile
   paths manually unless the helper fails.
2. If `local_api_enabled_pref` is false and the user asked to operate Zotero,
   run `enable --restart`.
3. Retrieve attachment file URLs, local paths, or full text only when the user
   asks for that content.
4. Treat every Zotero library write as an explicit write action. Confirm the
   exact content and destination unless the prompt already requests the write.
   Write commands still require `--yes`.
5. When importing a new article, import both its bibliographic record and an
   available legitimate full-text PDF. Store the PDF as a child attachment of
   the parent item. If no legitimate PDF is accessible, import the metadata and
   report the exact access blocker.

Check readiness:

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py status --json
```

## Task references

- For inventory, search, full text, BibTeX, citations, or draft insertion, read
  `references/read-and-cite.md`.
- For authorization, notes, PDF annotations, or BibTeX/RIS imports, read
  `references/write-and-import.md`.
- For endpoint behavior beyond helper commands, read
  `references/local-api-routes.md`.

Read only the references required for the current task.
