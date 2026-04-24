#!/usr/bin/env python3
"""Deeper inspection: rows 6-11 and named ranges / print areas."""
import xlrd

def inspect_detail(file_path):
    print(f"\n{'='*80}")
    print(f"{file_path}")
    print('='*80)

    wb = xlrd.open_workbook(file_path, on_demand=False)

    # --- Named ranges / print areas ---
    print("\nNamed ranges in workbook:")
    if hasattr(wb, 'name_obj_list') and wb.name_obj_list:
        for n in wb.name_obj_list:
            try:
                print(f"  name={repr(n.name)}  scope={n.scope}  result={n.result}")
            except Exception as e:
                print(f"  name={repr(n.name)}  (error reading result: {e})")
    elif hasattr(wb, 'name_map') and wb.name_map:
        for name, objs in wb.name_map.items():
            print(f"  {name}: {objs}")
    else:
        print("  (none found)")

    # --- Row layout of first PAGE sheet ---
    page_sheet = next(
        wb.sheet_by_index(i)
        for i in range(wb.nsheets)
        if wb.sheet_by_index(i).name.startswith('PAGE')
    )
    print(f"\nRows 6-11 of sheet '{page_sheet.name}':")
    for row_idx in range(5, min(11, page_sheet.nrows)):
        vals = []
        for col in range(min(25, page_sheet.ncols)):
            v = page_sheet.cell_value(row_idx, col)
            vals.append(repr(v)[:15] if v != '' else '.')
        print(f"  Row {row_idx+1:2d}: {' | '.join(vals)}")


for f in [
    'Phase1-Sample-Local/611 SERIES.xls',
    'Phase1-Sample-Local/830 SERIES.xls',
    'Phase1-Sample-Local/662 SERIES.xls',
]:
    inspect_detail(f)
