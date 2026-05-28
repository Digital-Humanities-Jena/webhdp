#!/usr/bin/env python3
"""
Google Drive User Authentication Test Script (token.json)

This script verifies that the application can use the 'token.json' file
to upload files to a shared folder using the owner's storage quota.
"""

import os
import sys
import tempfile
import logging
import time
from pathlib import Path

# Configure Enhanced Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("GDriveUserAuth")

try:
    from dotenv import load_dotenv
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    from googleapiclient.errors import HttpError
except ImportError as e:
    logger.error(f"Missing required libraries: {e}")
    print("Please run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2 python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv()

SHARED_FOLDER_ID = os.getenv("SHARED_GDRIVE_FOLDER_ID")
TOKEN_FILE = "token.json"
SCOPES = ['https://www.googleapis.com/auth/drive.file']  # Or 'drive' if you used that for setup

class GDriveUserTester:
    def __init__(self):
        self.folder_id = SHARED_FOLDER_ID
        self.service = self._authenticate()

    def _authenticate(self):
        """Authenticates using the user's token.json"""
        logger.info("🔑 Authenticating using User Credentials (token.json)...")

        if not os.path.exists(TOKEN_FILE):
            logger.critical(f"❌ File '{TOKEN_FILE}' not found! Please run setup_auth.py first.")
            sys.exit(1)

        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

            # Auto-refresh token if expired
            if creds and creds.expired and creds.refresh_token:
                logger.info("♻️  Token expired, refreshing automatically...")
                creds.refresh(Request())

                # Optionally save the refreshed token back
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
                logger.info("✅ Refreshed token saved.")

            service = build('drive', 'v3', credentials=creds)
            return service

        except Exception as e:
            logger.critical(f"❌ Authentication Failed: {e}", exc_info=True)
            sys.exit(1)

    def list_files(self):
        """Lists files in the shared folder to verify read access."""
        logger.info(f"📂 Scanning folder: {self.folder_id}...")

        if not self.folder_id:
            logger.error("❌ SHARED_GDRIVE_FOLDER_ID is missing in .env")
            return

        try:
            query = f"'{self.folder_id}' in parents and trashed = false"
            results = self.service.files().list(
                q=query,
                fields="files(id, name, size, mimeType)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()

            files = results.get("files", [])
            logger.info(f"   Found {len(files)} file(s).")
            for f in files:
                logger.info(f"      - {f['name']} (ID: {f['id']}, Type: {f['mimeType']})")
            return files

        except HttpError as error:
            logger.error(f"❌ API Error listing files: {error}")
            return []

    def upload_file(self, local_path):
        """Uploads a file to the shared folder."""
        logger.info(f"📤 Starting upload test: {local_path}")

        file_metadata = {
            "name": os.path.basename(local_path),
            "parents": [self.folder_id]  # This places it in YOUR folder
        }

        media = MediaFileUpload(local_path, resumable=True)

        try:
            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, name, size",
                supportsAllDrives=True
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.info(f"   ⏳ Upload progress: {int(status.progress() * 100)}%")

            logger.info(f"✅ Upload Complete! File ID: {response['id']}")
            return response

        except HttpError as error:
            logger.error(f"❌ Upload Failed: {error}")
            if "storageQuotaExceeded" in str(error):
                logger.error("🚨 Storage Quota Error still occurring. Check your account storage.")
            raise

    def download_file(self, file_id, file_name):
        """Downloads the file back to verify data integrity."""
        logger.info(f"📥 Downloading file: {file_name} ({file_id})")

        try:
            request = self.service.files().get_media(fileId=file_id)

            # Create a temporary file for download
            fd, path = tempfile.mkstemp(prefix="download_test_")
            with os.fdopen(fd, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    if status:
                        logger.info(f"   ⏳ Download progress: {int(status.progress() * 100)}%")

            logger.info(f"✅ Download successful to: {path}")
            return path
        except HttpError as error:
            logger.error(f"❌ Download Failed: {error}")
            raise

    def cleanup(self, file_id):
        """Deletes the test file."""
        logger.info(f"🗑️  Cleaning up (Deleting file {file_id})...")
        try:
            self.service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            logger.info("✅ Cleanup successful.")
        except HttpError as error:
            logger.warning(f"⚠️ Cleanup failed: {error}")

def main():
    print("="*60)
    print(" GOOGLE DRIVE USER AUTH TEST (token.json)")
    print("="*60)

    tester = GDriveUserTester()

    # Create a dummy file
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix=".txt") as tmp:
        tmp.write("This is a test of the HDP Cloud Storage integration using User Auth.")
        tmp_path = tmp.name

    try:
        # 1. Test List
        tester.list_files()

        # 2. Test Upload
        uploaded_file = tester.upload_file(tmp_path)

        # 3. Test Download
        downloaded_path = tester.download_file(uploaded_file['id'], uploaded_file['name'])

        # Compare sizes
        orig_size = os.path.getsize(tmp_path)
        down_size = os.path.getsize(downloaded_path)

        if orig_size == down_size:
            logger.info(f"✅ Integrity Check Passed: Size {orig_size} bytes matches.")
        else:
            logger.error(f"❌ Integrity Check Failed: {orig_size} vs {down_size}")

        # 4. Cleanup Cloud
        tester.cleanup(uploaded_file['id'])

    except Exception as e:
        logger.error(f"💥 Test Failed: {e}")
    finally:
        # Cleanup local temp files
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if 'downloaded_path' in locals() and os.path.exists(downloaded_path):
            os.remove(downloaded_path)

if __name__ == "__main__":
    main()