# Read, search, and cite

Use these read-only commands after `status --json` reports that the local API is
running.

## Library inventory and search

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py inventory
python3 <plugin-root>/skills/zotero/scripts/zotero.py collections
python3 <plugin-root>/skills/zotero/scripts/zotero.py tags
python3 <plugin-root>/skills/zotero/scripts/zotero.py groups
python3 <plugin-root>/skills/zotero/scripts/zotero.py search "BERT" --json
```

Inventory, collection, tag, group, search, citation, and child-item commands
read every API page automatically.

For inventory and search results, report the title, creators, year, Zotero item
key, and BibTeX key when available. Zotero item keys such as `PXW99EKT` are not
BibTeX citation keys such as `vaswani_attention_2023`; explain the distinction
when it matters.

## BibTeX and rendered citations

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py export-bibtex --out references.bib
python3 <plugin-root>/skills/zotero/scripts/zotero.py export-bibtex --item-key PXW99EKT
python3 <plugin-root>/skills/zotero/scripts/zotero.py sync-bib --out references.bib
python3 <plugin-root>/skills/zotero/scripts/zotero.py citations --style apa --json
```

For file exports, report the absolute output path and entry count.

## Draft insertion

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py cite --item-key PXW99EKT --tex paper.tex --bib references.bib --marker '<cite>'
python3 <plugin-root>/skills/zotero/scripts/zotero.py cite --query "BERT" --markdown notes.md --bib references.bib --marker '<cite>'
```

Report the edited draft, inserted citation key, and updated `.bib` path.

## Attachments and indexed full text

Only use these commands when the user requests PDFs, attachment paths, or
full-text content.

```bash
python3 <plugin-root>/skills/zotero/scripts/zotero.py children PXW99EKT --json
python3 <plugin-root>/skills/zotero/scripts/zotero.py fulltext 2JAZS9U8 --out article-fulltext.txt
python3 <plugin-root>/skills/zotero/scripts/zotero.py file-url 2JAZS9U8
```

For blockers, identify the exact gate: Zotero missing, local API disabled, port
closed, no matching item, attachment missing, or full text not indexed.
