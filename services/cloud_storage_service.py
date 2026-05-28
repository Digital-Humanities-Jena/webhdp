# services/cloud_storage_service.py
"""Cloud storage service for testing connectivity to Google Drive and Dropbox."""

import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class CloudStorageService:
    """Service for testing cloud storage connectivity."""

    @staticmethod
    def test_gdrive_connection() -> Dict[str, Any]:
        """
        Test Google Drive connectivity using Service Account credentials.

        Returns:
            dict: Test result with success status, message, and details
        """
        result = {
            "service": "gdrive",
            "success": False,
            "message": "",
            "details": {}
        }

        # Check for required environment variables
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        folder_id = os.getenv("SHARED_GDRIVE_FOLDER_ID")

        if not credentials_path:
            result["message"] = "GOOGLE_APPLICATION_CREDENTIALS environment variable not set"
            return result

        if not folder_id:
            result["message"] = "SHARED_GDRIVE_FOLDER_ID environment variable not set"
            return result

        if not os.path.exists(credentials_path):
            result["message"] = f"Credentials file not found at: {credentials_path}"
            return result

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError

            SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

            logger.info("🔑 Authenticating with Google Drive using Service Account...")

            # Authenticate using service account
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=SCOPES
            )

            # Build the Drive service
            service = build('drive', 'v3', credentials=credentials)

            # Test: List files in the shared folder
            logger.info(f"📂 Testing access to folder: {folder_id}")

            query = f"'{folder_id}' in parents and trashed = false"
            files_result = service.files().list(
                q=query,
                pageSize=5,
                fields="files(id, name, mimeType)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()

            files = files_result.get('files', [])

            result["success"] = True
            result["message"] = "Successfully connected to Google Drive"
            result["details"] = {
                "folder_id": folder_id,
                "files_found": len(files),
                "sample_files": [{"name": f["name"], "type": f["mimeType"]} for f in files[:5]]
            }

            logger.info(f"✅ Google Drive test passed. Found {len(files)} file(s).")

        except ImportError as e:
            result["message"] = f"Required libraries not installed: {str(e)}"
            logger.error(f"❌ Import error: {e}")
        except HttpError as e:
            result["message"] = f"Google API error: {str(e)}"
            result["details"]["error_code"] = e.resp.status if hasattr(e, 'resp') else None
            logger.error(f"❌ Google Drive API error: {e}")
        except Exception as e:
            result["message"] = f"Connection failed: {str(e)}"
            logger.error(f"❌ Google Drive test failed: {e}", exc_info=True)

        return result

    @staticmethod
    def test_dropbox_connection() -> Dict[str, Any]:
        """
        Test Dropbox connectivity using refresh token authentication.

        Returns:
            dict: Test result with success status, message, and details
        """
        result = {
            "service": "dropbox",
            "success": False,
            "message": "",
            "details": {}
        }

        # Check for required environment variables
        app_key = os.getenv("DROPBOX_APP_KEY")
        app_secret = os.getenv("DROPBOX_APP_SECRET")
        refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")

        missing_vars = []
        if not app_key:
            missing_vars.append("DROPBOX_APP_KEY")
        if not app_secret:
            missing_vars.append("DROPBOX_APP_SECRET")
        if not refresh_token:
            missing_vars.append("DROPBOX_REFRESH_TOKEN")

        if missing_vars:
            result["message"] = f"Missing environment variables: {', '.join(missing_vars)}"
            return result

        try:
            import dropbox
            from dropbox.exceptions import ApiError, AuthError

            logger.info("🔑 Authenticating with Dropbox using refresh token...")

            # Create Dropbox client with refresh token
            dbx = dropbox.Dropbox(
                app_key=app_key,
                app_secret=app_secret,
                oauth2_refresh_token=refresh_token
            )

            # Test: Get current account info
            account = dbx.users_get_current_account()

            # Test: Get space usage
            space_usage = dbx.users_get_space_usage()

            used_bytes = space_usage.used

            # Handle different allocation types (individual vs team)
            allocation = space_usage.allocation
            if allocation.is_individual():
                allocated_bytes = allocation.get_individual().allocated
                allocation_type = "individual"
            elif allocation.is_team():
                # Team allocation - use team allocated space
                team_alloc = allocation.get_team()
                allocated_bytes = team_alloc.allocated
                allocation_type = "team"
            else:
                # Fallback for other allocation types
                allocated_bytes = used_bytes  # Can't determine allocation
                allocation_type = "unknown"

            if allocated_bytes > 0:
                used_gb = round(used_bytes / (1024 ** 3), 2)
                allocated_gb = round(allocated_bytes / (1024 ** 3), 2)
                storage_percentage = round((used_bytes / allocated_bytes) * 100, 1)
            else:
                used_gb = round(used_bytes / (1024 ** 3), 2)
                allocated_gb = 0
                storage_percentage = 0

            result["success"] = True
            result["message"] = "Successfully connected to Dropbox"
            result["details"] = {
                "account_name": account.name.display_name,
                "email": account.email,
                "allocation_type": allocation_type,
                "storage_used_gb": used_gb,
                "storage_allocated_gb": allocated_gb,
                "storage_percentage": storage_percentage
            }

            logger.info(f"✅ Dropbox test passed. Account: {account.name.display_name}")

        except ImportError as e:
            result["message"] = f"Required libraries not installed: {str(e)}"
            logger.error(f"❌ Import error: {e}")
        except AuthError as e:
            result["message"] = f"Authentication failed: {str(e)}"
            logger.error(f"❌ Dropbox auth error: {e}")
        except ApiError as e:
            result["message"] = f"Dropbox API error: {str(e)}"
            logger.error(f"❌ Dropbox API error: {e}")
        except Exception as e:
            result["message"] = f"Connection failed: {str(e)}"
            logger.error(f"❌ Dropbox test failed: {e}", exc_info=True)

        return result
