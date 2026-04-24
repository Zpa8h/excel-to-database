# PGS Cutlist Database — Project Documentation

## Project Overview

### Problem
PGS has a large archive of `.xls` cutlist files (~6.89 GB) on a shared network drive. Finding specific parts, materials, or specifications requires manually opening files one-by-one, which is slow and unindexed. There is no way to search across all cutlists at once.

### Solution
Built a local searchable database that:
1. Extracts and indexes structured cutlist data from Excel files
2. Provides fast full-text search across thousands of rows
3. Replaces blind file browsing with instant, relevance-ranked results
4. Displays results with file paths and surrounding context for easy reference back to source files

### Key Features
- ✅ **Fast search** — FTS5 full-text indexing (avg 3.5ms per query)
- ✅ **No network dependency** — User makes local copy, tool never touches network
- ✅ **Web UI** — Single-page app, no build step, runs at localhost:5000
- ✅ **CLI import** — Bulk import all `.xls` files from a folder
- ✅ **Deduplication** — Skips files already in database
- ✅ **Result clustering** — Groups consecutive matches with context rows
- ✅ **Complete metadata** — Preserves all 19 columns + job info + flags

---

## Architecture

```
User (Windows/Mac/Linux)
    ↓
    ├─ CLI: python app.py scan /path/to/local/cutlists
    │         ↓
    │         Parse .xls files (xlrd)
    │         Extract title blocks, sheets, rows
    │         Insert into SQLite + FTS5 index
    │         ↓
    │         cutlist.db (local SQLite database)
    │
    └─ Web UI: python app.py serve
               ↓
               Flask REST API (localhost:5000)
               ├─ /api/search?q=curved
               ├─ /api/projects
               ├─ /api/flags
               └─ /api/projects/{id}/sheet/{sheet_id}
               ↓
               Browser (http://localhost:5000)
               ├─ Search tab
               ├─ Project Registry
               └─ Flags tab
```

---

## Installation & Usage

### Prerequisites
- Python 3.8+
- Windows / Mac / Linux

### Setup

```bash
# 1. Clone repo
git clone <repo> && cd excel-to-database

# 2. Install dependencies
python -m pip install -r requirements.txt

# 3. Copy cutlists from network to local folder
# (User manually copies via File Explorer or robocopy)
# Example: C:\Users\YourName\Cutlists

# 4. Import files into database
python app.py scan C:\Users\YourName\Cutlists

# 5. Start web server
python app.py serve

# 6. Open browser
# Visit: http://localhost:5000
```

### File Paths
- **Database**: `cutlist.db` (created in project directory)
- **Static files**: `static/index.html` (single-page app)
- **Config**: None — all settings in code

---

## File Structure

```
excel-to-database/
├── Initial Project Specs.md      # Data extraction specification
├── pgs_cutlist_ui_spec.md        # UI/UX specification
├── CLAUDE.md                     # This file
├── requirements.txt              # Python dependencies
├── app.py                        # Flask app + CLI entry point
├── db.py                         # Database schema and operations
├── parser.py                     # xlrd Excel parser
├── api.py                        # REST API endpoints
├── static/
│   └── index.html               # Single-page web UI (30KB, no build step)
├── tests/
│   ├── test_phase1.py           # Parser + DB tests
│   ├── test_phase5.py           # Integration tests (9 test suites)
│   └── inspect_*.py             # Diagnostic tools
├── Phase1-Sample-Local/         # Sample cutlist files (for testing)
└── cutlist.db                   # SQLite database (created after first import)
```

---

## How It Works

### 1. Data Extraction (parser.py)

**Input**: `.xls` file (Excel 97-2003 binary format)

**Process**:
- Detect format via cell V1 ("Version 1" = single-sheet, "Version" = traditional)
- Extract title block (rows 1-7): job name, number, series, room, dates, flags
- Filter sheets: exclude PROTOCOL, ASSEMBLY, PANEL STOCK LAYUP, etc.
- Flag non-standard sheet names (not matching PAGE (#) pattern)
- Extract data rows (8 onwards) up to print area boundary
- Join merged cells with `|` delimiter in data rows
- Convert Excel date serials to ISO format

**Output**: Dict with {title_block, sheets, rows, flags}

### 2. Database (db.py)

**Tables**:

| Table | Purpose |
|-------|---------|
| `projects` | One row per imported .xls file |
| `sheets` | One row per captured sheet |
| `rows` | One row per cutlist data row (19 columns) |
| `rows_fts` | FTS5 virtual table (all 19 columns indexed) |
| `flags` | Import issues (non-standard sheet, no print area) |

**Foreign Keys**:
- sheets → projects (cascade delete)
- rows → sheets (cascade delete)
- flags → projects (cascade delete)

**Triggers**:
- INSERT/UPDATE/DELETE on `rows` → auto-sync `rows_fts`

### 3. API Endpoints (api.py)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/search?q=curved` | GET | FTS5 search with clustering, context rows |
| `/api/projects` | GET | List all imported projects |
| `/api/projects/preview` | POST | Parse file without importing |
| `/api/projects/import` | POST | Import single file |
| `/api/projects/{id}` | DELETE | Remove project (cascading) |
| `/api/projects/{id}/reimport` | POST | Delete + re-import |
| `/api/projects/{id}/sheet/{sheet_id}` | GET | Full sheet view |
| `/api/flags` | GET | List flags (resolved/unresolved) |
| `/api/flags/{id}/resolve` | POST | Mark flag as resolved |

**Search Clustering**: Consecutive matched rows with gap ≤ 3 are grouped; includes 2 context rows above/below each cluster.

### 4. Web UI (static/index.html)

**Three Tabs**:

1. **Search**
   - Full-width search input
   - Filters: FSC only, Flagged projects, Creator initials, Date range
   - Results: Clustered cards with job name, sheet badge, matched rows highlighted
   - Context rows in subdued text
   - "View in project" action

2. **Project Registry**
   - Table of all imported projects
   - Columns: Job name, Series, Room, Sheet count, Created date, Flags
   - Import button → preview modal
   - Actions: View, Re-import, Delete

3. **Flags**
   - Color-coded flags (amber for naming/version, red for no print area)
   - Resolve button
   - Toggle: Show resolved flags

**Project View Modal**:
- Sticky title block header
- Sheet selector dropdown
- Full cutlist table (all 19 columns, horizontally scrollable)
- Matched rows highlighted with amber background

---

## Data Extraction Details

### Column Mapping

**Single-Sheet Format** (V1 contains "Version 1"):
```
A:VTO# | B:FL-RM# | C:PART# category | D:component | E:Description
F:W | G:L | H:T | I:L:Material | M:QTY | N:Left | O:Right | P:Top
Q:Bottom | R:Front | S:Back | T:CNC flag | U:V:Notes | W:CNC Prog #
```

**Traditional Multi-Sheet Format** (V1 = "Version", W1 = version number):
```
A:VTO# | B:FL-RM# | C:PART# category | D:component | E:Description
F:W | G:L | H:T | I:L:Material | M:QTY | N:Left | O:Right | P:Top
Q:Bottom | R:Front | S:Back | T:CNC flag | U:W:Notes | X:CNC Prog #
```

### Title Block (Rows 1-7)

| Field | Cell | Notes |
|-------|------|-------|
| Job name | E1 | Plain text |
| Job number | E2 | From merged E2:E3 |
| Series number | E4 | Plain text |
| Room | E5 | Plain text |
| VTO reference | G1 | From merged G1:H1 |
| Area description | P1 | From merged P1:U1 |
| Cutlist date | G3 | Converted from Excel serial |
| Cutlist by | H3 | Creator initials |
| Checked date | G4 | Converted from Excel serial |
| Checked by | H4 | Plain text |
| In Works date | G5 | Converted from Excel serial |
| In Works by | H5 | Plain text |
| FSC flag | M4 | Boolean (presence = true) |
| FR flag | M2 | Boolean (presence = true) |
| Edgeband block | N3:R6 | Raw text (captured as-is) |
| Machining block | S3-S6, V3-V6 | 8 cells as array |
| Version number | V1 (single) / W1 (traditional) | Text/number |

### Sheet Filtering

**Excluded Prefixes** (case-insensitive):
- PROTOCOL
- ENGINEERING CHECKLIST
- ASSEMBLY (catches variants like "ASSEMBLY (2)")
- ASS'Y LABELS
- PANEL STOCK LAYUP
- SORTED PARTS LIST
- MATERIAL REQ.
- MISC INFO

**Included Sheets**:
- Any sheet NOT matching excluded prefixes
- Standard sheets: named `PAGE (1)`, `PAGE (2)`, etc.
- Non-standard sheets: captured but flagged for review

### Data Row Extraction

- **Start**: Row 8 (index 7) — always, per spec
- **End**: Determined by print area from Excel's named ranges
- **Fallback**: If no print area found, raise flag and skip data extraction (but sheet record still written)
- **Merged cells in rows**: Join all cells in range with ` | ` delimiter
- **Empty rows**: Captured as-is (don't skip)

---

## Flags

| Flag Type | Meaning | Action |
|-----------|---------|--------|
| `non-standard-sheet` | Sheet name doesn't match PAGE (#) pattern | User review needed |
| `no-print-area` | No print area defined; data rows not extracted | Check original file |
| `ambiguous-version` | V1 format unclear; defaulted to traditional | Verify format |

Flags can be marked as resolved via the UI.

---

## Database Schema Details

### projects Table
```sql
id (PK) | file_path | job_name | job_number | series_number | room | area
vto_reference | is_fsc | is_fr | cutlist_by | cutlist_date | checked_by
checked_date | format_type | import_date | has_flags
```

### sheets Table
```sql
id (PK) | project_id (FK) | sheet_name | is_standard | print_area
print_area_fallback | edgeband_block | machining_block (JSON) | row_count
```

### rows Table (19 columns)
```sql
id (PK) | sheet_id (FK) | row_number | vto | fl_rm | part_category
part_component | description | width | length | thickness | material
qty | edge_left | edge_right | edge_top | edge_bottom | edge_front
edge_back | cnc_flag | notes | cnc_prog
```

### rows_fts Table (FTS5)
Virtual table indexing all 19 columns from `rows` for full-text search.

### flags Table
```sql
id (PK) | project_id (FK) | sheet_id (FK, nullable) | flag_type
message | resolved (default: false)
```

---

## Extending the Project

### Add a New Search Filter
1. Modify `static/index.html` — add filter control in search-box div
2. Modify `api.py:search()` — add query parameter handling
3. Test via `/api/search?q=curved&your_filter=value`

### Add a New API Endpoint
1. Create function in `api.py` decorated with `@api.route('/api/newpath')`
2. Use `get_db()` to access database
3. Return `jsonify(results)` or `jsonify({'error': '...'})` with appropriate HTTP status
4. Test via Flask test client or browser

### Add a Database Column
1. Add to `rows` table schema in `db.py:create_tables()`
2. Add trigger logic to `rows_fts` if it's a searchable column
3. Update `parser.py` to extract the value
4. Update UI table columns if user-visible

### Modify Excel Extraction Logic
1. Edit `parser.py` — cell references, merged cell handling, etc.
2. Test against sample files: `python test_phase1.py`
3. Run integration tests: `python test_phase5.py`

---

## Troubleshooting

### 404 on localhost:5000
- Ensure `static/index.html` exists in the project directory
- Use absolute paths (fixed in latest version)
- Check Flask server is running (no errors in console)

### Database not found / "no such table"
- Run: `python app.py scan /path/to/cutlists` first to create and populate database
- Verify `cutlist.db` exists in project directory

### Search returns no results
- Try simpler terms ("panel" vs "wall panel assembly")
- Check import completed successfully (should show row count)
- Verify FTS5 index: `SELECT COUNT(*) FROM rows_fts` in SQLite shell

### Import hangs or is slow
- Large files (500MB+) can take several minutes
- Check disk space for `cutlist.db`
- No progress feedback yet (could be added if needed)

### Windows path issues
- Use backslashes: `C:\Users\Name\Cutlists`
- Or forward slashes: `C:/Users/Name/Cutlists`
- Python's pathlib handles both on Windows

---

## Performance Targets

| Metric | Target | Actual |
|--------|--------|--------|
| Search latency | <100ms | 3.5ms avg |
| Import speed | Reasonable | Depends on file count/size |
| FTS5 index size | Efficient | ~475 rows = minimal overhead |
| Database size | <100MB for typical use | ~50KB for 475 sample rows |

---

## Testing

### Unit Tests
```bash
python test_phase1.py    # Parser + DB tests
```

### Integration Tests
```bash
python test_phase5.py    # Full end-to-end (9 test suites)
```

Tests validate:
- Parser extraction correctness
- Database integrity (no orphaned rows)
- API endpoints
- Search clustering
- FTS5 performance
- UI loading

---

## Known Limitations

- No authentication (assumes single user, local use)
- No concurrent imports (but concurrent searches OK)
- No partial/incremental imports (re-import = delete + reimport)
- No export feature (read-only after import)
- Print area detection via named ranges only (not Sheet.PageSetup properties in xlrd)

---

## Future Enhancements

- [ ] Import progress indicator
- [ ] Export search results to Excel/CSV
- [ ] Advanced filters (date ranges, multi-select criteria)
- [ ] Bulk actions (delete multiple projects)
- [ ] Import history/audit log
- [ ] Duplicate detection by content (not just path)
- [ ] Incremental import (track file modification time)
- [ ] API documentation (Swagger/OpenAPI)

---

## Contact & Support

If you encounter issues:
1. Check troubleshooting section above
2. Run `python test_phase5.py` to validate installation
3. Check Flask console for error messages
4. Review relevant spec file (Initial Project Specs.md or pgs_cutlist_ui_spec.md)

---

**Last Updated**: April 24, 2026  
**Status**: Production-ready  
**Phase**: 5/5 (Complete)
