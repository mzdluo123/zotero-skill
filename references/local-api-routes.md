# Zotero local API and connector routes

Base URL: `http://127.0.0.1:23119`.

## Desktop local API

The local API is under `/api/`. It implements Zotero Web API v3 for the local logged-in desktop user.

Important constraints:

- Use `/api/users/0/...` for the local user by default.
- Local API reads do not require authentication. In Zotero 10+, writes require a user-approved local API key from `POST /api/local/authorize`.
- Atom output is not supported locally.
- Attachment file URLs and full text can expose local file paths or document text; only retrieve them when the user asks.
- Every Zotero 10+ write must include the instance's `Zotero-Server-ID`; updates and deletes must also include the current object version.

Safe read routes:

```text
/api/
/api/schema
/api/itemTypes
/api/itemFields
/api/itemTypeFields?itemType=journalArticle
/api/itemTypeCreatorTypes?itemType=journalArticle
/api/creatorFields
/api/users/0/collections
/api/users/0/collections/top
/api/users/0/items
/api/users/0/items/top
/api/users/0/items/trash
/api/users/0/items/<itemKey>
/api/users/0/items/<itemKey>/children
/api/users/0/items?format=keys
/api/users/0/items?format=versions
/api/users/0/items?format=bibtex
/api/users/0/items?include=data,citation&style=apa
/api/users/0/items?q=<query>
/api/users/0/tags
/api/users/0/searches
/api/users/0/searches/<searchKey>/items
/api/users/0/groups
/api/users/0/fulltext?since=0
/api/users/0/items/<attachmentKey>/fulltext
/api/users/0/items/<attachmentKey>/file/view/url
```

Write routes supported by Zotero 10+:

```text
POST   /api/local/authorize
POST   /api/users/0/items
PATCH  /api/users/0/items/<itemKey>
DELETE /api/users/0/items/<itemKey>
```

Create notes with `itemType: note` and HTML in `note`. Omit `parentItem` for a standalone note or set it to a parent item key for a child note. Use `PATCH` with `If-Unmodified-Since-Version` for updates and `DELETE` with the same precondition for deletion. The helper stores approved local keys per `Zotero-Server-ID` in a mode-`0600` user config file.

Native PDF highlights are child items with `itemType: annotation`, `annotationType: highlight`, the stored PDF attachment key in `parentItem`, and the exact quote/comment in `annotationText`/`annotationComment`. `annotationPosition` is a JSON string containing a zero-based `pageIndex` and PDF rectangles in `[left, bottom, right, top]` order. The helper uses PyMuPDF to resolve exact text to coordinates and reads the created annotation back for verification.

## Connector server

The Zotero Connector server shares port `23119` and is used for BibTeX/RIS imports. Prefer the authorized Zotero 10+ local API for note and general item writes.

Useful routes:

```text
GET  /connector/ping
POST /connector/ping
POST /connector/getSelectedCollection
POST /connector/import?session=<uuid>
POST /connector/saveItems
POST /connector/saveSnapshot
```

Use `/connector/import` for importing BibTeX/RIS strings into the currently selected Zotero library or collection. Treat connector writes as Zotero library modifications and confirm with the user before doing them.
