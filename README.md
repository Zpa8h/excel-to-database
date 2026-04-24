# PGS Cutlist Database

A local search tool for indexing and querying a large archive of `.xls` cutlist files. Built for millwork detailers who need to find how a specific fabrication technique was handled in a past project — without opening hundreds of files manually on a slow network drive.

---

## What it does

Extracts structured data from PGS-format cutlist Excel files and stores it in a local SQLite database with full-text search. You can then search across thousands of rows of historical cutlist data in milliseconds, see matched rows in context, and navigate back to the original file.

**The problem it solves:** Finding a past example — say, how a curved cabinet back was detailed, or what operation code was used for a specific machining step — currently means opening job folders on the server one by one and searching through files manually. On a large shared drive, this can take 10–20 minutes with no guarantee of finding anything. This tool makes that search instant.

**What it is not:** A replacement for the original files. The database is an index and reference tool. All file paths point back to the source `.xls` files, which remain the authoritative record.

---

## Setup

**Requirements:** Python 3.10+

```bash
git clone https://github.com/Zpa8h/excel-to-database
cd excel-to-database
pip install -r requirements.txt
```

Dependencies: `xlrd`, `flask`, `click`, `pytest`

---

## Usage

### Step 1 — Prepare a local copy of your cutlist folder

**Do not point this tool at the live network drive.** Make a local copy first:

```powershell
# PowerShell — copy jobs modified since 2023
$source = "\\server\Cutlists"
$destination = "C:\Users\yourname\Projects\Filtered-Cutlists"
$cutoffDate = Get-Date "2023-01-01"

Get-ChildItem -Path $source -Directory | ForEach-Object {
    $recent = Get-ChildItem -Path $_.FullName -Recurse -File |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($recent -and $recent.LastWriteTime -ge $cutoffDate) {
        Copy-Item -Path $_.FullName -Destination $destination -Recurse -Force
        Write-Host "Copied: $($_.Name)"
    }
}
```

Once you're done with the database, you can delete the local copy. The database stores file paths but does not depend on the files being present for searching — only for re-importing.

### Step 2 — Import the cutlist files

```bash
python app.py scan "C:\Users\yourname\Projects\Filtered-Cutlists"
```

This recursively finds all `.xls` files in the folder, extracts their title block and row data, and writes everything to `cutlist.db`. Progress is printed per file. Files already in the database are skipped automatically.

Example output:
```
Found 214 .xls file(s)

[1/214] IMPORTED 2664 - WELLS FARGO\101 SERIES.xls — 312 rows (1 flag)
[2/214] IMPORTED 2591 - MORGAN STANLEY\202 SERIES.xls — 188 rows
[3/214] SKIP    2540 - BLACKROCK\301 SERIES.xls (already in database)
...

────────────────────────────────────────────────────────────
  Files found:    214
  Imported:       198
  Skipped:         14  (already in database)
  Failed:           2
  Rows imported: 41823
  Flags raised:     7
────────────────────────────────────────────────────────────
```

**Options:**
```bash
python app.py scan --help
python app.py scan "path/to/folder" --db "path/to/custom.db"
```

### Step 3 — Start the web interface

```bash
python app.py serve
```

Then open [http://localhost:5000](http://localhost:5000) in your browser.

```bash
python app.py serve --port 8080          # use a different port
python app.py serve --db custom.db       # use a specific database file
```

Press `Ctrl+C` in the terminal to stop the server.

---

## Web interface

### Search tab

Type any term into the search bar — part descriptions, materials, operation codes, notes, anything. Results are returned using SQLite FTS5 full-text search across all row columns.

Results are shown as cards, one per cluster of matches within a sheet. Matched rows are highlighted in amber; two rows of surrounding context appear above and below each cluster. If multiple hits appear within 3 rows of each other, they are grouped into a single card automatically.

Click **View in project** on any card to open the full sheet view, with the title block pinned at the top and all matched rows highlighted.

### Project registry tab

Lists every imported project with job name, series, room, sheet count, detailer initials, and import date. From here you can remove a project (deletes all associated rows and flags) or re-import it from the stored file path.

Use the **Import file** button to preview and import a single `.xls` file without running a full scan.

### Flags tab

Any issues encountered during import are logged here — non-standard sheet names, missing print areas, ambiguous version formats. Each flag shows the job and sheet it came from. Click **Resolve** to dismiss a flag once you've reviewed it.

---

## File structure

```
excel-to-database/
├── app.py              # CLI entry point (scan + serve commands)
├── parser.py           # xlrd-based .xls extractor
├── db.py               # SQLite schema, FTS5 setup, queries
├── api.py              # Flask API endpoints
├── static/
│   └── index.html      # Single-file web UI
├── inspect_xls.py      # Utility: inspect a file's raw structure
├── inspect_detail.py   # Utility: inspect title block extraction
├── test_phase1.py      # Parser tests
├── test_phase5.py      # API/integration tests
└── requirements.txt
```

---

## How the extractor works

Each `.xls` file is parsed with `xlrd`. The extractor:

1. **Detects the format** — single-sheet (user template) vs. traditional multi-sheet, based on whether cell V1 contains a number embedded in a "Version N" string or just the label "Version"
2. **Filters sheets** — skips non-data sheets (PROTOCOL, ENGINEERING CHECKLIST, ASSEMBLY..., Ass'y labels..., PANEL STOCK LAYUP, SORTED PARTS LIST, MATERIAL REQ.). Everything else is captured; non-standard sheet names (anything not matching `PAGE (#)`) are flagged for review
3. **Reads the title block** — extracts job name, number, series, room, area, VTO reference, authoring info, FSC/FR flags, edgeband notes, and machining notes from rows 1–7
4. **Determines the data range** — uses the sheet's print area (`Print_Area` named range) to find the last data row. If no print area is set, the sheet is flagged and data extraction is skipped for that sheet
5. **Reads data rows** — captures all rows from row 8 to the print area end. Multi-cell ranges (Material, Notes) are read cell-by-cell and joined with ` | `. Row type classification is not attempted — callout rows and part rows are all captured as-is
6. **Writes to database** — all extracted content is stored in SQLite and indexed in a FTS5 virtual table covering all 19 text columns

---

## Background

This tool was built to solve a specific daily friction point: searching a 6.89 GB archive of historical millwork cutlist files on a shared network drive that has no indexing. The search would require opening folders manually in File Explorer, which resets progress if the window is accidentally closed.

The design went through several rounds of specification before any code was written — covering title block structure, sheet naming conventions, print area detection as a reliable data boundary, FTS5 as a hard requirement (not an optimization), and a two-format detection strategy to handle both the traditional multi-sheet cutlist template and a consolidated single-sheet variant.

Spec documents are included in the repository (`Initial Project Specs.md`, `pgs_cutlist_ui_spec.md`) for reference.

The MVP was built with [Claude Code](https://claude.ai/code). Design and specification were developed collaboratively with Claude through an extended conversation covering the database schema, extraction logic, UI layout, and clustering algorithm for search results.

---

## Known limitations (MVP)

- Dimensions (W, L, T) are stored as raw strings. Mixed formats (fractions, inch symbols, decimal) are not normalized
- The edgeband block is captured as a raw string rather than parsed into individual label/value pairs
- Single-file preview import via the UI does not yet support drag-and-drop
- No export functionality from search results

---

## Running tests

```bash
pytest test_phase1.py   # parser unit tests
pytest test_phase5.py   # integration tests
```
