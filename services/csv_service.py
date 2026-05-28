# services/csv_service.py
import csv
import os
import logging
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class CSVService:
    """
    Service for maintaining a session tracking CSV file.
    Tracks: Original Filename, Record ID, DOI, File Links
    """

    FIELDNAMES = ["original_filename", "record_id", "doi", "file_links", "last_updated"]

    def __init__(self, session_dir: str):
        self.session_dir = session_dir
        self.csv_path = os.path.join(session_dir, "session_tracking.csv")
        self._ensure_csv_exists()

    def _ensure_csv_exists(self):
        """Creates the CSV with headers if it doesn't exist."""
        if not os.path.exists(self.csv_path):
            try:
                with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                    writer.writeheader()
                logger.info(f"Created session tracking CSV at {self.csv_path}")
            except Exception as e:
                logger.error(f"Failed to create tracking CSV: {e}")

    def update_tracking_csv(self, records_data: List[Dict[str, Any]]):
        """
        Updates the tracking CSV with a batch of record data.

        Args:
            records_data: List of dicts containing:
                - filename (original)
                - id (record id)
                - doi (optional)
                - links (optional dict or string)
        """
        try:
            # Read existing to check for duplicates (simple inefficient set method for now, sufficient for 1000 rows)
            existing_rows = {}
            if os.path.exists(self.csv_path):
                with open(self.csv_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # KEY: Use record_id as key if available, else filename
                        key = row.get("record_id") or row.get("original_filename")
                        if key:
                            existing_rows[key] = row

            # Update/Add new rows
            for record in records_data:
                # Extract relevant data with fallbacks
                record_id = str(record.get("id") or record.get("record_id", ""))
                filename = record.get("filename") or record.get("title", "Unknown") # specific logic depends on what HDP returns

                # If we don't have a filename but have ID, try to preserve existing filename
                if not filename and record_id in existing_rows:
                    filename = existing_rows[record_id].get("original_filename", "")

                doi = record.get("doi") or record.get("metadata", {}).get("doi", "")
                links = record.get("links", "")

                # Format links if it's a dict
                if isinstance(links, dict):
                    import json
                    links = json.dumps(links)

                row_data = {
                    "original_filename": filename,
                    "record_id": record_id,
                    "doi": doi,
                    "file_links": str(links),
                    "last_updated": datetime.now().isoformat()
                }

                # Upsert logic
                key = record_id if record_id else filename
                existing_rows[key] = row_data

            # Write all back
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()
                writer.writerows(list(existing_rows.values()))

            logger.info(f"Updated tracking CSV with {len(records_data)} records")

        except Exception as e:
            logger.error(f"Failed to update tracking CSV: {e}", exc_info=True)
