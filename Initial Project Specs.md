# PGS Cutlist Database — Full Spec
**Status:** Ready for Claude Code implementation  
**Date:** 2026-04-23

---

## Project Summary

Build a searchable database by extracting structured data from PGS's archive of `.xls` cutlist files stored on a shared network drive (~6.89 GB, years of completed projects). The goal is to replace the current workflow of blindly opening files on the server — which is slow and unindexed — with a fast local search that returns file paths and context, letting the user navigate directly to the original file when needed.

The database is **personal and local** (SQLite). It is **not** a clone of the documents — it is a structured index and reference tool.

---

## Input Files

- Format: `.xls` (Excel 97-2003 binary format)
- Location: Shared network drive, one folder per job, cutlist file inside
- Size: ~6.89 GB total; extracted text content estimated at 5–50 MB
- Parser: Python `xlrd` library (handles binary `.xls`)

---

## Sheet Filtering

### Exclude sheets matching these prefixes (case-insensitive):
- `PROTOCOL`
- `ENGINEERING CHECKLIST`
- `ASSEMBLY` ← catches "ASSEMBLY,REVEAL LOAD LIST", "ASSEMBLY (2)", etc.
- `Ass'y labels` ← catches all copies
- `PANEL STOCK LAYUP`
- `SORTED PARTS LIST`
- `MATERIAL REQ.`

### Capture all remaining sheets.

Standard sheets are named `PAGE (1)`, `PAGE (2)`, etc.  
Non-standard sheets (anything not matching `PAGE (#)` pattern) should be captured but flagged for review.

**Flag message format:**  
`"Job [job_number] – Series [series_number]: sheet '[sheet_name]' does not match standard naming — may warrant review"`

---

## Version Detection

Check cell W1:
- **Numeric value** (e.g. `1`) → **Single-sheet format** (user's template)
- **Text value or empty** → **Traditional multi-sheet format**

This determines column mapping for Notes and CNC Prog # (see Data Rows section).

---

## Title Block Extraction (Rows 1–7)

These fields are extracted once per sheet and stored with every row from that sheet.

### Core Job Info

| Field | Cell | Notes |
|---|---|---|
| Job name | E1 | Plain text |
| Job number | E2 (merged E2:E3) | Plain text |
| Series number | E4 | Plain text |
| Room | E5 | Plain text |
| VTO reference | G1:H1 (merged) | Plain text |
| Area description | P1:U1 (merged) | Plain text |
| Version number | W1 | Numeric; single-sheet format only |

### Authoring Block

| Field | Cell |
|---|---|
| Cutlist date | G3 |
| Cutlist by | H3 |
| Checked date | G4 |
| Checked by | H4 |
| In Works date | G5 |
| In Works by | H5 |

### FSC / FR Flags

Both cells contain a Wingdings "P" character when flagged, empty otherwise.

| Field | Cell |
|---|---|
| F.R. flag | M2 |
| FSC flag | M4 |

Store as boolean: presence of any value in cell = True.

### Edgeband Block

Capture the entire block **N3:R6** as a single raw string (label + value pairs together). Do not attempt to parse individual entries — layout varies too much.

### Machining Block

**Single-sheet format:** 8 cells — S3, S4, S5, S6, V3, V4, V5, V6  
**Traditional format:** 8 merged cells — S3:U3, S4:U4, S5:U5, S6:U6, V3:W3, V4:W4, V5:W5, V6:W6

Capture all 8 as an array of strings (empty strings for unused slots).

---

## Data Row Extraction

### Row Range

- **Start:** Row 8 (first data row, consistent across all formats)
- **End:** Determined by the sheet's print area (`Sheet.PageSetup.PrintArea`)
  - Parse the print area range string to get the last row number
  - **Fallback** if print area is not set: read until the last non-empty row
  - If fallback is used: flag the sheet for review

### Column Map — Single-sheet format

| Col | Field |
|---|---|
| A | VTO# |
| B | FL-RM# |
| C | PART# category |
| D | PART# component |
| E | Description |
| F | W (width) |
| G | L (length) |
| H | T (thickness) |
| I:L | Material (merged) |
| M | QTY |
| N | Edge — Left |
| O | Edge — Right |
| P | Edge — Top |
| Q | Edge — Bottom |
| R | Edge — Front |
| S | Edge — Back |
| T | CNC flag |
| U:V | Notes (merged) |
| W | CNC Prog # |

### Column Map — Traditional multi-sheet format

Same as above through column T, then:

| Col | Field |
|---|---|
| U:W | Notes (merged) |
| X | CNC Prog # |

### Merged Cell Handling

Many data rows contain merged cells (especially in Description and Notes columns, and callout/assembly header rows). Extract the value from the first cell of any merged range. Do not skip rows with merged cells — they are valid data (often assembly headers or visual callout rows).

### Empty and Partial Rows

Capture all rows within the print area range, including rows that appear empty or are callout rows. Do not attempt to classify row types. A row with empty dimension/QTY cells and a description value is valid — the user can recognize callout rows visually when reviewing results.

---

## Database Schema (SQLite)

### Table: `projects`

One row per imported file.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| file_path | TEXT | Full network path to source .xls file |
| job_name | TEXT | From E1 |
| job_number | TEXT | From E2:E3 |
| series_number | TEXT | From E4 |
| room | TEXT | From E5 |
| area | TEXT | From P1:U1 |
| vto_reference | TEXT | From G1:H1 |
| is_fsc | BOOLEAN | From M4 |
| is_fr | BOOLEAN | From M2 |
| cutlist_by | TEXT | From H3 |
| cutlist_date | TEXT | From G3 |
| checked_by | TEXT | From H4 |
| checked_date | TEXT | From G4 |
| format_type | TEXT | 'single-sheet' or 'traditional' |
| import_date | TEXT | ISO timestamp |
| has_flags | BOOLEAN | True if any review flags were raised |

### Table: `sheets`

One row per captured sheet.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| project_id | INTEGER FK | → projects.id |
| sheet_name | TEXT | |
| is_standard | BOOLEAN | True if matches PAGE (#) pattern |
| print_area | TEXT | Raw print area string from PageSetup |
| print_area_fallback | BOOLEAN | True if print area was not set |
| edgeband_block | TEXT | Raw capture of N3:R6 |
| machining_block | TEXT | JSON array of 8 strings |
| row_count | INTEGER | Number of data rows captured |

### Table: `rows`

One row per data row per sheet.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| sheet_id | INTEGER FK | → sheets.id |
| row_number | INTEGER | Source row number in original sheet |
| vto | TEXT | |
| fl_rm | TEXT | |
| part_category | TEXT | |
| part_component | TEXT | |
| description | TEXT | |
| width | TEXT | Stored as text — may contain fractions/mixed formats |
| length | TEXT | |
| thickness | TEXT | |
| material | TEXT | |
| qty | TEXT | |
| edge_left | TEXT | |
| edge_right | TEXT | |
| edge_top | TEXT | |
| edge_bottom | TEXT | |
| edge_front | TEXT | |
| edge_back | TEXT | |
| cnc_flag | TEXT | |
| notes | TEXT | |
| cnc_prog | TEXT | |

### Table: `flags`

One row per flag raised during import.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| project_id | INTEGER FK | |
| sheet_id | INTEGER FK | Nullable |
| flag_type | TEXT | 'non-standard-sheet', 'no-print-area', 'import-review' |
| message | TEXT | Human-readable description |
| resolved | BOOLEAN | Default false |

---

## Import Modes

### 1. Bulk import
Scans a folder (or folder tree) and imports all `.xls` files found, applying all filtering and flagging rules. Skips files already in the database (match on file path). Reports summary on completion: files processed, rows imported, flags raised.

### 2. Single-file preview import
User points the tool at one specific `.xls` file. Tool displays:
- Title block values it would extract
- Sheet names it would capture vs. skip
- Row count per sheet
- Any flags that would be raised

User confirms (thumbs up) or cancels (thumbs down). Confirmed previews write to the database. Cancelled previews write nothing.

---

## Project Registry / Table of Contents

A queryable view (or separate UI) showing all imported projects with:
- Job name, job number, series, room
- File path
- Import date
- Sheet count
- Flag count
- FSC / FR status

Supports:
- **Remove project:** Deletes all rows, sheets, and flags for a project_id in a single transaction
- **Mark flag resolved:** Updates `flags.resolved = true` for a given flag id
- **Re-import:** Remove + re-run import on same file path

---

## Search Behavior

**Fast, accurate search is the core purpose of this tool.** All text search must use SQLite FTS5 — not `LIKE` scanning. This is a hard requirement, not an optional optimization.

### FTS5 Virtual Table

At database creation, a companion FTS5 virtual table must be created alongside `rows`:

```sql
CREATE VIRTUAL TABLE rows_fts USING fts5(
    description,
    material,
    notes,
    part_category,
    part_component,
    cnc_prog,
    content='rows',
    content_rowid='id'
);
```

This table must be kept in sync with `rows` via triggers on INSERT, UPDATE, and DELETE. Every row written to `rows` must also be indexed in `rows_fts` at the same time.

### Why FTS5 (not LIKE)

- `LIKE '%curved back%'` scans every row sequentially — gets slow as the database grows
- FTS5 pre-indexes every word, making search near-instant regardless of database size
- FTS5 supports multi-word queries, partial matching, and relevance ranking — `LIKE` does not
- Since the entire point of this tool is finding things quickly across thousands of cutlist rows, `LIKE`-based search would defeat the purpose

### Search Query Behavior

- Multi-word searches find rows containing all terms (across any indexed column)
- Results ranked by relevance using FTS5's built-in `bm25()` scoring
- Search is case-insensitive by default

### Result Format Per Match

- File path to source `.xls` (navigable)
- Job name + job number
- Sheet name
- Source row number in original file
- Matched column(s) and value(s)
- 1–2 surrounding rows from the same sheet for context

---

## Edge Cases & Flags Summary

| Situation | Behavior |
|---|---|
| Sheet name doesn't match `PAGE (#)` | Capture + raise `non-standard-sheet` flag |
| Print area not set | Capture to last non-empty row + raise `no-print-area` flag |
| File already in database | Skip (no duplicate import) |
| Merged cell in data row | Extract value from first cell of merged range |
| Empty row within print area | Capture as-is (do not skip) |
| W1 ambiguous (not clearly numeric or text) | Default to traditional format + raise flag |
