#!/usr/bin/env python3
"""Inspect Excel file structure to debug extraction."""

import xlrd


def inspect_file(file_path):
    """Inspect structure of an XLS file."""
    print(f"\n{'='*80}")
    print(f"Inspecting: {file_path}")
    print('='*80)

    try:
        workbook = xlrd.open_workbook(file_path, on_demand=False)
        print(f"\nWorkbook Info:")
        print(f"  Sheets: {workbook.nsheets}")
        print(f"  Encoding: {workbook.encoding}")

        # Check all sheet names
        print(f"\nAll Sheets:")
        for i in range(workbook.nsheets):
            s = workbook.sheet_by_index(i)
            print(f"  {i+1}. '{s.name}' ({s.nrows} rows x {s.ncols} cols)")

        # Find first PAGE sheet (skip excluded ones)
        page_sheet = None
        for i in range(workbook.nsheets):
            sheet = workbook.sheet_by_index(i)
            if sheet.name.startswith('PAGE'):
                page_sheet = sheet
                page_idx = i
                break

        if not page_sheet:
            print("\n⚠️  No PAGE sheet found")
            return

        print(f"\nInspecting First PAGE Sheet: '{page_sheet.name}' (index {page_idx})")
        print(f"  Dimensions: {page_sheet.nrows} rows x {page_sheet.ncols} cols")

        # Show cells E1:E5 (job info area)
        print(f"\nTitle Block Area (E1:E5, E2:E3 merged):")
        for row in range(min(5, page_sheet.nrows)):
            print(f"  Row {row+1}:")
            for col_idx, col_name in [(4, 'E'), (6, 'G'), (21, 'V'), (22, 'W')]:
                try:
                    val = page_sheet.cell_value(row, col_idx)
                    print(f"    {col_name}{row+1}: {repr(val)[:50]}")
                except Exception as e:
                    print(f"    {col_name}{row+1}: (col out of range)")

        # Show row 8 columns A-X (data row sample)
        print(f"\nRow 8 (First Data Row) - Columns A through X:")
        if page_sheet.nrows > 7:
            row_data = []
            for col in range(min(24, page_sheet.ncols)):  # A-X = 0-23
                try:
                    value = page_sheet.cell_value(7, col)
                    row_data.append(f"{repr(value)[:20]}")
                except:
                    row_data.append("(err)")
            for i in range(0, len(row_data), 6):
                print(f"  {' | '.join(row_data[i:i+6])}")
        else:
            print(f"  (File has fewer than 8 rows)")

        # Check for print area using xlrd formatting
        print(f"\nPage Setup Info:")
        print(f"  Sheet has 'pagesetup': {hasattr(page_sheet, 'pagesetup')}")
        # In xlrd, print settings are in sheet.window_panes or book.format_map
        try:
            print(f"  Sheet attributes: {[a for a in dir(page_sheet) if 'print' in a.lower() or 'page' in a.lower()]}")
        except Exception as e:
            print(f"  Error: {e}")

        # Check merged cells
        print(f"\nMerged Cells:")
        if hasattr(page_sheet, 'merged_cells'):
            merged = page_sheet.merged_cells
            if merged:
                print(f"  Found {len(merged)} merged cell ranges")
                for cell_range in merged[:5]:  # Show first 5
                    print(f"    {cell_range}")
            else:
                print(f"  (None)")
        else:
            print(f"  (No merged_cells attribute)")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    files = [
        'Phase1-Sample-Local/611 SERIES.xls',
        'Phase1-Sample-Local/830 SERIES.xls',
        'Phase1-Sample-Local/662 SERIES.xls',
    ]

    for file_path in files:
        try:
            inspect_file(file_path)
        except Exception as e:
            print(f"Failed to inspect {file_path}: {e}")
