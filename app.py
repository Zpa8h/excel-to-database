import sys
import os
from pathlib import Path
from datetime import datetime, timezone

import click
from flask import Flask, send_from_directory

from db import CutlistDatabase
from parser import CutlistParser
import api as api_module

DB_PATH = Path(__file__).parent / "cutlist.db"


def get_db():
    db = CutlistDatabase(str(DB_PATH))
    db.create_tables()
    return db


def create_app(db_path=None):
    app = Flask(__name__, static_folder='static', static_url_path='')
    resolved = str(db_path or DB_PATH)
    api_module._db_path = resolved
    app.register_blueprint(api_module.api, url_prefix='/api')

    @app.route('/')
    def index():
        static_dir = Path(__file__).parent / 'static'
        return send_from_directory(str(static_dir), 'index.html')

    return app


def import_file(db, file_path):
    """Parse and insert one .xls file. Returns (rows_inserted, flags_raised) or raises."""
    parser = CutlistParser(file_path)
    result = parser.parse()

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
    sheet_id_map = {}  # sheet_name -> sheet_id (for flag linkage)

    for sheet in result['sheets']:
        sheet_data = {
            'sheet_name': sheet['sheet_name'],
            'is_standard': sheet['is_standard'],
            'print_area': sheet['print_area'],
            'print_area_fallback': sheet['print_area_fallback'],
            'edgeband_block': sheet['edgeband_block'],
            'machining_block': sheet['machining_block'],
            'row_count': sheet['row_count'],
        }
        sheet_id = db.insert_sheet(project_id, sheet_data)
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


@click.group()
def cli():
    """PGS Cutlist Database — import and manage cutlist files."""
    pass


@cli.command()
@click.argument('folder', type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option('--db', 'db_path', default=None, help='Path to database file (default: cutlist.db)')
def scan(folder, db_path):
    """Recursively import all .xls files from FOLDER into the database."""
    if db_path:
        target_db = CutlistDatabase(db_path)
        target_db.create_tables()
    else:
        target_db = get_db()

    folder_path = Path(folder).resolve()
    xls_files = sorted(folder_path.rglob('*.xls'))

    if not xls_files:
        click.echo(f"No .xls files found in {folder_path}")
        return

    click.echo(f"Found {len(xls_files)} .xls file(s) in {folder_path}")
    click.echo()

    total_files = len(xls_files)
    imported = 0
    skipped = 0
    failed = 0
    total_rows = 0
    total_flags = 0

    for i, file_path in enumerate(xls_files, 1):
        rel_path = file_path.relative_to(folder_path)
        prefix = f"[{i}/{total_files}]"

        if target_db.project_exists(str(file_path)):
            click.echo(f"{prefix} SKIP     {rel_path}")
            skipped += 1
            continue

        try:
            rows, flags = import_file(target_db, str(file_path))
            flag_note = f"  ({flags} flag(s))" if flags else ""
            click.echo(f"{prefix} IMPORTED {rel_path}  —  {rows} rows{flag_note}")
            imported += 1
            total_rows += rows
            total_flags += flags
        except Exception as e:
            click.echo(f"{prefix} FAILED   {rel_path}  —  {e}", err=True)
            failed += 1

    click.echo()
    click.echo("─" * 60)
    click.echo(f"  Files found:    {total_files}")
    click.echo(f"  Imported:       {imported}")
    click.echo(f"  Skipped:        {skipped}  (already in database)")
    click.echo(f"  Failed:         {failed}")
    click.echo(f"  Rows imported:  {total_rows}")
    click.echo(f"  Flags raised:   {total_flags}")
    click.echo("─" * 60)


@cli.command()
@click.option('--host', default='127.0.0.1', show_default=True)
@click.option('--port', default=5000, show_default=True)
@click.option('--db', 'db_path', default=None, help='Path to database file')
def serve(host, port, db_path):
    """Start the web UI server at localhost:5000."""
    resolved_db = db_path or str(DB_PATH)
    # Ensure database exists before starting
    init_db = CutlistDatabase(resolved_db)
    init_db.create_tables()
    init_db.close()

    app = create_app(resolved_db)
    click.echo(f"Starting PGS Cutlist server at http://{host}:{port}")
    click.echo(f"Database: {resolved_db}")
    click.echo("Press Ctrl+C to stop.")
    app.run(host=host, port=port, debug=False)


if __name__ == '__main__':
    cli()
