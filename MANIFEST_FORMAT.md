# Black Land Project — Change Manifest Format Specification

*Version 1.0 — 2026-03-30*

---

## Overview

A change manifest is a JSON document that describes all updates to the six Black Land Project tracking files resulting from the analysis of one or more new deed/instrument documents. The manifest is produced by an AI analyst and consumed by `apply_manifest.py` to apply changes automatically.

---

## JSON Structure

```json
{
  "manifest_version": "1.0",
  "batch_id": "YYYY-MM-DD_batch_NN",
  "date": "YYYY-MM-DD",
  "documents_analyzed": [
    "filename_as_provided.pdf"
  ],
  "batch_summary": "One-paragraph plain English summary of what was found and what changed.",
  "files": {
    "01_FAMILY_ENTITY_STRUCTURE.md": {
      "changed": true,
      "timestamp_summary": "Short description of changes for this file",
      "operations": [ ... ]
    },
    "02_PROPERTY_INVENTORY.md": {
      "changed": false,
      "timestamp_summary": null,
      "operations": []
    }
  }
}
```

All six files MUST appear in the `files` object, even if unchanged (`changed: false`, empty operations array).

---

## Operations

There are three operation types: `replace`, `insert_after`, and `insert_before`.

### `replace`

Find exact text in the file and substitute it. The `find` string MUST appear exactly once in the file.

```json
{
  "action": "replace",
  "description": "Human-readable explanation of what this change does",
  "find": "exact text to locate (must be unique in file)",
  "replace_with": "replacement text"
}
```

**Rules:**
- `find` must match the file content byte-for-byte (including whitespace, newlines, punctuation).
- If `find` appears zero times or more than once, the script will reject the operation and log an error.
- Multi-line strings: use `\n` for newlines in JSON.
- To delete text, set `replace_with` to `""`.

### `insert_after`

Insert new content on the line(s) immediately following an anchor string. The anchor MUST appear exactly once.

```json
{
  "action": "insert_after",
  "description": "Human-readable explanation",
  "anchor": "exact text to locate (must be unique in file)",
  "content": "text to insert after the anchor line"
}
```

**Rules:**
- The anchor is used for location only — it is NOT modified.
- Content is inserted starting on the next line after the line containing the anchor.
- Use `\n` for multi-line insertions.

### `insert_before`

Insert new content on the line(s) immediately before an anchor string. The anchor MUST appear exactly once.

```json
{
  "action": "insert_before",
  "description": "Human-readable explanation",
  "anchor": "exact text to locate (must be unique in file)",
  "content": "text to insert before the anchor line"
}
```

---

## Timestamp Updates

Each file's first line is a timestamp in this format:

```
*Last updated: YYYY-MM-DD — one-line summary of latest batch.*
```

The script handles timestamp updates automatically using the `date` and `timestamp_summary` fields from the manifest. No explicit `replace` operation is needed for the timestamp line.

**If a file has `changed: false`**, the timestamp is not touched.

---

## Anchor Selection Guidelines

Good anchors are unique strings that won't change between sessions:

- **Deed entries**: Use the deed number bracket, e.g., `[121]` combined with enough surrounding text to be unique: `| [121] | J. H. Bounds → J. V. Bounds |`
- **Issues**: Use the issue header, e.g., `**ISSUE-43: Master Pull List`
- **Table rows**: Use enough of the row to be unique — at minimum the CAD ID or deed number column.
- **Section headers**: Use the full markdown header, e.g., `### Wm. Richie / Ritchie A-527 Group`
- **Avoid**: Short strings that could match elsewhere. When in doubt, include more context.

---

## Operation Ordering

Operations are applied in array order, top to bottom. Each operation sees the file as modified by all prior operations. **This means:**

1. If operation 2 depends on text inserted by operation 1, that's fine — operation 2 will see the inserted text.
2. If operation 2's `find` or `anchor` string was modified by operation 1, operation 2 will fail — avoid this.
3. Put timestamp-independent operations first. The script applies the timestamp update last.

**Best practice:** Order operations from bottom of file to top. This way, line insertions don't shift the position of anchors that haven't been processed yet.

---

## Validation Checklist (for the AI analyst)

Before emitting the manifest, verify:

- [ ] Every `find` and `anchor` string is unique in its target file
- [ ] Every `find` string matches the CURRENT file content exactly (copy from the file, don't retype)
- [ ] Multi-line `find` strings preserve exact whitespace and line breaks
- [ ] New deed entries use the correct Phase section
- [ ] Cross-county duplicate deeds are handled in both the FC and LC sections
- [ ] New issues get the next sequential ISSUE number
- [ ] All six files appear in the manifest
- [ ] `batch_summary` accurately describes what was found
- [ ] No `find` or `anchor` from one operation is altered by a prior operation in the same file

---

## Example: Adding a New Deed Entry

```json
{
  "action": "insert_after",
  "description": "Add deed [126] entry to Phase 1 section, after deed [124]",
  "anchor": "| [124] | J. H. Bounds → T. W. Bounds | Limestone | IDX |",
  "content": "| [126] | New Grantor → New Grantee | Limestone | ✓ | Vol. X, Pg. Y | — | date | date | clerk details |"
}
```

## Example: Updating an Existing Issue

```json
{
  "action": "replace",
  "description": "Update ISSUE-03 status from OPEN to RESOLVED",
  "find": "- **Status**: OPEN (partially resolved)",
  "replace_with": "- **Status**: RESOLVED"
}
```

Note: The `find` string must be unique. If multiple issues have `- **Status**: OPEN`, include more context (e.g., the full issue header line above it as part of a multi-line find).
