import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, request, jsonify, abort

from db import CutlistDatabase
from parser import CutlistParser

api = Blueprint('api', __name__)

# Will be set by app.py when creating the Flask app
_db_path = None


def get_db():
    db = CutlistDatabase(_db_path)
    db.connect()
    return db


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@api.route('/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    fsc_only = request.args.get('fsc') == '1'
    flagged_only = request.args.get('flagged') == '1'
    initials = request.args.get('initials', '').strip()  # comma-separated
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    db = get_db()
    try:
        cur = db.conn.cursor()

        fts_query = _build_fts_query(q)

        try:
            cur.execute("""
                SELECT r.id, r.sheet_id, r.row_number,
                       bm25(rows_fts) AS score
                FROM rows_fts
                JOIN rows r ON rows_fts.rowid = r.id
                WHERE rows_fts MATCH ?
                ORDER BY score
            """, (fts_query,))
            matches = cur.fetchall()
        except Exception as e:
            return jsonify({'error': f'Search error: {e}'}), 400

        if not matches:
            return jsonify([])

        by_sheet = {}
        for row in matches:
            sid = row['sheet_id']
            by_sheet.setdefault(sid, []).append(row)

        # Fetch all sheet+project metadata in one query instead of one per sheet
        sheet_ids = list(by_sheet.keys())
        placeholders = ','.join('?' * len(sheet_ids))
        cur.execute(f"""
            SELECT s.*, p.id as project_id, p.job_name, p.job_number,
                   p.series_number, p.room, p.file_path, p.is_fsc,
                   p.has_flags, p.cutlist_by, p.cutlist_date
            FROM sheets s
            JOIN projects p ON s.project_id = p.id
            WHERE s.id IN ({placeholders})
        """, sheet_ids)
        sheet_meta_map = {row['id']: row for row in cur.fetchall()}

        results = []
        for sheet_id, sheet_matches in by_sheet.items():
            sheet_meta = sheet_meta_map.get(sheet_id)
            if not sheet_meta:
                continue

            if fsc_only and not sheet_meta['is_fsc']:
                continue
            if flagged_only and not sheet_meta['has_flags']:
                continue
            if initials:
                allowed = [i.strip().upper() for i in initials.split(',')]
                by_val = (sheet_meta['cutlist_by'] or '').upper()
                if by_val not in allowed:
                    continue
            if date_from and (sheet_meta['cutlist_date'] or '') < date_from:
                continue
            if date_to and (sheet_meta['cutlist_date'] or '') > date_to:
                continue

            matched_row_numbers = sorted(set(m['row_number'] for m in sheet_matches))
            clusters = _cluster_rows(matched_row_numbers, gap=3)

            # Fetch all context rows for this sheet in one query (one BETWEEN per cluster)
            ranges = [(max(c[0] - 2, 1), c[-1] + 2) for c in clusters]
            conditions = ' OR '.join('row_number BETWEEN ? AND ?' for _ in ranges)
            params = [sheet_id] + [v for r in ranges for v in r]
            cur.execute(
                f"SELECT * FROM rows WHERE sheet_id = ? AND ({conditions}) ORDER BY row_number",
                params
            )
            rows_by_num = {r['row_number']: dict(r) for r in cur.fetchall()}

            for cluster in clusters:
                context_start = max(cluster[0] - 2, 1)
                context_end = cluster[-1] + 2
                context_rows = [rows_by_num[n] for n in range(context_start, context_end + 1) if n in rows_by_num]
                matched_set = set(cluster)
                for row in context_rows:
                    row['is_match'] = row['row_number'] in matched_set

                results.append({
                    'project_id': sheet_meta['project_id'],
                    'job_name': sheet_meta['job_name'],
                    'job_number': sheet_meta['job_number'],
                    'series_number': sheet_meta['series_number'],
                    'room': sheet_meta['room'],
                    'file_path': sheet_meta['file_path'],
                    'sheet_id': sheet_id,
                    'sheet_name': sheet_meta['sheet_name'],
                    'rows': context_rows,
                })

        return jsonify(results)
    finally:
        db.close()


def _build_fts_query(q):
    """Wrap the query string safely for FTS5."""
    # If it already looks like an FTS5 expression, pass through
    if any(op in q for op in ('"', 'AND', 'OR', 'NOT', '*')):
        return q
    # Multi-word: require all terms
    terms = q.split()
    if len(terms) == 1:
        return terms[0]
    return ' '.join(terms)


def _cluster_rows(row_numbers, gap=3):
    """Group sorted row numbers into clusters where consecutive gap <= gap."""
    if not row_numbers:
        return []
    clusters = [[row_numbers[0]]]
    for rn in row_numbers[1:]:
        if rn - clusters[-1][-1] <= gap:
            clusters[-1].append(rn)
        else:
            clusters.append([rn])
    return clusters


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@api.route('/projects')
def list_projects():
    db = get_db()
    cur = db.conn.cursor()
    cur.execute("""
        SELECT p.*,
               COUNT(DISTINCT s.id) AS sheet_count,
               COALESCE(SUM(s.row_count), 0) AS total_rows,
               COUNT(DISTINCT f.id) AS flag_count
        FROM projects p
        LEFT JOIN sheets s ON s.project_id = p.id
        LEFT JOIN flags f ON f.project_id = p.id AND f.resolved = 0
        GROUP BY p.id
        ORDER BY p.import_date DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    db.close()
    return jsonify(rows)


@api.route('/projects/preview', methods=['POST'])
def preview_project():
    data = request.get_json()
    if not data or 'file_path' not in data:
        abort(400, 'file_path is required')

    file_path = data['file_path']
    if not Path(file_path).exists():
        abort(404, f'File not found: {file_path}')

    try:
        parser = CutlistParser(file_path)
        result = parser.parse()
    except Exception as e:
        abort(422, f'Failed to parse file: {e}')

    # Check if already imported
    db = get_db()
    already_imported = db.project_exists(str(Path(file_path).resolve()))
    db.close()

    preview = {
        'file_path': result['file_path'],
        'already_imported': already_imported,
        'format_type': result['format_type'],
        'title_block': result['title_block'],
        'sheets': [
            {
                'sheet_name': s['sheet_name'],
                'is_standard': s['is_standard'],
                'print_area': s['print_area'],
                'print_area_fallback': s['print_area_fallback'],
                'row_count': s['row_count'],
            }
            for s in result['sheets']
        ],
        'flags': result['flags'],
    }
    return jsonify(preview)


@api.route('/projects/import', methods=['POST'])
def import_project():
    data = request.get_json()
    if not data or 'file_path' not in data:
        abort(400, 'file_path is required')

    file_path = str(Path(data['file_path']).resolve())

    db = get_db()
    if db.project_exists(file_path):
        db.close()
        abort(409, 'File already imported. Use /projects/{id}/reimport to re-import.')

    try:
        parser = CutlistParser(file_path)
        result = parser.parse()
        rows_inserted, flags_raised = insert_parsed(db, result)
    except Exception as e:
        db.rollback()
        db.close()
        abort(422, f'Import failed: {e}')

    db.close()
    return jsonify({
        'status': 'imported',
        'file_path': file_path,
        'rows_inserted': rows_inserted,
        'flags_raised': flags_raised,
    }), 201


@api.route('/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    db = get_db()
    cur = db.conn.cursor()
    cur.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not cur.fetchone():
        db.close()
        abort(404, f'Project {project_id} not found')

    cur.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    db.close()
    return jsonify({'status': 'deleted', 'project_id': project_id})


@api.route('/projects/<int:project_id>/sheets')
def list_project_sheets(project_id):
    db = get_db()
    cur = db.conn.cursor()
    cur.execute("SELECT id, sheet_name FROM sheets WHERE project_id = ? ORDER BY id", (project_id,))
    sheets = [dict(r) for r in cur.fetchall()]
    db.close()
    return jsonify(sheets)


@api.route('/projects/<int:project_id>/sheet/<int:sheet_id>')
def get_sheet(project_id, sheet_id):
    db = get_db()
    cur = db.conn.cursor()

    cur.execute("""
        SELECT s.*, p.job_name, p.job_number, p.series_number, p.room,
               p.area, p.vto_reference, p.is_fsc, p.is_fr,
               p.cutlist_by, p.cutlist_date, p.checked_by, p.checked_date,
               p.format_type, p.file_path
        FROM sheets s
        JOIN projects p ON s.project_id = p.id
        WHERE s.id = ? AND p.id = ?
    """, (sheet_id, project_id))
    sheet = cur.fetchone()
    if not sheet:
        db.close()
        abort(404)

    cur.execute("""
        SELECT * FROM rows WHERE sheet_id = ? ORDER BY row_number
    """, (sheet_id,))
    rows = [dict(r) for r in cur.fetchall()]

    # Parse machining_block JSON
    sheet_dict = dict(sheet)
    try:
        sheet_dict['machining_block'] = json.loads(sheet_dict.get('machining_block') or '[]')
    except Exception:
        sheet_dict['machining_block'] = []

    db.close()
    return jsonify({'sheet': sheet_dict, 'rows': rows})


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

@api.route('/flags')
def list_flags():
    resolved = request.args.get('resolved', '0')
    db = get_db()
    cur = db.conn.cursor()

    if resolved == 'all':
        cur.execute("""
            SELECT f.*, p.job_name, p.job_number, s.sheet_name
            FROM flags f
            JOIN projects p ON f.project_id = p.id
            LEFT JOIN sheets s ON f.sheet_id = s.id
            ORDER BY f.resolved ASC, f.id DESC
        """)
    else:
        show_resolved = resolved == '1'
        cur.execute("""
            SELECT f.*, p.job_name, p.job_number, s.sheet_name
            FROM flags f
            JOIN projects p ON f.project_id = p.id
            LEFT JOIN sheets s ON f.sheet_id = s.id
            WHERE f.resolved = ?
            ORDER BY f.id DESC
        """, (1 if show_resolved else 0,))

    rows = [dict(r) for r in cur.fetchall()]
    db.close()
    return jsonify(rows)


@api.route('/flags/<int:flag_id>/resolve', methods=['POST'])
def resolve_flag(flag_id):
    db = get_db()
    cur = db.conn.cursor()
    cur.execute("SELECT id FROM flags WHERE id = ?", (flag_id,))
    if not cur.fetchone():
        db.close()
        abort(404, f'Flag {flag_id} not found')

    cur.execute("UPDATE flags SET resolved = 1 WHERE id = ?", (flag_id,))
    db.commit()
    db.close()
    return jsonify({'status': 'resolved', 'flag_id': flag_id})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def insert_parsed(db, result):
    """Insert a fully-parsed result dict into the database. Returns (rows, flags)."""
    project_data = {
        **{k: result['title_block'].get(k) for k in (
            'job_name', 'job_number', 'series_number', 'room', 'area',
            'vto_reference', 'is_fsc', 'is_fr',
            'cutlist_by', 'cutlist_date', 'checked_by', 'checked_date',
        )},
        'file_path': result['file_path'],
        'format_type': result['format_type'],
        'import_date': datetime.now(timezone.utc).isoformat(),
        'has_flags': result['has_flags'],
    }
    project_id = db.insert_project(project_data)

    total_rows = 0
    sheet_id_map = {}

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
        sheet_id_map[sheet['sheet_name']] = sheet_id
        for row in sheet['rows']:
            db.insert_row(sheet_id, row)
            total_rows += 1

    for flag in result['flags']:
        db.insert_flag(project_id, {
            'sheet_id': sheet_id_map.get(flag.get('sheet_name')),
            'flag_type': flag['flag_type'],
            'message': flag['message'],
        })

    db.commit()
    return total_rows, len(result['flags'])
