import sqlite3
import json
from pathlib import Path
from datetime import datetime


class CutlistDatabase:
    def __init__(self, db_path="cutlist.db"):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()

    def create_tables(self):
        conn = self.connect()
        cursor = conn.cursor()

        # Projects table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                job_name TEXT,
                job_number TEXT,
                series_number TEXT,
                room TEXT,
                area TEXT,
                vto_reference TEXT,
                is_fsc BOOLEAN DEFAULT 0,
                is_fr BOOLEAN DEFAULT 0,
                cutlist_by TEXT,
                cutlist_date TEXT,
                checked_by TEXT,
                checked_date TEXT,
                format_type TEXT,
                import_date TEXT,
                has_flags BOOLEAN DEFAULT 0
            )
        """)

        # Sheets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                sheet_name TEXT,
                is_standard BOOLEAN DEFAULT 0,
                print_area TEXT,
                print_area_fallback BOOLEAN DEFAULT 0,
                edgeband_block TEXT,
                machining_block TEXT,
                row_count INTEGER DEFAULT 0,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)

        # Rows table (cutlist data rows)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_id INTEGER NOT NULL,
                row_number INTEGER,
                vto TEXT,
                fl_rm TEXT,
                part_category TEXT,
                part_component TEXT,
                description TEXT,
                width TEXT,
                length TEXT,
                thickness TEXT,
                material TEXT,
                qty TEXT,
                edge_left TEXT,
                edge_right TEXT,
                edge_top TEXT,
                edge_bottom TEXT,
                edge_front TEXT,
                edge_back TEXT,
                cnc_flag TEXT,
                notes TEXT,
                cnc_prog TEXT,
                FOREIGN KEY (sheet_id) REFERENCES sheets(id) ON DELETE CASCADE
            )
        """)

        # FTS5 virtual table (all 19 text columns)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS rows_fts USING fts5(
                vto,
                fl_rm,
                part_category,
                part_component,
                description,
                width,
                length,
                thickness,
                material,
                qty,
                edge_left,
                edge_right,
                edge_top,
                edge_bottom,
                edge_front,
                edge_back,
                cnc_flag,
                notes,
                cnc_prog,
                content='rows',
                content_rowid='id'
            )
        """)

        # Flags table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS flags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                sheet_id INTEGER,
                flag_type TEXT,
                message TEXT,
                resolved BOOLEAN DEFAULT 0,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (sheet_id) REFERENCES sheets(id) ON DELETE CASCADE
            )
        """)

        # FTS5 triggers to keep rows_fts in sync
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS rows_fts_insert AFTER INSERT ON rows BEGIN
                INSERT INTO rows_fts(rowid, vto, fl_rm, part_category, part_component,
                                      description, width, length, thickness, material,
                                      qty, edge_left, edge_right, edge_top, edge_bottom,
                                      edge_front, edge_back, cnc_flag, notes, cnc_prog)
                VALUES (new.id, new.vto, new.fl_rm, new.part_category, new.part_component,
                        new.description, new.width, new.length, new.thickness, new.material,
                        new.qty, new.edge_left, new.edge_right, new.edge_top, new.edge_bottom,
                        new.edge_front, new.edge_back, new.cnc_flag, new.notes, new.cnc_prog);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS rows_fts_delete AFTER DELETE ON rows BEGIN
                DELETE FROM rows_fts WHERE rowid = old.id;
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS rows_fts_update AFTER UPDATE ON rows BEGIN
                DELETE FROM rows_fts WHERE rowid = old.id;
                INSERT INTO rows_fts(rowid, vto, fl_rm, part_category, part_component,
                                      description, width, length, thickness, material,
                                      qty, edge_left, edge_right, edge_top, edge_bottom,
                                      edge_front, edge_back, cnc_flag, notes, cnc_prog)
                VALUES (new.id, new.vto, new.fl_rm, new.part_category, new.part_component,
                        new.description, new.width, new.length, new.thickness, new.material,
                        new.qty, new.edge_left, new.edge_right, new.edge_top, new.edge_bottom,
                        new.edge_front, new.edge_back, new.cnc_flag, new.notes, new.cnc_prog);
            END
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_rows_sheet_rownum ON rows(sheet_id, row_number)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sheets_project ON sheets(project_id)
        """)

        conn.commit()
        return conn

    def insert_project(self, project_data):
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT INTO projects (
                file_path, job_name, job_number, series_number, room, area, vto_reference,
                is_fsc, is_fr, cutlist_by, cutlist_date, checked_by, checked_date,
                format_type, import_date, has_flags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_data['file_path'],
            project_data.get('job_name'),
            project_data.get('job_number'),
            project_data.get('series_number'),
            project_data.get('room'),
            project_data.get('area'),
            project_data.get('vto_reference'),
            project_data.get('is_fsc', False),
            project_data.get('is_fr', False),
            project_data.get('cutlist_by'),
            project_data.get('cutlist_date'),
            project_data.get('checked_by'),
            project_data.get('checked_date'),
            project_data.get('format_type'),
            project_data.get('import_date'),
            project_data.get('has_flags', False)
        ))

        return cursor.lastrowid

    def insert_sheet(self, project_id, sheet_data):
        cursor = self.conn.cursor()

        machining_block_json = json.dumps(sheet_data.get('machining_block', []))

        cursor.execute("""
            INSERT INTO sheets (
                project_id, sheet_name, is_standard, print_area,
                print_area_fallback, edgeband_block, machining_block, row_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            sheet_data.get('sheet_name'),
            sheet_data.get('is_standard', False),
            sheet_data.get('print_area'),
            sheet_data.get('print_area_fallback', False),
            sheet_data.get('edgeband_block'),
            machining_block_json,
            sheet_data.get('row_count', 0)
        ))

        return cursor.lastrowid

    def insert_row(self, sheet_id, row_data):
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT INTO rows (
                sheet_id, row_number, vto, fl_rm, part_category, part_component,
                description, width, length, thickness, material, qty,
                edge_left, edge_right, edge_top, edge_bottom, edge_front, edge_back,
                cnc_flag, notes, cnc_prog
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sheet_id,
            row_data.get('row_number'),
            row_data.get('vto'),
            row_data.get('fl_rm'),
            row_data.get('part_category'),
            row_data.get('part_component'),
            row_data.get('description'),
            row_data.get('width'),
            row_data.get('length'),
            row_data.get('thickness'),
            row_data.get('material'),
            row_data.get('qty'),
            row_data.get('edge_left'),
            row_data.get('edge_right'),
            row_data.get('edge_top'),
            row_data.get('edge_bottom'),
            row_data.get('edge_front'),
            row_data.get('edge_back'),
            row_data.get('cnc_flag'),
            row_data.get('notes'),
            row_data.get('cnc_prog')
        ))

        return cursor.lastrowid

    def insert_flag(self, project_id, flag_data):
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT INTO flags (
                project_id, sheet_id, flag_type, message, resolved
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            project_id,
            flag_data.get('sheet_id'),
            flag_data.get('flag_type'),
            flag_data.get('message'),
            flag_data.get('resolved', False)
        ))

        return cursor.lastrowid

    def project_exists(self, file_path):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM projects WHERE file_path = ?", (file_path,))
        return cursor.fetchone() is not None

    def commit(self):
        if self.conn:
            self.conn.commit()

    def rollback(self):
        if self.conn:
            self.conn.rollback()
