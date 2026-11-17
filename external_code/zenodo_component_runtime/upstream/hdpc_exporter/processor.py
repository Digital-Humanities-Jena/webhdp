"""
Core processor for HDPC CSV Exporter component.
Handles extraction and export of data from HDPC database files to CSV format.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import pandas as pd


class HDPCCSVExporter:
    """Exports data from HDPC database files to CSV format."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize exporter with configuration.

        Args:
            config: Dictionary containing processing parameters
        """
        self.config = config
        self.export_mode = config.get("export_mode", "files_overview")
        self.include_tables = config.get("include_tables", ["source_files"])
        self.custom_columns = config.get("custom_columns", "")
        self.custom_sql_query = config.get("custom_sql_query", "")
        self.include_project_info = config.get("include_project_info", True)
        self.filter_status = config.get("filter_status", "")
        self.date_range_start = config.get("date_range_start", "")
        self.date_range_end = config.get("date_range_end", "")
        self.max_rows = config.get("max_rows", 0)
        self.verbose = config.get("verbose", False)
        self.version = config.get("version", "undefined")

        # Statistics tracking
        self.stats = {
            "total_rows_exported": 0,
            "tables_accessed": [],
            "columns_exported": [],
            "processing_time": 0,
            "errors": [],
            "export_mode_used": self.export_mode,
            "schema_type": "hdpc",
        }

        # Predefined export templates
        self.export_templates = {
            "files_overview": {
                "description": "Overview of all files in the project",
                "base_query": """
                SELECT
                    sf.file_id, sf.filename, sf.relative_path, sf.size_bytes, sf.mime_type,
                    sf.file_type, sf.status, sf.added_timestamp, sf.last_processed_timestamp, sf.error_message
                FROM source_files sf
                """,
                "order_by": "sf.file_id ASC",  # <-- ADD this new key
                "joins": ["project_info pi ON sf.project_id = pi.project_id"],
            },
            "zenodo_records": {
                "description": "Zenodo publication records",
                "base_query": """
                SELECT
                    zr.record_id, zr.zenodo_record_id, zr.zenodo_doi, zr.concept_doi, zr.record_title,
                    zr.record_status, zr.is_sandbox, zr.version, zr.created_timestamp, zr.last_updated_timestamp,
                    sf.filename as source_filename, sf.file_type as source_file_type
                FROM zenodo_records zr
                LEFT JOIN source_files sf ON zr.source_file_id = sf.file_id
                """,
                "joins": ["project_info pi ON zr.project_id = pi.project_id"] if self.include_project_info else [],
            },
            "metadata_export": {
                "description": "Extracted metadata values",
                "base_query": """
                SELECT
                    mv.value_id, sf.filename, mmf.mapping_name, mv.field_name,
                    mv.field_value, mv.extracted_timestamp
                FROM metadata_values mv
                JOIN source_files sf ON mv.source_file_id = sf.file_id
                JOIN metadata_mapping_files mmf ON mv.mapping_id = mmf.mapping_id
                """,
                "joins": ["project_info pi ON sf.project_id = pi.project_id"] if self.include_project_info else [],
            },
            "project_summary": {
                "description": "Project overview with statistics",
                "base_query": """
                SELECT
                    pi.project_name, pi.project_short_code, pi.description, pi.creation_timestamp,
                    pi.last_modified_timestamp, COUNT(DISTINCT sf.file_id) as total_files,
                    COUNT(DISTINCT zr.record_id) as total_zenodo_records, COUNT(DISTINCT b.batch_id) as total_batches
                FROM project_info pi
                LEFT JOIN source_files sf ON pi.project_id = sf.project_id
                LEFT JOIN zenodo_records zr ON pi.project_id = zr.project_id
                LEFT JOIN batches b ON pi.project_id = b.project_id
                """,
                "joins": [],
                "group_by": [
                    "pi.project_id",
                    "pi.project_name",
                    "pi.project_short_code",
                    "pi.description",
                    "pi.creation_timestamp",
                    "pi.last_modified_timestamp",
                ],
            },
            "api_log": {
                "description": "API interaction log",
                "base_query": """
                SELECT
                    al.log_id, al.timestamp, al.http_method, al.endpoint_url, al.response_status_code,
                    al.duration_ms, al.status, zr.zenodo_record_id, sf.filename
                FROM api_log al
                LEFT JOIN zenodo_records zr ON al.record_id = zr.record_id
                LEFT JOIN source_files sf ON al.file_id = sf.file_id
                """,
                "joins": ["project_info pi ON al.project_id = pi.project_id"] if self.include_project_info else [],
            },
        }

    def process(self, hdpc_file_path: str, output_dir: str) -> Dict[str, Any]:
        """Main processing function."""
        start_time = datetime.now()
        try:
            conn = sqlite3.connect(hdpc_file_path)
            self._validate_database_schema(conn)

            query = self.custom_sql_query if self.custom_sql_query else self._build_export_query()
            if self.verbose:
                print(f"🔍 Executing query for {self.export_mode} export...")

            df = pd.read_sql_query(query, conn)
            conn.close()

            if self.max_rows > 0:
                df = df.head(self.max_rows)

            if df.empty:
                raise ValueError("No data found matching the specified criteria")

            output_files = self._generate_output_files(df, hdpc_file_path, output_dir)
            end_time = datetime.now()
            self.stats["processing_time"] = (end_time - start_time).total_seconds()
            self.stats["total_rows_exported"] = len(df)
            self.stats["columns_exported"] = list(df.columns)

            return {
                "success": True,
                "output_files": output_files,
                "rows_exported": len(df),
                "columns_exported": len(df.columns),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _validate_database_schema(self, conn: sqlite3.Connection):
        """Validate that the database has the expected HDPC schema."""
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        expected_tables = ["project_info", "source_files"]
        missing_tables = [table for table in expected_tables if table not in tables]
        if missing_tables:
            raise ValueError(f"Invalid HDPC database: missing required tables: {missing_tables}")
        self.stats["tables_accessed"] = tables
        if self.verbose:
            print(f"✅ Database validated (HDPC schema).")

    def _build_export_query(self) -> str:
        """Build SQL query based on export mode and configuration."""
        if self.export_mode == "custom":
            # This part is simplified; a full implementation would need connection
            # to determine columns if not provided. Assuming custom_columns is sufficient.
            main_table = self.include_tables[0]
            query = f"SELECT {self.custom_columns or '*'} FROM {main_table}"
            return query

        template = self.export_templates[self.export_mode]
        query = template["base_query"]

        if self.include_project_info and template.get("joins"):
            for join in template["joins"]:
                query += f" LEFT JOIN {join}"

        where_clauses = []
        if self.filter_status:
            if "zenodo_records" in query.lower():
                where_clauses.append(f"zr.record_status = '{self.filter_status}'")
            elif "source_files" in query.lower():
                where_clauses.append(f"sf.status = '{self.filter_status}'")
        if self.date_range_start:
            where_clauses.append(f"DATE(created_timestamp) >= '{self.date_range_start}'")
        if self.date_range_end:
            where_clauses.append(f"DATE(created_timestamp) <= '{self.date_range_end}'")

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        if template.get("group_by"):
            query += " GROUP BY " + ", ".join(template["group_by"])

        # Append the ORDER BY clause at the end for correct syntax
        if template.get("order_by"):
            query += " ORDER BY " + template["order_by"]

        return query

    def _generate_output_files(self, df: pd.DataFrame, db_file_path: str, output_dir: str) -> List[str]:
        """Generate output CSV and report files."""
        output_path = Path(output_dir)
        db_stem = Path(db_file_path).stem
        csv_path = output_path / f"{db_stem}_export.csv"
        df.to_csv(csv_path, index=False)
        report_path = self._generate_export_report(df, output_path, db_stem, db_file_path)
        return [str(csv_path), str(report_path)]

    def _generate_export_report(self, df: pd.DataFrame, output_path: Path, hdpc_stem: str, hdpc_file_path: str) -> str:
        """Generate detailed export report."""
        report_path = output_path / f"{hdpc_stem}_export_report.json"
        column_info = {
            col: {
                "dtype": str(df[col].dtype),
                "non_null_count": int(df[col].count()),
            }
            for col in df.columns
        }
        report = {
            "component": "hdpc_csv_exporter",
            "version": self.version,
            "export_timestamp": datetime.now().isoformat(),
            "source_hdpc_file": str(hdpc_file_path),
            "export_configuration": self.config,
            "data_statistics": {
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "column_details": column_info,
            },
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return str(report_path)
