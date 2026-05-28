#!/usr/bin/env python3
"""
Dropbox Advanced Operation Test Script

Features:
1. Standard Upload/Download Integrity Test.
2. "Cloud-Direct" Operation: Uploads a CSV and processes it
   (counts chars/rows) via memory stream without saving a local file.
"""

import os
import sys
import io
import csv
import time
import logging
import random
import string
from dotenv import load_dotenv

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("DropboxOps")

try:
    import dropbox
    from dropbox.files import WriteMode
    from dropbox.exceptions import ApiError, AuthError
except ImportError:
    logger.error("Missing libraries. Run: pip install dropbox python-dotenv")
    sys.exit(1)

# Load configuration
load_dotenv()

class DropboxAdvancedTester:
    def __init__(self):
        self.app_key = os.getenv("DROPBOX_APP_KEY")
        self.app_secret = os.getenv("DROPBOX_APP_SECRET")
        self.refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")

        if not all([self.app_key, self.app_secret, self.refresh_token]):
            logger.critical("❌ Missing Dropbox credentials in .env")
            sys.exit(1)

        self.dbx = self._authenticate()

    def _authenticate(self):
        """Authenticates using Refresh Token."""
        try:
            dbx = dropbox.Dropbox(
                app_key=self.app_key,
                app_secret=self.app_secret,
                oauth2_refresh_token=self.refresh_token
            )
            # Quick check
            dbx.users_get_current_account()
            logger.info("✅ Authenticated with Dropbox successfully.")
            return dbx
        except Exception as e:
            logger.critical(f"❌ Auth Failed: {e}")
            sys.exit(1)

    def generate_random_file(self, size_kb=10):
        """Generates random content in memory."""
        chars = ''.join(random.choices(string.ascii_letters + string.digits, k=1024))
        return (chars * size_kb).encode('utf-8')

    def upload_bytes(self, data, filename):
        """Uploads bytes directly to Dropbox."""
        path = f"/{filename}"
        logger.info(f"📤 Uploading {filename} ({len(data)} bytes)...")
        try:
            self.dbx.files_upload(data, path, mode=WriteMode.overwrite)
            logger.info("   Upload complete.")
            return path
        except ApiError as e:
            logger.error(f"❌ Upload failed: {e}")
            raise

    def download_to_disk(self, dropbox_path, local_filename):
        """Classic download to local disk."""
        logger.info(f"📥 Downloading {dropbox_path} to disk...")
        try:
            self.dbx.files_download_to_file(local_filename, dropbox_path)
            logger.info(f"   Saved to {local_filename}")
        except ApiError as e:
            logger.error(f"❌ Download failed: {e}")
            raise

    def process_csv_in_memory(self, dropbox_path):
        """
        Reads a file from Dropbox directly into memory (Stream)
        and performs operations without saving to disk.
        """
        logger.info(f"☁️  Processing {dropbox_path} directly in-memory...")

        try:
            # metadata, response_object
            md, res = self.dbx.files_download(dropbox_path)

            # res.content holds the bytes in memory
            # We wrap it in BytesIO to treat it like a file
            with io.BytesIO(res.content) as stream:
                # Convert bytes stream to text stream for CSV reader
                text_stream = io.TextIOWrapper(stream, encoding='utf-8')

                reader = csv.reader(text_stream)
                row_count = 0
                char_count = 0

                # Iterate through rows directly from the stream
                for row in reader:
                    row_count += 1
                    char_count += sum(len(cell) for cell in row)

            logger.info(f"   ✅ Analysis Result: {row_count} rows, {char_count} characters.")
            return row_count, char_count

        except ApiError as e:
            logger.error(f"❌ Cloud processing failed: {e}")
            raise

    def cleanup(self, filename):
        path = f"/{filename}"
        try:
            self.dbx.files_delete_v2(path)
            logger.info(f"🗑️  Deleted remote file: {path}")
        except:
            pass

def main():
    tester = DropboxAdvancedTester()

    print("="*60)
    print("TEST 1: Standard File Integrity (Upload -> Disk -> Verify)")
    print("="*60)

    # Generate random binary data
    test_filename = "test_integrity.bin"
    raw_data = tester.generate_random_file(size_kb=5)

    # 1. Upload
    tester.upload_bytes(raw_data, test_filename)

    # 2. Download to disk
    local_out = "downloaded_test.bin"
    tester.download_to_disk(f"/{test_filename}", local_out)

    # 3. Verify
    with open(local_out, 'rb') as f:
        disk_data = f.read()

    if raw_data == disk_data:
        logger.info("✅ Integrity Check PASSED (Binary match)")
    else:
        logger.error("❌ Integrity Check FAILED")

    # Cleanup Test 1
    os.remove(local_out)
    tester.cleanup(test_filename)

    print("\n" + "="*60)
    print("TEST 2: Cloud-Direct CSV Operation (No Disk Usage)")
    print("="*60)

    # Create a CSV in memory
    csv_filename = "data_analysis.csv"
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["ID", "Name", "Role", "Score"]) # Header
    writer.writerow(["101", "Alice", "Engineer", "95"])
    writer.writerow(["102", "Bob", "Designer", "88"])
    writer.writerow(["103", "Charlie", "Manager", "91"])

    csv_content = csv_buffer.getvalue().encode('utf-8')
    expected_rows = 4  # Header + 3 data rows

    # 1. Upload the CSV bytes
    tester.upload_bytes(csv_content, csv_filename)

    # 2. Process "in cloud" (Memory Stream)
    # This reads the file from Dropbox into RAM and counts without a temp file
    rows_found, chars_found = tester.process_csv_in_memory(f"/{csv_filename}")

    if rows_found == expected_rows:
        logger.info(f"✅ CSV Logic Check PASSED (Found {rows_found} rows)")
    else:
        logger.error(f"❌ CSV Logic Check FAILED (Expected {expected_rows}, got {rows_found})")

    # Cleanup Test 2
    tester.cleanup(csv_filename)

if __name__ == "__main__":
    main()