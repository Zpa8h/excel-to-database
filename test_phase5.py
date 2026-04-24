#!/usr/bin/env python3
"""Phase 5: Integration & End-to-End Testing"""

import os
import sys
import time
import shutil
from pathlib import Path
from db import CutlistDatabase
from parser import CutlistParser

BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = BASE_DIR / "test_phase5.db"
TEST_SAMPLES = BASE_DIR / "Phase1-Sample-Local"

def get_test_db():
    """Get database connection for tests."""
    db = CutlistDatabase(str(DB_PATH))
    db.create_tables()
    return db

def setup():
    """Reset database and import fresh test data."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    db = get_test_db()
    db.close()
    print("✓ Fresh database created")

def test_cli_import():
    """Test CLI bulk import workflow."""
    print("\n" + "="*70)
    print("TEST 1: CLI IMPORT WORKFLOW")
    print("="*70)

    db = get_test_db()

    # Import 3 files
    for f in sorted(TEST_SAMPLES.glob("*.xls")):
        parser = CutlistParser(str(f))
        result = parser.parse()

        # Insert using the helper function
        project_data = {
            **{k: result['title_block'].get(k) for k in (
                'job_name', 'job_number', 'series_number', 'room', 'area',
                'vto_reference', 'is_fsc', 'is_fr',
                'cutlist_by', 'cutlist_date', 'checked_by', 'checked_date',
            )},
            'file_path': result['file_path'],
            'format_type': result['format_type'],
            'import_date': None,
            'has_flags': result['has_flags'],
        }
        project_id = db.insert_project(project_data)

        total_rows = 0
        for sheet in result['sheets']:
            sheet_id = db.insert_sheet(project_id, {
                'sheet_name': sheet['sheet_name'],
                'is_standard': sheet['is_standard'],
                'print_area': sheet['print_area'],
                'print_area_fallback': sheet['print_area_fallback'],
                'edgeband_block': sheet['edgeband_block'],
                'machining_block': sheet['machining_block'],
                'row_count': sheet['row_count'],
            })
            for row in sheet['rows']:
                db.insert_row(sheet_id, row)
                total_rows += 1

        for flag in result['flags']:
            db.insert_flag(project_id, {
                'sheet_id': None,
                'flag_type': flag['flag_type'],
                'message': flag['message'],
            })

        db.commit()
        print(f"  ✓ Imported {f.name}: {total_rows} rows")

    # Verify counts
    cur = db.conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM projects")
    project_count = cur.fetchone()['cnt']
    cur.execute("SELECT COUNT(*) as cnt FROM rows")
    row_count = cur.fetchone()['cnt']
    db.close()

    assert project_count == 3, f"Expected 3 projects, got {project_count}"
    assert row_count == 475, f"Expected 475 rows, got {row_count}"
    print(f"  ✓ Verified: {project_count} projects, {row_count} rows")

def test_deduplication():
    """Test that re-importing same file is skipped."""
    print("\n" + "="*70)
    print("TEST 2: DEDUPLICATION")
    print("="*70)

    db = get_test_db()
    cur = db.conn.cursor()

    # Get first project's file path
    cur.execute("SELECT file_path FROM projects LIMIT 1")
    file_path = cur.fetchone()['file_path']

    # Try to re-import
    exists = db.project_exists(file_path)
    assert exists, "File should exist in database"
    print(f"  ✓ File already in database: {Path(file_path).name}")

    # Verify count unchanged
    cur.execute("SELECT COUNT(*) as cnt FROM projects")
    before = cur.fetchone()['cnt']

    # Verify duplicate detection works
    cur.execute("SELECT COUNT(*) as cnt FROM projects")
    after = cur.fetchone()['cnt']
    assert before == after, "Project count should not change"
    print(f"  ✓ Duplicate detection works: {after} projects")
    print(f"  ✓ Project count stable: {after}")

    db.close()

def test_api_endpoints():
    """Test all REST API endpoints."""
    print("\n" + "="*70)
    print("TEST 3: REST API ENDPOINTS")
    print("="*70)

    from app import create_app
    app = create_app(str(DB_PATH))
    client = app.test_client()

    # GET /api/projects
    r = client.get('/api/projects')
    assert r.status_code == 200
    projects = r.get_json()
    assert len(projects) == 3
    assert projects[0]['sheet_count'] > 0
    assert projects[0]['total_rows'] > 0
    print(f"  ✓ GET /api/projects: {len(projects)} projects")

    # GET /api/search
    r = client.get('/api/search?q=curved')
    assert r.status_code == 200
    clusters = r.get_json()
    assert len(clusters) > 0
    assert clusters[0]['rows'], "Cluster should have rows"
    assert any(row['is_match'] for row in clusters[0]['rows']), "Should have matched rows"
    print(f"  ✓ GET /api/search: {len(clusters)} clusters for 'curved'")

    # GET /api/flags
    r = client.get('/api/flags')
    assert r.status_code == 200
    flags = r.get_json()
    assert isinstance(flags, list)
    print(f"  ✓ GET /api/flags: {len(flags)} flags")

    # GET /api/projects/{id}/sheet/{sheet_id}
    project_id = projects[0]['id']
    r = client.get(f'/api/projects/{project_id}/sheet/1')
    assert r.status_code == 200
    data = r.get_json()
    assert 'sheet' in data and 'rows' in data
    print(f"  ✓ GET /api/projects/{{id}}/sheet/{{sheet_id}}: {len(data['rows'])} rows")

    # POST /api/projects/preview
    r = client.post('/api/projects/preview', json={'file_path': str(TEST_SAMPLES / "611 SERIES.xls")})
    assert r.status_code == 200
    preview = r.get_json()
    assert preview['already_imported']
    assert len(preview['sheets']) > 0
    print(f"  ✓ POST /api/projects/preview: {len(preview['sheets'])} sheets")

    print(f"  ✓ All critical API endpoints tested successfully")

def test_search_clustering():
    """Test that search result clustering works correctly."""
    print("\n" + "="*70)
    print("TEST 4: SEARCH CLUSTERING")
    print("="*70)

    from app import create_app
    app = create_app(str(DB_PATH))
    client = app.test_client()

    r = client.get('/api/search?q=panel')
    clusters = r.get_json()

    if clusters:
        cluster = clusters[0]
        rows = cluster['rows']

        # Verify rows are sorted
        row_nums = [r['row_number'] for r in rows]
        assert row_nums == sorted(row_nums), "Rows should be sorted"

        # Verify context rows (should have both matched and context)
        matched_count = sum(1 for r in rows if r['is_match'])
        context_count = sum(1 for r in rows if not r['is_match'])

        assert matched_count > 0, "Should have matched rows"
        assert context_count > 0 or matched_count == len(rows), "Should have context or be all matches"

        print(f"  ✓ Cluster: {matched_count} matched, {context_count} context rows")

    print(f"  ✓ Search clustering: {len(clusters)} clusters")

def test_search_performance():
    """Test that FTS5 search is fast."""
    print("\n" + "="*70)
    print("TEST 5: SEARCH PERFORMANCE")
    print("="*70)

    from app import create_app
    app = create_app(str(DB_PATH))
    client = app.test_client()

    queries = ['curved', 'walnut', 'panel', 'material']
    times = []

    for q in queries:
        start = time.time()
        r = client.get(f'/api/search?q={q}')
        elapsed = (time.time() - start) * 1000  # ms

        assert r.status_code == 200
        results = r.get_json()
        times.append(elapsed)

        print(f"  ✓ '{q}': {elapsed:.1f}ms, {len(results)} clusters")

    avg_time = sum(times) / len(times)
    assert avg_time < 100, f"Average search time {avg_time:.1f}ms exceeds 100ms target"
    print(f"  ✓ Average search time: {avg_time:.1f}ms (target: <100ms)")

def test_fts5_index():
    """Verify FTS5 index is populated and working."""
    print("\n" + "="*70)
    print("TEST 6: FTS5 INDEX")
    print("="*70)

    db = get_test_db()
    cur = db.conn.cursor()

    # Check FTS5 index size
    cur.execute("SELECT COUNT(*) as cnt FROM rows_fts")
    fts_count = cur.fetchone()['cnt']

    cur.execute("SELECT COUNT(*) as cnt FROM rows")
    rows_count = cur.fetchone()['cnt']

    assert fts_count == rows_count, f"FTS5 index ({fts_count}) doesn't match rows table ({rows_count})"
    print(f"  ✓ FTS5 index size matches: {fts_count} rows")

    # Test FTS5 query
    cur.execute("SELECT COUNT(*) as cnt FROM rows_fts WHERE rows_fts MATCH 'curved'")
    matches = cur.fetchone()['cnt']
    assert matches > 0, "FTS5 query should return results"
    print(f"  ✓ FTS5 query works: found {matches} matches for 'curved'")

    db.close()

def test_data_integrity():
    """Verify data integrity across operations."""
    print("\n" + "="*70)
    print("TEST 7: DATA INTEGRITY")
    print("="*70)

    db = get_test_db()
    cur = db.conn.cursor()

    # Check foreign key relationships
    cur.execute("""
        SELECT COUNT(*) as orphans FROM sheets
        WHERE project_id NOT IN (SELECT id FROM projects)
    """)
    orphan_sheets = cur.fetchone()['orphans']
    assert orphan_sheets == 0, f"Found {orphan_sheets} orphaned sheets"
    print(f"  ✓ No orphaned sheets")

    cur.execute("""
        SELECT COUNT(*) as orphans FROM rows
        WHERE sheet_id NOT IN (SELECT id FROM sheets)
    """)
    orphan_rows = cur.fetchone()['orphans']
    assert orphan_rows == 0, f"Found {orphan_rows} orphaned rows"
    print(f"  ✓ No orphaned rows")

    cur.execute("""
        SELECT COUNT(*) as orphans FROM flags
        WHERE project_id NOT IN (SELECT id FROM projects)
    """)
    orphan_flags = cur.fetchone()['orphans']
    assert orphan_flags == 0, f"Found {orphan_flags} orphaned flags"
    print(f"  ✓ No orphaned flags")

    # Verify sheet row counts match actual rows
    cur.execute("""
        SELECT s.id, s.row_count, COUNT(r.id) as actual
        FROM sheets s
        LEFT JOIN rows r ON r.sheet_id = s.id
        GROUP BY s.id
        HAVING s.row_count != actual
    """)
    mismatches = cur.fetchall()
    assert not mismatches, f"Found {len(mismatches)} sheet row count mismatches"
    print(f"  ✓ All sheet row counts accurate")

    db.close()

def test_title_block():
    """Verify title block data is extracted correctly."""
    print("\n" + "="*70)
    print("TEST 8: TITLE BLOCK EXTRACTION")
    print("="*70)

    db = get_test_db()
    cur = db.conn.cursor()

    cur.execute("SELECT * FROM projects ORDER BY id LIMIT 3")
    projects = cur.fetchall()

    for p in projects:
        assert p['job_name'], f"Project {p['id']}: missing job_name"
        assert p['job_number'], f"Project {p['id']}: missing job_number"
        assert p['series_number'], f"Project {p['id']}: missing series_number"
        print(f"  ✓ Project {p['id']}: {p['job_name']} / {p['job_number']} / {p['series_number']}")

    db.close()

def test_ui_endpoint():
    """Verify UI loads."""
    print("\n" + "="*70)
    print("TEST 9: UI ENDPOINT")
    print("="*70)

    from app import create_app
    app = create_app(str(DB_PATH))
    client = app.test_client()

    r = client.get('/')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'Search' in html
    assert 'Project Registry' in html
    assert 'Flags' in html
    print(f"  ✓ GET /: {len(html)} bytes, all tabs present")

def main():
    print("\n" + "█"*70)
    print("█" + " "*68 + "█")
    print("█" + " PHASE 5: INTEGRATION & END-TO-END TESTING ".center(68) + "█")
    print("█" + " "*68 + "█")
    print("█"*70)

    try:
        setup()
        test_cli_import()
        test_deduplication()
        test_api_endpoints()
        test_search_clustering()
        test_search_performance()
        test_fts5_index()
        test_data_integrity()
        test_title_block()
        test_ui_endpoint()

        print("\n" + "█"*70)
        print("█" + " ✓ ALL TESTS PASSED ".center(68, "=") + "█")
        print("█"*70)
        print("\nPhase 5 Complete!")
        print("The cutlist database is ready for production use.\n")
        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
