# PGS Cutlist Database — UI Spec
**Status:** Ready for implementation  
**Date:** 2026-04-24  
**Companion doc:** `pgs_cutlist_database_spec.md`

---

## Overview

A local web application served by a Python backend (Flask or FastAPI) and accessed via browser at `localhost:5000`. The user starts the server with a single terminal command and interacts entirely through the browser.

CLI is acceptable only for the initial bulk import step. Everything else — search, project management, flag review — must be accessible through the browser UI.

---

## Tech Stack

- **Backend:** Python (Flask preferred for simplicity)
- **Database:** SQLite with FTS5 (see database spec)
- **Frontend:** Single HTML file with inline CSS and JS — no build step, no framework
- **Fonts/styling:** System sans-serif, clean and minimal

---

## Layout

Three-panel tab structure at the top level:

| Tab | Purpose |
|---|---|
| Search | Query the database, browse results |
| Project registry | View all imported projects, manage imports |
| Flags | Review and resolve import issues |

The active tab is indicated by a bottom border on the tab label. Tab switching does not reload the page — JS handles view toggling.

---

## Tab 1: Search

### Search bar
- Full-width text input at the top of the panel
- "Search" button to the right
- Submits on Enter or button click
- Input persists between searches (does not clear on submit)

### Filters (below search bar)
A row of toggleable chips for quick filtering:
- FSC only
- Flagged projects
- Filter by detailer initials (populated dynamically from database)
- Date range (e.g. "2023+", "2024+") — simple year cutoff selector

Chips toggle on/off. Active chips have a distinct background color. Multiple chips can be active simultaneously (AND logic).

### Results metadata
A single line below filters:
`N matches across N projects`
Updates with each search.

### Result cards

Each card represents a cluster of matched rows from a single sheet within a single project.

**Clustering rule:** If multiple matched rows are within 3 rows of each other, they are combined into a single card. If matches are more than 3 rows apart, they become separate cards. Example: hits on rows 30, 32, 34 → one card. Hit on row 40 → separate card.

**Card header:**
- Job name and number (bold)
- Sheet name badge
- FSC badge (if applicable)
- Review badge (if sheet is flagged)
- File path in monospace, subdued color, below the job name
- "View in project" button — right-aligned, opens project view for this file

**Card body — tabular row display:**

A horizontally scrollable table matching the cutlist column structure. Column headers are shown once per card. Columns in order:

| Header | Field | Notes |
|---|---|---|
| (row #) | Row number | Monospace, subdued — not a data column |
| VTO# | vto | |
| FL-RM# | fl_rm | |
| Cat. | part_category | |
| Comp. | part_component | |
| Description | description | Widest column |
| W | width | |
| L | length | |
| T | thickness | |
| Material | material | |
| Qty | qty | |
| L | edge_left | Edge columns grouped |
| R | edge_right | |
| T | edge_top | |
| B | edge_bottom | |
| F | edge_front | |
| Bk | edge_back | |
| CNC | cnc_flag | |
| Notes | notes | |

**Row types within a card:**

- **Context rows** (2 above and 2 below the matched cluster): rendered in subdued/tertiary text color, no background
- **Matched rows**: amber background highlight; search term highlighted in a darker amber within the Description and Notes cells

**Search term highlighting:** The matching term(s) are wrapped in a mark-style span with amber background within cell text. Applied to all text columns, not just Description.

---

## Tab 2: Project registry

### Toolbar
- Filter input (text) — filters the table client-side by job name or number
- "Import file" button — triggers single-file preview import flow (see below)

### Registry table

One row per imported project. Columns:

| Column | Content |
|---|---|
| Job | Job name (bold) + job number (subdued, monospace below) |
| Series | Series number |
| Room | Room field from title block |
| Sheets | Count of captured sheets |
| By | Cutlist by initials |
| Imported | Import date (YYYY-MM-DD) |
| Flags | Badge showing FSC and/or flag count |
| Actions | "Re-import" and "Remove" buttons |

**Remove:** Shows a confirmation prompt before deleting. Deletes all rows, sheets, and flags for that project in a single transaction.

**Re-import:** Removes existing data for the project and re-runs the import from the stored file path. Shows result summary (rows imported, flags raised).

### Single-file preview import flow

Triggered by "Import file" button:

1. File picker opens (filtered to .xls files)
2. Backend parses the file and returns a preview:
   - Title block values extracted (job name, number, series, room, FSC/FR)
   - List of sheets: which would be captured vs. skipped, row count per captured sheet
   - Any flags that would be raised
3. Preview is displayed in a modal or inline panel
4. User confirms ("Import") or cancels
5. On confirm: data writes to database, success message shown
6. On cancel: nothing is written

---

## Tab 3: Flags

### Flags list

One row per unresolved flag. Each row contains:

- Color-coded dot indicator:
  - Amber: non-standard sheet name, version ambiguous
  - Red: no print area (data rows skipped)
- Flag message (human-readable, as generated during import)
- Job name and flag type (subdued, below message)
- "Resolve" button — marks the flag as resolved and removes it from this view

Resolved flags are hidden by default. A toggle ("Show resolved") can reveal them in a subdued style.

---

## Project view (click-through from search)

Opened when user clicks "View in project" on a result card. Replaces the search panel (or slides in as a full-panel view). A "Back to results" button at the top returns to search without losing the query or results.

### Header bar
- Back button (left)
- Job name, series, sheet name (center)
- FSC badge if applicable (right)

### Title block strip (sticky)
A persistent block below the header showing key fields from the title block in a compact grid:

- Job name
- Job number
- Series
- Room
- Area description
- VTO reference
- Cutlist by + date
- Checked by + date

This block does not scroll away — it stays visible as the user scrolls through rows.

### Sheet selector
If the project has multiple captured sheets, a tab row or dropdown allows switching between sheets without leaving the project view.

Label: `PAGE (1) of 4 · Rows 8–52 · N matches highlighted`

### Row table (scrollable)

Full table of all data rows for the selected sheet, using the same column structure as search result cards. Both the title block strip and the column header row are sticky — they remain visible during vertical scroll.

**Matched rows** (the rows that triggered this result card) are highlighted:
- Amber background on the full row
- Amber left border (3px) for easy scanning while scrolling

Non-matched rows render normally.

The table does not truncate rows — all rows from the print area are shown. The user scrolls to see full context.

---

## General UI behavior

- No page reloads for tab switching or project view navigation — all handled in JS
- Horizontal scroll on all cutlist tables — columns are wider than the viewport; tables scroll independently within their container
- Empty states: each tab shows a helpful message when empty (no results, no projects, no flags)
- Loading states: search queries and imports show a simple loading indicator while the backend responds
- Error states: if the backend returns an error, display it inline near the relevant action (not as a browser alert)
- No authentication — this is a single-user local tool

---

## API endpoints (backend)

The frontend communicates with the Flask backend via these endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | /search?q=...&filters=... | Full-text search, returns clustered results |
| GET | /projects | List all imported projects |
| POST | /projects/preview | Preview a file import (body: file path) |
| POST | /projects/import | Confirm and write a previewed import |
| DELETE | /projects/<id> | Remove a project and all its data |
| POST | /projects/<id>/reimport | Re-import a project from stored path |
| GET | /projects/<id>/sheet/<sheet_id> | Get all rows for a sheet (project view) |
| GET | /flags | List all flags |
| POST | /flags/<id>/resolve | Mark a flag resolved |

### Search response structure

The backend handles clustering before returning results. Each result object contains:

```json
{
  "job_name": "Wells Fargo 5th and 6th Floor",
  "job_number": "2664",
  "series": "101",
  "file_path": "~/Cutlists/...",
  "sheet_name": "PAGE (3)",
  "is_fsc": true,
  "has_flags": false,
  "rows": [
    {
      "row_number": 28,
      "is_match": false,
      "is_context": true,
      "vto": "", "fl_rm": "204", "part_category": "CA-04"
    },
    {
      "row_number": 30,
      "is_match": true,
      "is_context": false,
      "matched_terms": ["curved back"],
      "vto": "V-12"
    }
  ]
}
```

Clustering logic lives in the backend, not the frontend. The frontend renders whatever row array it receives.

---

## Clustering algorithm (backend)

Given a list of matched row numbers for a sheet:

1. Sort matched rows ascending
2. Group consecutive matches where gap between any two adjacent matches is 3 or fewer
3. For each group, define the display window as (first_match_row - 2) to (last_match_row + 2), clamped to the sheet's valid row range
4. Fetch all rows in that window from the database
5. Tag each row as is_match: true or is_context: true
6. Return one result object per group

---

## Edge cases

- If a context row falls outside the sheet's valid row range (e.g. match is on row 8, context would be rows 6-7 which don't exist): clamp silently, do not error
- If two clusters' windows would overlap after expansion, merge them into one card
- If a sheet has no rows (no-print-area flag): do not include it in search results; it may still appear in project view with a "no data — print area was not set" message
