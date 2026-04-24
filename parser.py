import xlrd
import re
from pathlib import Path


EXCLUDED_SHEET_PREFIXES = [
    'PROTOCOL',
    'ENGINEERING CHECKLIST',
    'ASSEMBLY',
    "ASS'Y LABELS",
    'PANEL STOCK LAYUP',
    'SORTED PARTS LIST',
    'MATERIAL REQ.',
    'MISC INFO',
]

STANDARD_SHEET_PATTERN = re.compile(r'^PAGE\s*\(\s*\d+\s*\)$', re.IGNORECASE)


class CutlistParser:
    def __init__(self, file_path):
        self.file_path = str(file_path)
        self.workbook = None
        self.format_type = None
        self._print_area_map = {}  # sheet_index -> (row_start, row_end) 0-indexed

    def parse(self):
        try:
            self.workbook = xlrd.open_workbook(self.file_path, on_demand=False)
        except Exception as e:
            raise ValueError(f"Failed to open {self.file_path}: {e}")

        if not self.workbook.nsheets:
            raise ValueError(f"No sheets found in {self.file_path}")

        # Build print area map from named ranges
        self._build_print_area_map()

        # Find the first non-excluded sheet for version detection and title block
        first_page_sheet = self._find_first_page_sheet()
        if first_page_sheet is None:
            raise ValueError(f"No capturable sheet found in {self.file_path}")

        # Detect format from V1 of first PAGE sheet
        self.format_type = self._detect_format(first_page_sheet)

        # Extract title block from first PAGE sheet
        title_block = self._extract_title_block(first_page_sheet)

        # Process all sheets
        sheets = []
        flags = []

        for sheet_idx in range(self.workbook.nsheets):
            sheet = self.workbook.sheet_by_index(sheet_idx)
            sheet_name = sheet.name

            if self._should_exclude_sheet(sheet_name):
                continue

            is_standard = bool(STANDARD_SHEET_PATTERN.match(sheet_name))
            if not is_standard:
                flags.append({
                    'sheet_name': sheet_name,
                    'flag_type': 'non-standard-sheet',
                    'message': (
                        f"Job {title_block.get('job_number')} – "
                        f"Series {title_block.get('series_number')}: "
                        f"sheet '{sheet_name}' does not match standard naming — may warrant review"
                    )
                })

            print_area = self._print_area_map.get(sheet_idx)
            no_print_area = print_area is None

            edgeband_block = self._get_block_raw(sheet, 2, 13, 5, 17)  # N3:R6
            machining_block = self._get_machining_block(sheet)

            if no_print_area:
                flags.append({
                    'sheet_name': sheet_name,
                    'flag_type': 'no-print-area',
                    'message': (
                        f"Job {title_block.get('job_number')} – "
                        f"Series {title_block.get('series_number')}: "
                        f"sheet '{sheet_name}' has no print area — data extraction skipped"
                    )
                })
                sheet_rows = []
            else:
                sheet_rows = self._extract_rows(sheet, print_area)

            sheets.append({
                'sheet_name': sheet_name,
                'is_standard': is_standard,
                'print_area': f"rows {print_area[0]+1}-{print_area[1]+1}" if print_area else None,
                'print_area_fallback': no_print_area,
                'edgeband_block': edgeband_block,
                'machining_block': machining_block,
                'row_count': len(sheet_rows),
                'rows': sheet_rows,
            })

        return {
            'file_path': self.file_path,
            'title_block': title_block,
            'format_type': self.format_type,
            'sheets': sheets,
            'flags': flags,
            'has_flags': len(flags) > 0,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_print_area_map(self):
        """Read Print_Area named ranges and map sheet_index -> (row_start, row_end)."""
        self._print_area_map = {}
        if not hasattr(self.workbook, 'name_obj_list'):
            return
        for name_obj in self.workbook.name_obj_list:
            if name_obj.name.upper() != 'PRINT_AREA':
                continue
            try:
                result = name_obj.result
                if result is None:
                    continue
                value = result.value
                if not isinstance(value, list) or not value:
                    continue
                for ref in value:
                    if not hasattr(ref, 'shtxlo'):
                        continue
                    sheet_idx = ref.shtxlo
                    row_start = ref.rowxlo      # 0-based inclusive
                    row_end = ref.rowxhi - 1    # rowxhi is exclusive
                    self._print_area_map[sheet_idx] = (row_start, row_end)
            except Exception:
                continue

    def _find_first_page_sheet(self):
        """Return first sheet not in the exclusion list."""
        for i in range(self.workbook.nsheets):
            sheet = self.workbook.sheet_by_index(i)
            if not self._should_exclude_sheet(sheet.name):
                return sheet
        return None

    def _should_exclude_sheet(self, name):
        name_upper = name.upper()
        for prefix in EXCLUDED_SHEET_PREFIXES:
            if name_upper.startswith(prefix.upper()):
                return True
        return False

    def _detect_format(self, sheet):
        """Check V1 (col 21) for version string."""
        v1 = self._cell_str(sheet, 0, 21)
        if not v1:
            return 'traditional'
        v1_lower = v1.lower()
        if 'version' in v1_lower and any(c.isdigit() for c in v1):
            return 'single-sheet'
        if 'version' in v1_lower:
            return 'traditional'
        return 'traditional'

    def _extract_title_block(self, sheet):
        wb = self.workbook
        return {
            'job_name':      self._cell_str(sheet, 0, 4),      # E1
            'job_number':    self._cell_str(sheet, 1, 4),      # E2
            'series_number': self._cell_str(sheet, 3, 4),      # E4
            'room':          self._cell_str(sheet, 4, 4),      # E5
            'vto_reference': self._cell_str(sheet, 0, 6),      # G1 (first cell of G1:H1)
            'area':          self._cell_str(sheet, 0, 15),     # P1 (first cell of P1:U1)
            'cutlist_date':  self._cell_date(sheet, 2, 6, wb), # G3
            'cutlist_by':    self._cell_str(sheet, 2, 7),      # H3
            'checked_date':  self._cell_date(sheet, 3, 6, wb), # G4
            'checked_by':    self._cell_str(sheet, 3, 7),      # H4
            'in_works_date': self._cell_date(sheet, 4, 6, wb), # G5
            'in_works_by':   self._cell_str(sheet, 4, 7),      # H5
            'is_fr':         bool(self._cell_str(sheet, 1, 12)),  # M2
            'is_fsc':        bool(self._cell_str(sheet, 3, 12)), # M4
            'version_number': self._get_version_number(sheet),
        }

    def _get_version_number(self, sheet):
        if self.format_type == 'single-sheet':
            return self._cell_str(sheet, 0, 21)  # V1
        else:
            return self._cell_str(sheet, 0, 22)  # W1

    def _get_machining_block(self, sheet):
        """Extract 8 machining cells as list of strings."""
        # Both formats use the same cell positions for value extraction;
        # in traditional format these are merged ranges but xlrd returns
        # the value in the top-left cell of each range.
        positions = [
            (2, 18), (3, 18), (4, 18), (5, 18),  # S3-S6
            (2, 21), (3, 21), (4, 21), (5, 21),  # V3-V6
        ]
        return [self._cell_str(sheet, r, c) for r, c in positions]

    def _get_block_raw(self, sheet, row_start, col_start, row_end, col_end):
        """Capture a rectangular block as a raw string (rows joined by newline)."""
        lines = []
        for r in range(row_start, row_end + 1):
            parts = [
                self._cell_str(sheet, r, c)
                for c in range(col_start, col_end + 1)
            ]
            row_text = ' '.join(p for p in parts if p)
            if row_text:
                lines.append(row_text)
        return '\n'.join(lines)

    def _extract_rows(self, sheet, print_area):
        """Extract data rows starting at row 8 (index 7) up to print area end."""
        row_start, row_end = print_area
        data_start = max(row_start, 7)  # spec: data always starts row 8 (index 7)

        rows = []
        for row_idx in range(data_start, row_end + 1):
            if self.format_type == 'single-sheet':
                row_data = self._extract_row_single(sheet, row_idx)
            else:
                row_data = self._extract_row_traditional(sheet, row_idx)
            row_data['row_number'] = row_idx + 1  # 1-indexed for display
            rows.append(row_data)
        return rows

    def _extract_row_single(self, sheet, r):
        return {
            'vto':          self._cell_str(sheet, r, 0),            # A
            'fl_rm':        self._cell_str(sheet, r, 1),            # B
            'part_category':self._cell_str(sheet, r, 2),            # C
            'part_component':self._cell_str(sheet, r, 3),           # D
            'description':  self._cell_str(sheet, r, 4),            # E
            'width':        self._cell_str(sheet, r, 5),            # F
            'length':       self._cell_str(sheet, r, 6),            # G
            'thickness':    self._cell_str(sheet, r, 7),            # H
            'material':     self._join_range(sheet, r, 8, 11),      # I:L
            'qty':          self._cell_str(sheet, r, 12),           # M
            'edge_left':    self._cell_str(sheet, r, 13),           # N
            'edge_right':   self._cell_str(sheet, r, 14),           # O
            'edge_top':     self._cell_str(sheet, r, 15),           # P
            'edge_bottom':  self._cell_str(sheet, r, 16),           # Q
            'edge_front':   self._cell_str(sheet, r, 17),           # R
            'edge_back':    self._cell_str(sheet, r, 18),           # S
            'cnc_flag':     self._cell_str(sheet, r, 19),           # T
            'notes':        self._join_range(sheet, r, 20, 21),     # U:V
            'cnc_prog':     self._cell_str(sheet, r, 22),           # W
        }

    def _extract_row_traditional(self, sheet, r):
        return {
            'vto':          self._cell_str(sheet, r, 0),            # A
            'fl_rm':        self._cell_str(sheet, r, 1),            # B
            'part_category':self._cell_str(sheet, r, 2),            # C
            'part_component':self._cell_str(sheet, r, 3),           # D
            'description':  self._cell_str(sheet, r, 4),            # E
            'width':        self._cell_str(sheet, r, 5),            # F
            'length':       self._cell_str(sheet, r, 6),            # G
            'thickness':    self._cell_str(sheet, r, 7),            # H
            'material':     self._join_range(sheet, r, 8, 11),      # I:L
            'qty':          self._cell_str(sheet, r, 12),           # M
            'edge_left':    self._cell_str(sheet, r, 13),           # N
            'edge_right':   self._cell_str(sheet, r, 14),           # O
            'edge_top':     self._cell_str(sheet, r, 15),           # P
            'edge_bottom':  self._cell_str(sheet, r, 16),           # Q
            'edge_front':   self._cell_str(sheet, r, 17),           # R
            'edge_back':    self._cell_str(sheet, r, 18),           # S
            'cnc_flag':     self._cell_str(sheet, r, 19),           # T
            'notes':        self._join_range(sheet, r, 20, 22),     # U:W
            'cnc_prog':     self._cell_str(sheet, r, 23),           # X
        }

    # ------------------------------------------------------------------
    # Low-level cell accessors
    # ------------------------------------------------------------------

    def _cell_str(self, sheet, row, col):
        """Return cell value as a clean string, converting floats to ints where whole."""
        try:
            if row >= sheet.nrows or col >= sheet.ncols:
                return ''
            ctype = sheet.cell_type(row, col)
            value = sheet.cell_value(row, col)
            if ctype == xlrd.XL_CELL_EMPTY:
                return ''
            if ctype == xlrd.XL_CELL_NUMBER:
                # Store whole numbers without decimal (e.g., 2642.0 → "2642")
                if value == int(value):
                    return str(int(value))
                return str(value)
            if ctype == xlrd.XL_CELL_DATE:
                # Dates will be handled by _cell_date; here just return raw
                return str(value)
            return str(value).strip()
        except Exception:
            return ''

    def _cell_date(self, sheet, row, col, workbook):
        """Return cell value as ISO date string if it looks like an Excel date."""
        try:
            if row >= sheet.nrows or col >= sheet.ncols:
                return ''
            ctype = sheet.cell_type(row, col)
            value = sheet.cell_value(row, col)
            if ctype == xlrd.XL_CELL_DATE:
                dt = xlrd.xldate_as_datetime(value, workbook.datemode)
                return dt.strftime('%Y-%m-%d')
            if ctype == xlrd.XL_CELL_NUMBER and value > 20000:
                # Likely an unformatted date serial
                dt = xlrd.xldate_as_datetime(value, workbook.datemode)
                return dt.strftime('%Y-%m-%d')
            return self._cell_str(sheet, row, col)
        except Exception:
            return self._cell_str(sheet, row, col)

    def _join_range(self, sheet, row, col_start, col_end):
        """Read each cell in a column range and join non-empty values with ' | '."""
        parts = [self._cell_str(sheet, row, c) for c in range(col_start, col_end + 1)]
        return ' | '.join(p for p in parts if p)
