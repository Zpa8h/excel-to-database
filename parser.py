import xlrd
import re
from datetime import datetime
from pathlib import Path


EXCLUDED_SHEET_PREFIXES = [
    'PROTOCOL',
    'ENGINEERING CHECKLIST',
    'ASSEMBLY',
    "Ass'y labels",
    'PANEL STOCK LAYUP',
    'SORTED PARTS LIST',
    'MATERIAL REQ.',
]

STANDARD_SHEET_PATTERN = re.compile(r'^PAGE\s*\(\s*\d+\s*\)$', re.IGNORECASE)


class CutlistParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.workbook = None
        self.format_type = None

    def parse(self):
        try:
            self.workbook = xlrd.open_workbook(self.file_path, on_demand=True)
        except Exception as e:
            raise ValueError(f"Failed to open {self.file_path}: {e}")

        if not self.workbook.nsheets:
            raise ValueError(f"No sheets found in {self.file_path}")

        # Detect format from first sheet's V1
        self.format_type = self._detect_format()

        # Extract title block (once, from first sheet)
        first_sheet = self.workbook.sheet_by_index(0)
        title_block = self._extract_title_block(first_sheet)

        # Process all sheets
        sheets = []
        flags = []

        for sheet_idx in range(self.workbook.nsheets):
            sheet = self.workbook.sheet_by_index(sheet_idx)
            sheet_name = sheet.name

            # Check if sheet should be excluded
            if self._should_exclude_sheet(sheet_name):
                continue

            # Flag if non-standard sheet name
            is_standard = STANDARD_SHEET_PATTERN.match(sheet_name) is not None
            if not is_standard:
                flags.append({
                    'sheet_name': sheet_name,
                    'flag_type': 'non-standard-sheet',
                    'message': f"Job {title_block.get('job_number')} – Series {title_block.get('series_number')}: sheet '{sheet_name}' does not match standard naming — may warrant review"
                })

            # Extract sheet data
            sheet_data = self._extract_sheet(sheet, sheet_name, is_standard)

            # Check for missing print area
            if sheet_data['print_area'] is None:
                sheet_data['print_area_fallback'] = True
                flags.append({
                    'sheet_name': sheet_name,
                    'flag_type': 'no-print-area',
                    'message': f"Job {title_block.get('job_number')} – Series {title_block.get('series_number')}: sheet '{sheet_name}' has no print area — data extraction skipped"
                })
                sheet_data['rows'] = []
            else:
                sheet_data['rows'] = self._extract_rows(sheet, self.format_type, sheet_data['print_area'])

            sheets.append(sheet_data)

        return {
            'file_path': str(self.file_path),
            'title_block': title_block,
            'format_type': self.format_type,
            'sheets': sheets,
            'flags': flags,
            'has_flags': len(flags) > 0
        }

    def _detect_format(self):
        """Check V1 cell in first sheet to determine format."""
        try:
            first_sheet = self.workbook.sheet_by_index(0)
            v1_value = self._get_cell_value(first_sheet, 0, 21)  # V = column 21 (0-indexed)

            if not v1_value:
                return 'traditional'

            v1_str = str(v1_value).strip()

            # If V1 contains a version number (e.g., "Version 1")
            if 'version' in v1_str.lower() and any(c.isdigit() for c in v1_str):
                return 'single-sheet'
            # If V1 contains only text without version number
            elif 'version' in v1_str.lower():
                return 'traditional'
            else:
                # Ambiguous - default to traditional
                return 'traditional'
        except Exception:
            return 'traditional'

    def _extract_title_block(self, sheet):
        """Extract title block from rows 1-7."""
        title_block = {
            'job_name': self._get_cell_value(sheet, 0, 4),  # E1
            'job_number': self._get_cell_value(sheet, 1, 4),  # E2
            'series_number': self._get_cell_value(sheet, 3, 4),  # E4
            'room': self._get_cell_value(sheet, 4, 4),  # E5
            'vto_reference': self._get_merged_cell_value(sheet, 0, 6, 7),  # G1:H1
            'area': self._get_merged_cell_value(sheet, 0, 15, 20),  # P1:U1
            'cutlist_date': self._get_cell_value(sheet, 2, 6),  # G3
            'cutlist_by': self._get_cell_value(sheet, 2, 7),  # H3
            'checked_date': self._get_cell_value(sheet, 3, 6),  # G4
            'checked_by': self._get_cell_value(sheet, 3, 7),  # H4
            'in_works_date': self._get_cell_value(sheet, 4, 6),  # G5
            'in_works_by': self._get_cell_value(sheet, 4, 7),  # H5
            'is_fr': bool(self._get_cell_value(sheet, 1, 12)),  # M2
            'is_fsc': bool(self._get_cell_value(sheet, 3, 12)),  # M4
            'edgeband_block': self._get_merged_cell_raw(sheet, 2, 6, 13, 17),  # N3:R6
            'machining_block': self._get_machining_block(sheet),
            'version_number': self._get_version_number(sheet)
        }
        return title_block

    def _get_version_number(self, sheet):
        """Extract version number based on format."""
        if self.format_type == 'single-sheet':
            return self._get_cell_value(sheet, 0, 21)  # V1
        else:
            return self._get_cell_value(sheet, 0, 22)  # W1

    def _get_machining_block(self, sheet):
        """Extract 8 machining cells as array."""
        cells = []

        if self.format_type == 'single-sheet':
            # S3, S4, S5, S6, V3, V4, V5, V6
            cols = [18, 18, 18, 18, 21, 21, 21, 21]
            rows = [2, 3, 4, 5, 2, 3, 4, 5]
        else:
            # S3:U3, S4:U4, S5:U5, S6:U6, V3:W3, V4:W4, V5:W5, V6:W6
            # For merged cells, we get the value from the first cell
            cols = [18, 18, 18, 18, 21, 21, 21, 21]
            rows = [2, 3, 4, 5, 2, 3, 4, 5]

        for row, col in zip(rows, cols):
            value = self._get_cell_value(sheet, row, col)
            cells.append(str(value) if value else '')

        return cells

    def _should_exclude_sheet(self, sheet_name):
        """Check if sheet should be excluded based on prefix."""
        sheet_name_lower = sheet_name.lower()
        for prefix in EXCLUDED_SHEET_PREFIXES:
            if sheet_name_lower.startswith(prefix.lower()):
                return True
        return False

    def _extract_sheet(self, sheet, sheet_name, is_standard):
        """Extract sheet metadata and data rows."""
        print_area = self._get_print_area(sheet)

        sheet_data = {
            'sheet_name': sheet_name,
            'is_standard': is_standard,
            'print_area': print_area,
            'print_area_fallback': False,
            'edgeband_block': self._get_merged_cell_raw(sheet, 2, 6, 13, 17),  # N3:R6
            'machining_block': self._get_machining_block(sheet),
            'row_count': 0,
            'rows': []
        }

        return sheet_data

    def _get_print_area(self, sheet):
        """Get print area from sheet. Returns (start_row, end_row) or None."""
        try:
            if not sheet.pagesetup.print_area:
                return None

            print_area_str = sheet.pagesetup.print_area
            # Parse print area string like "$A$8:$X$237"
            match = re.search(r'\$[A-Z]+\$(\d+):\$[A-Z]+\$(\d+)', print_area_str)
            if match:
                start_row = int(match.group(1)) - 1  # Convert to 0-indexed
                end_row = int(match.group(2)) - 1
                return (start_row, end_row)

            return None
        except Exception:
            return None

    def _extract_rows(self, sheet, format_type, print_area):
        """Extract data rows from sheet."""
        rows = []
        start_row, end_row = print_area

        # Data starts at row 8 (index 7)
        data_start_row = 7

        # Use print area's end_row if it's after data_start_row
        if end_row < data_start_row:
            return rows

        for row_idx in range(data_start_row, end_row + 1):
            row_data = self._extract_single_row(sheet, row_idx, format_type)
            row_data['row_number'] = row_idx + 1  # Store 1-indexed row number
            rows.append(row_data)

        return rows

    def _extract_single_row(self, sheet, row_idx, format_type):
        """Extract a single data row."""
        if format_type == 'single-sheet':
            return self._extract_row_single_sheet(sheet, row_idx)
        else:
            return self._extract_row_traditional(sheet, row_idx)

    def _extract_row_single_sheet(self, sheet, row_idx):
        """Extract row for single-sheet format."""
        return {
            'vto': self._get_cell_value(sheet, row_idx, 0),  # A
            'fl_rm': self._get_cell_value(sheet, row_idx, 1),  # B
            'part_category': self._get_cell_value(sheet, row_idx, 2),  # C
            'part_component': self._get_cell_value(sheet, row_idx, 3),  # D
            'description': self._get_cell_value(sheet, row_idx, 4),  # E
            'width': self._get_cell_value(sheet, row_idx, 5),  # F
            'length': self._get_cell_value(sheet, row_idx, 6),  # G
            'thickness': self._get_cell_value(sheet, row_idx, 7),  # H
            'material': self._get_merged_cell_join(sheet, row_idx, 8, 11),  # I:L
            'qty': self._get_cell_value(sheet, row_idx, 12),  # M
            'edge_left': self._get_cell_value(sheet, row_idx, 13),  # N
            'edge_right': self._get_cell_value(sheet, row_idx, 14),  # O
            'edge_top': self._get_cell_value(sheet, row_idx, 15),  # P
            'edge_bottom': self._get_cell_value(sheet, row_idx, 16),  # Q
            'edge_front': self._get_cell_value(sheet, row_idx, 17),  # R
            'edge_back': self._get_cell_value(sheet, row_idx, 18),  # S
            'cnc_flag': self._get_cell_value(sheet, row_idx, 19),  # T
            'notes': self._get_merged_cell_join(sheet, row_idx, 20, 21),  # U:V
            'cnc_prog': self._get_cell_value(sheet, row_idx, 22),  # W
        }

    def _extract_row_traditional(self, sheet, row_idx):
        """Extract row for traditional multi-sheet format."""
        return {
            'vto': self._get_cell_value(sheet, row_idx, 0),  # A
            'fl_rm': self._get_cell_value(sheet, row_idx, 1),  # B
            'part_category': self._get_cell_value(sheet, row_idx, 2),  # C
            'part_component': self._get_cell_value(sheet, row_idx, 3),  # D
            'description': self._get_cell_value(sheet, row_idx, 4),  # E
            'width': self._get_cell_value(sheet, row_idx, 5),  # F
            'length': self._get_cell_value(sheet, row_idx, 6),  # G
            'thickness': self._get_cell_value(sheet, row_idx, 7),  # H
            'material': self._get_merged_cell_join(sheet, row_idx, 8, 11),  # I:L
            'qty': self._get_cell_value(sheet, row_idx, 12),  # M
            'edge_left': self._get_cell_value(sheet, row_idx, 13),  # N
            'edge_right': self._get_cell_value(sheet, row_idx, 14),  # O
            'edge_top': self._get_cell_value(sheet, row_idx, 15),  # P
            'edge_bottom': self._get_cell_value(sheet, row_idx, 16),  # Q
            'edge_front': self._get_cell_value(sheet, row_idx, 17),  # R
            'edge_back': self._get_cell_value(sheet, row_idx, 18),  # S
            'cnc_flag': self._get_cell_value(sheet, row_idx, 19),  # T
            'notes': self._get_merged_cell_join(sheet, row_idx, 20, 22),  # U:W
            'cnc_prog': self._get_cell_value(sheet, row_idx, 23),  # X
        }

    def _get_cell_value(self, sheet, row, col):
        """Get value from a single cell."""
        try:
            if row < sheet.nrows and col < sheet.ncols:
                value = sheet.cell_value(row, col)
                return str(value).strip() if value else ''
            return ''
        except Exception:
            return ''

    def _get_merged_cell_value(self, sheet, start_row, start_col, end_col):
        """Get value from merged cell range (single row). Returns first non-empty cell."""
        try:
            for col in range(start_col, end_col + 1):
                value = self._get_cell_value(sheet, start_row, col)
                if value:
                    return value
            return ''
        except Exception:
            return ''

    def _get_merged_cell_join(self, sheet, row, start_col, end_col):
        """Get values from cell range and join with |."""
        try:
            values = []
            for col in range(start_col, end_col + 1):
                value = self._get_cell_value(sheet, row, col)
                values.append(value)
            return ' | '.join(v for v in values if v)
        except Exception:
            return ''

    def _get_merged_cell_raw(self, sheet, start_row, start_col, end_row, end_col):
        """Get raw text from a cell range (preserve formatting, join with newlines)."""
        try:
            lines = []
            for row in range(start_row, end_row + 1):
                row_values = []
                for col in range(start_col, end_col + 1):
                    value = self._get_cell_value(sheet, row, col)
                    if value:
                        row_values.append(value)
                if row_values:
                    lines.append(' '.join(row_values))
            return '\n'.join(lines) if lines else ''
        except Exception:
            return ''
