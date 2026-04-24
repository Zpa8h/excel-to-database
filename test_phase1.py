#!/usr/bin/env python3
"""Test Phase 1: Parser and Database"""

import json
import os
from pathlib import Path
from parser import CutlistParser
from db import CutlistDatabase


def test_parser():
    """Test parsing on sample files."""
    sample_files = [
        'Phase1-Sample-Local/611 SERIES.xls',
        'Phase1-Sample-Local/830 SERIES.xls',
        'Phase1-Sample-Local/662 SERIES.xls',
    ]

    for file_path in sample_files:
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            continue

        print(f"\n{'='*80}")
        print(f"Testing: {file_path}")
        print('='*80)

        try:
            parser = CutlistParser(file_path)
            result = parser.parse()

            print(f"\n✅ Successfully parsed {file_path}")
            print(f"\nTitle Block:")
            print(f"  Job Name:      {result['title_block'].get('job_name')}")
            print(f"  Job Number:    {result['title_block'].get('job_number')}")
            print(f"  Series Number: {result['title_block'].get('series_number')}")
            print(f"  Room:          {result['title_block'].get('room')}")
            print(f"  Format Type:   {result['format_type']}")
            print(f"  VTO Reference: {result['title_block'].get('vto_reference')}")
            print(f"  Area:          {result['title_block'].get('area')}")
            print(f"  Is FSC:        {result['title_block'].get('is_fsc')}")
            print(f"  Is FR:         {result['title_block'].get('is_fr')}")
            print(f"  Cutlist By:    {result['title_block'].get('cutlist_by')}")
            print(f"  Cutlist Date:  {result['title_block'].get('cutlist_date')}")
            print(f"  Checked By:    {result['title_block'].get('checked_by')}")
            print(f"  Checked Date:  {result['title_block'].get('checked_date')}")

            print(f"\nSheets ({len(result['sheets'])} captured):")
            for i, sheet in enumerate(result['sheets'], 1):
                print(f"  {i}. {sheet['sheet_name']}")
                print(f"     - Standard: {sheet['is_standard']}")
                print(f"     - Print Area: {sheet['print_area']}")
                print(f"     - Print Area Fallback: {sheet['print_area_fallback']}")
                print(f"     - Row Count: {len(sheet['rows'])}")

            if result['flags']:
                print(f"\nFlags ({len(result['flags'])}):")
                for flag in result['flags']:
                    print(f"  - [{flag['flag_type']}] {flag['message']}")
            else:
                print(f"\nFlags: None")

            # Show sample data rows if available
            if result['sheets']:
                first_sheet = result['sheets'][0]
                if first_sheet['rows']:
                    print(f"\nSample Data Rows from '{first_sheet['sheet_name']}':")
                    for row in first_sheet['rows'][:3]:  # Show first 3 rows
                        print(f"  Row {row['row_number']}:")
                        print(f"    - Description: {row['description']}")
                        print(f"    - Material:    {row['material']}")
                        print(f"    - QTY:         {row['qty']}")
                        print(f"    - Notes:       {row['notes']}")

        except Exception as e:
            print(f"❌ Error parsing {file_path}: {e}")
            import traceback
            traceback.print_exc()


def test_database():
    """Test database creation and insertion."""
    db_path = "test_cutlist.db"

    # Remove old test database if exists
    if os.path.exists(db_path):
        os.remove(db_path)

    print(f"\n{'='*80}")
    print("Testing Database Creation and Insertion")
    print('='*80)

    try:
        db = CutlistDatabase(db_path)
        db.create_tables()
        print("✅ Database tables created successfully")

        # Test inserting data from a parsed file
        sample_file = 'Phase1-Sample-Local/611 SERIES.xls'
        if os.path.exists(sample_file):
            parser = CutlistParser(sample_file)
            result = parser.parse()

            # Start transaction
            db.connect()

            # Insert project
            project_data = {
                'file_path': result['file_path'],
                'job_name': result['title_block'].get('job_name'),
                'job_number': result['title_block'].get('job_number'),
                'series_number': result['title_block'].get('series_number'),
                'room': result['title_block'].get('room'),
                'area': result['title_block'].get('area'),
                'vto_reference': result['title_block'].get('vto_reference'),
                'is_fsc': result['title_block'].get('is_fsc', False),
                'is_fr': result['title_block'].get('is_fr', False),
                'cutlist_by': result['title_block'].get('cutlist_by'),
                'cutlist_date': result['title_block'].get('cutlist_date'),
                'checked_by': result['title_block'].get('checked_by'),
                'checked_date': result['title_block'].get('checked_date'),
                'format_type': result['format_type'],
                'import_date': None,
                'has_flags': result['has_flags']
            }

            project_id = db.insert_project(project_data)
            print(f"✅ Inserted project (ID: {project_id})")

            # Insert sheets and rows
            total_rows = 0
            for sheet in result['sheets']:
                sheet_data = {
                    'sheet_name': sheet['sheet_name'],
                    'is_standard': sheet['is_standard'],
                    'print_area': str(sheet['print_area']) if sheet['print_area'] else None,
                    'print_area_fallback': sheet['print_area_fallback'],
                    'edgeband_block': sheet['edgeband_block'],
                    'machining_block': sheet['machining_block'],
                    'row_count': len(sheet['rows'])
                }

                sheet_id = db.insert_sheet(project_id, sheet_data)
                print(f"✅ Inserted sheet '{sheet['sheet_name']}' (ID: {sheet_id}, {len(sheet['rows'])} rows)")

                # Insert rows
                for row in sheet['rows']:
                    db.insert_row(sheet_id, row)
                    total_rows += 1

            # Insert flags
            for flag in result['flags']:
                flag_data = {
                    'sheet_id': None,
                    'flag_type': flag['flag_type'],
                    'message': flag['message']
                }
                db.insert_flag(project_id, flag_data)

            db.commit()
            print(f"✅ Inserted {total_rows} data rows")
            print(f"✅ Transaction committed")

            # Verify FTS5 indexing
            cursor = db.conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM rows_fts")
            fts_count = cursor.fetchone()['count']
            print(f"✅ FTS5 index contains {fts_count} rows")

            # Test a simple FTS5 query
            cursor.execute("SELECT description FROM rows_fts WHERE rows_fts MATCH 'door' LIMIT 5")
            results = cursor.fetchall()
            print(f"✅ FTS5 sample search for 'door': {len(results)} results")

            db.close()
            print(f"\n✅ All database tests passed!")

        else:
            print(f"⚠️  Sample file not found: {sample_file}")

    except Exception as e:
        print(f"❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    print("Phase 1: Parser and Database Testing")
    print("="*80)

    test_parser()
    test_database()

    print(f"\n{'='*80}")
    print("Phase 1 Testing Complete")
    print('='*80)
