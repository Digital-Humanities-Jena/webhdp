# services/cloud_upload_service.py
"""Cloud upload service for handling file uploads to Dropbox and Google Drive."""

import os
import hashlib
import logging
import json
import re
from typing import Dict, Any, Optional, Tuple, BinaryIO
from pathlib import Path
from uuid import uuid4

from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer

from database.database import db
from database.models import SystemConfig
from exceptions import SecurityError
from security import sanitize_upload_filename

logger = logging.getLogger(__name__)

# Storage type constants
STORAGE_DROPBOX = "dropbox"
STORAGE_GDRIVE = "gdrive"
STORAGE_SERVER = "server"

# Storage mode constants
# - pure_cloud: Upload directly to cloud, minimal server storage (only temp during processing)
# - cloud_backup: Keep files on server AND upload to cloud (backup mode)
# - server_only: Only use server storage, no cloud upload
STORAGE_MODE_PURE_CLOUD = "pure_cloud"
STORAGE_MODE_CLOUD_BACKUP = "cloud_backup"
STORAGE_MODE_SERVER_ONLY = "server_only"
STORAGE_MODE_LOCAL = "local"

DEFAULT_STORAGE_CONFIG = {
    "primary_storage": STORAGE_DROPBOX,
    "secondary_storage": STORAGE_GDRIVE,
    "allow_server_fallback": False,  # Changed to False for pure_cloud default
    "storage_mode": STORAGE_MODE_PURE_CLOUD  # Default to pure cloud
}


def _stream_receipts():
    return URLSafeTimedSerializer(current_app.secret_key, salt='webhdp-stream-upload',
                                  signer_kwargs={'digest_method': hashlib.sha256})


def issue_stream_receipt(user_id: int, filename: str, result: dict, *, size_bytes: int | None = None) -> str:
    provider = result.get('storage_type')
    path = result.get('remote_path') if provider == STORAGE_DROPBOX else result.get('file_id')
    if (provider not in {STORAGE_DROPBOX, STORAGE_GDRIVE} or not isinstance(path, str) or not path
            or (provider == STORAGE_DROPBOX and not path.startswith('/hdp_uploads/'))
            or (provider == STORAGE_GDRIVE and not re.fullmatch(r'[A-Za-z0-9_-]+', path))):
        raise ValueError('Streaming provider did not return a managed cloud object reference')
    payload = {'user': user_id, 'path': path, 'provider': provider, 'name': filename}
    if size_bytes is not None:
        payload['size_bytes'] = size_bytes
    return _stream_receipts().dumps(payload)


def read_stream_receipt(value: str, user_id: int) -> dict:
    try:
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise BadData('Missing or invalid receipt')
        payload = _stream_receipts().loads(value, max_age=3600)
        if payload.get('user') != user_id:
            raise BadData('Receipt belongs to another account')
        return payload
    except BadData as exc:
        raise SecurityError('Upload the file through WebHDP to obtain a valid cloud upload receipt.') from exc


class CloudUploadService:
    """Service for uploading files to cloud storage (Dropbox/Google Drive)."""

    CONFIG_KEY = "storage_config"

    @classmethod
    def get_storage_config(cls) -> Dict[str, Any]:
        """
        Get the current storage configuration from database.

        Returns:
            dict: Storage configuration with primary_storage, secondary_storage,
                  and allow_server_fallback keys
        """
        try:
            config_entry = db.session.get(SystemConfig, cls.CONFIG_KEY)
        except RuntimeError as exc:
            logger.warning("Storage config unavailable from database, using defaults: %s", exc)
            return DEFAULT_STORAGE_CONFIG.copy()
        if config_entry and config_entry.value:
            try:
                return json.loads(config_entry.value)
            except json.JSONDecodeError:
                logger.error("Failed to decode storage config, using defaults")
        return DEFAULT_STORAGE_CONFIG.copy()

    @classmethod
    def save_storage_config(cls, config: Dict[str, Any]) -> None:
        """
        Save storage configuration to database.

        Args:
            config: Configuration dict with storage preferences
        """
        config_entry = db.session.get(SystemConfig, cls.CONFIG_KEY)
        if not config_entry:
            config_entry = SystemConfig(key=cls.CONFIG_KEY)
            db.session.add(config_entry)

        config_entry.value = json.dumps(config)
        db.session.commit()
        logger.info(f"Storage config saved: {config}")

    @staticmethod
    def check_dropbox_available() -> Tuple[bool, str]:
        """
        Check if Dropbox is configured and accessible.

        Returns:
            tuple: (is_available, message)
        """
        app_key = os.getenv("DROPBOX_APP_KEY")
        app_secret = os.getenv("DROPBOX_APP_SECRET")
        refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")

        if not all([app_key, app_secret, refresh_token]):
            missing = []
            if not app_key:
                missing.append("DROPBOX_APP_KEY")
            if not app_secret:
                missing.append("DROPBOX_APP_SECRET")
            if not refresh_token:
                missing.append("DROPBOX_REFRESH_TOKEN")
            return False, f"Missing environment variables: {', '.join(missing)}"

        try:
            import dropbox
            from dropbox.exceptions import AuthError

            dbx = dropbox.Dropbox(
                app_key=app_key,
                app_secret=app_secret,
                oauth2_refresh_token=refresh_token
            )

            # Constructing the SDK client does not authenticate it.
            dbx.users_get_current_account()
            return True, "Connected"

        except ImportError:
            return False, "Dropbox library not installed"
        except AuthError as e:
            return False, f"Authentication failed: {str(e)}"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    @staticmethod
    def check_gdrive_available() -> Tuple[bool, str]:
        """
        Check if Google Drive is configured and accessible.

        Returns:
            tuple: (is_available, message)
        """
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        folder_id = os.getenv("SHARED_GDRIVE_FOLDER_ID")

        if not credentials_path:
            return False, "GOOGLE_APPLICATION_CREDENTIALS not set"
        if not folder_id:
            return False, "SHARED_GDRIVE_FOLDER_ID not set"
        if not os.path.exists(credentials_path):
            return False, f"Credentials file not found: {credentials_path}"

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError

            SCOPES = ['https://www.googleapis.com/auth/drive']

            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=SCOPES
            )

            service = build('drive', 'v3', credentials=credentials)

            # Quick check - get folder metadata
            folder = service.files().get(
                fileId=folder_id,
                supportsAllDrives=True
            ).execute()

            return True, f"Connected to folder: {folder.get('name', folder_id)}"

        except ImportError:
            return False, "Google API libraries not installed"
        except HttpError as e:
            return False, f"API error: {str(e)}"
        except Exception as e:
            return False, f"Connection error: {str(e)}"

    @classmethod
    def get_available_storage(cls) -> Tuple[Optional[str], str]:
        """
        Get the first available storage based on configuration priority.

        Returns:
            tuple: (storage_type or None, message)
                   storage_type is one of: 'dropbox', 'gdrive', 'server', or None
        """
        config = cls.get_storage_config()

        primary = config.get("primary_storage", STORAGE_DROPBOX)
        secondary = config.get("secondary_storage", STORAGE_GDRIVE)
        allow_fallback = config.get("allow_server_fallback", True)

        if cls.get_storage_mode() == STORAGE_MODE_LOCAL:
            return STORAGE_SERVER, "Local storage mode enabled"

        # Check primary storage
        if primary == STORAGE_DROPBOX:
            available, msg = cls.check_dropbox_available()
            if available:
                return STORAGE_DROPBOX, f"Using Dropbox (primary): {msg}"
        elif primary == STORAGE_GDRIVE:
            available, msg = cls.check_gdrive_available()
            if available:
                return STORAGE_GDRIVE, f"Using Google Drive (primary): {msg}"

        # Check secondary storage
        if secondary == STORAGE_DROPBOX:
            available, msg = cls.check_dropbox_available()
            if available:
                return STORAGE_DROPBOX, f"Using Dropbox (secondary): {msg}"
        elif secondary == STORAGE_GDRIVE:
            available, msg = cls.check_gdrive_available()
            if available:
                return STORAGE_GDRIVE, f"Using Google Drive (secondary): {msg}"

        # Check server fallback
        if allow_fallback:
            return STORAGE_SERVER, "Using server internal storage (fallback)"

        return None, "No storage available. Configure cloud storage or enable server fallback."

    @staticmethod
    def upload_to_dropbox(local_path: str, remote_path: str) -> Dict[str, Any]:
        """
        Upload a file to Dropbox.

        Args:
            local_path: Path to local file
            remote_path: Destination path in Dropbox (e.g., "/uploads/file.zip")

        Returns:
            dict: Upload result with success, remote_url, file_id
        """
        result = {
            "success": False,
            "storage_type": STORAGE_DROPBOX,
            "remote_path": remote_path,
            "remote_url": None,
            "file_id": None,
            "message": ""
        }

        try:
            import dropbox
            from dropbox.files import WriteMode

            app_key = os.getenv("DROPBOX_APP_KEY")
            app_secret = os.getenv("DROPBOX_APP_SECRET")
            refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")

            dbx = dropbox.Dropbox(
                app_key=app_key,
                app_secret=app_secret,
                oauth2_refresh_token=refresh_token
            )

            file_size = os.path.getsize(local_path)
            CHUNK_SIZE = 150 * 1024 * 1024  # 150 MB chunks for large files

            with open(local_path, 'rb') as f:
                if file_size <= CHUNK_SIZE:
                    # Small file - single upload
                    metadata = dbx.files_upload(
                        f.read(),
                        remote_path,
                        mode=WriteMode.overwrite
                    )
                else:
                    # Large file - chunked upload
                    logger.info(f"Starting chunked upload for {file_size / (1024**3):.2f} GB file")

                    session_start = dbx.files_upload_session_start(f.read(CHUNK_SIZE))
                    cursor = dropbox.files.UploadSessionCursor(
                        session_id=session_start.session_id,
                        offset=f.tell()
                    )
                    commit = dropbox.files.CommitInfo(
                        path=remote_path,
                        mode=WriteMode.overwrite
                    )

                    while f.tell() < file_size:
                        remaining = file_size - f.tell()
                        if remaining <= CHUNK_SIZE:
                            # Final chunk
                            metadata = dbx.files_upload_session_finish(
                                f.read(remaining),
                                cursor,
                                commit
                            )
                        else:
                            dbx.files_upload_session_append_v2(
                                f.read(CHUNK_SIZE),
                                cursor
                            )
                            cursor.offset = f.tell()

            # Keep stored artifacts private. Authorized download routes request
            # temporary links when needed instead of publishing a shared link.
            result["remote_url"] = f"dropbox://{remote_path}"

            result["success"] = True
            result["file_id"] = metadata.id
            result["message"] = f"Uploaded successfully to {remote_path}"
            logger.info(f"✅ Dropbox upload complete: {remote_path}")

        except Exception as e:
            result["message"] = f"Upload failed: {str(e)}"
            logger.error(f"❌ Dropbox upload failed: {e}", exc_info=True)

        return result

    @staticmethod
    def upload_to_gdrive(local_path: str, remote_filename: str) -> Dict[str, Any]:
        """
        Upload a file to Google Drive.

        Args:
            local_path: Path to local file
            remote_filename: Filename in Google Drive folder

        Returns:
            dict: Upload result with success, file_id, remote_url
        """
        result = {
            "success": False,
            "storage_type": STORAGE_GDRIVE,
            "remote_path": remote_filename,
            "remote_url": None,
            "file_id": None,
            "message": ""
        }

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            folder_id = os.getenv("SHARED_GDRIVE_FOLDER_ID")

            SCOPES = ['https://www.googleapis.com/auth/drive']

            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=SCOPES
            )

            service = build('drive', 'v3', credentials=credentials)

            # File metadata
            file_metadata = {
                'name': remote_filename,
                'parents': [folder_id]
            }

            # Determine MIME type
            mime_type = 'application/zip' if local_path.endswith('.zip') else 'application/octet-stream'

            # Use resumable upload for large files
            media = MediaFileUpload(
                local_path,
                mimetype=mime_type,
                resumable=True,
                chunksize=256 * 1024 * 1024  # 256 MB chunks
            )

            logger.info(f"Starting Google Drive upload: {remote_filename}")

            request = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink',
                supportsAllDrives=True
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.info(f"Upload progress: {int(status.progress() * 100)}%")

            result["success"] = True
            result["file_id"] = response.get('id')
            result["remote_url"] = response.get('webViewLink')
            result["message"] = f"Uploaded successfully as {response.get('name')}"
            logger.info(f"✅ Google Drive upload complete: {result['file_id']}")

        except Exception as e:
            result["message"] = f"Upload failed: {str(e)}"
            logger.error(f"❌ Google Drive upload failed: {e}", exc_info=True)

        return result

    @classmethod
    def upload_file(cls, local_path: str, remote_name: str) -> Dict[str, Any]:
        """
        Upload a file to the best available storage.

        Args:
            local_path: Path to local file
            remote_name: Desired remote filename

        Returns:
            dict: Upload result with storage_type, success, and details
        """
        remote_name = sanitize_upload_filename(remote_name)
        storage_type, message = cls.get_available_storage()

        if storage_type is None:
            return {
                "success": False,
                "storage_type": None,
                "message": message
            }

        logger.info(f"Selected storage: {storage_type} - {message}")

        if storage_type == STORAGE_DROPBOX:
            remote_path = f"/hdp_uploads/{uuid4().hex}-{remote_name}"
            return cls.upload_to_dropbox(local_path, remote_path)

        elif storage_type == STORAGE_GDRIVE:
            return cls.upload_to_gdrive(local_path, remote_name)

        elif storage_type == STORAGE_SERVER:
            # Server storage - file is already local, just return info
            return {
                "success": True,
                "storage_type": STORAGE_SERVER,
                "remote_path": local_path,
                "remote_url": None,
                "file_id": None,
                "message": "File stored on server"
            }

        return {
            "success": False,
            "storage_type": None,
            "message": "Unknown storage type"
        }

    @classmethod
    def get_storage_mode(cls) -> str:
        """
        Get the current storage mode from configuration,
        prioritizing app config/environment variables.

        Returns:
            str: One of 'pure_cloud', 'cloud_backup', 'server_only', or 'local'
        """
        from flask import current_app
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
        from database.models import User
        from services.hdp_component_policy import (
            DEPLOYMENT_CLASS_WORKSTATION_LOCAL,
            webhdp_deployment_class,
        )

        # Check user role if request context is available
        try:
            verify_jwt_in_request(optional=True)
            user_id = get_jwt_identity()
            if user_id:
                user = db.session.get(User, int(user_id))
                # Hosted server/VPS deployments keep non-admin users on cloud
                # upload storage. Explicit workstation-local deployments may use
                # mounted local folders for non-admin workflows.
                if (
                    user
                    and user.role.value != "admin"
                    and webhdp_deployment_class(current_app) != DEPLOYMENT_CLASS_WORKSTATION_LOCAL
                ):
                    return STORAGE_MODE_PURE_CLOUD
        except Exception:
            # If outside request context or auth fail, ignore and use config
            pass

        try:
            # Check Flask config first (which loads from environment in config.py)
            if current_app and "STORAGE_MODE" in current_app.config:
                return current_app.config["STORAGE_MODE"]
        except (RuntimeError, KeyError):
            pass

        # Fallback to database config
        config = cls.get_storage_config()
        return config.get("storage_mode", STORAGE_MODE_PURE_CLOUD)

    @classmethod
    def should_keep_server_copy(cls) -> bool:
        """
        Check if files should be kept on server after upload.

        Returns:
            bool: True if server copy should be retained
        """
        mode = cls.get_storage_mode()
        return mode in [STORAGE_MODE_CLOUD_BACKUP, STORAGE_MODE_SERVER_ONLY]

    @classmethod
    def should_upload_to_cloud(cls) -> bool:
        """
        Check if files should be uploaded to cloud storage.

        Returns:
            bool: True if cloud upload is required
        """
        mode = cls.get_storage_mode()
        return mode in [STORAGE_MODE_PURE_CLOUD, STORAGE_MODE_CLOUD_BACKUP]

    @staticmethod
    def stream_upload_to_dropbox(file_stream: BinaryIO, remote_path: str, file_size: int) -> Dict[str, Any]:
        """
        Stream upload a file directly to Dropbox without saving to disk.

        Args:
            file_stream: File-like object to upload
            remote_path: Destination path in Dropbox
            file_size: Total file size in bytes

        Returns:
            dict: Upload result
        """
        result = {
            "success": False,
            "storage_type": STORAGE_DROPBOX,
            "remote_path": remote_path,
            "remote_url": None,
            "file_id": None,
            "message": ""
        }

        try:
            import dropbox
            from dropbox.files import WriteMode

            app_key = os.getenv("DROPBOX_APP_KEY")
            app_secret = os.getenv("DROPBOX_APP_SECRET")
            refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")

            dbx = dropbox.Dropbox(
                app_key=app_key,
                app_secret=app_secret,
                oauth2_refresh_token=refresh_token
            )

            CHUNK_SIZE = 150 * 1024 * 1024  # 150 MB chunks

            if file_size <= CHUNK_SIZE:
                # Small file - single upload
                data = file_stream.read()
                metadata = dbx.files_upload(
                    data,
                    remote_path,
                    mode=WriteMode.overwrite
                )
            else:
                # Large file - chunked upload
                logger.info(f"Starting streaming chunked upload for {file_size / (1024**3):.2f} GB file")

                first_chunk = file_stream.read(CHUNK_SIZE)
                session_start = dbx.files_upload_session_start(first_chunk)
                cursor = dropbox.files.UploadSessionCursor(
                    session_id=session_start.session_id,
                    offset=len(first_chunk)
                )
                commit = dropbox.files.CommitInfo(
                    path=remote_path,
                    mode=WriteMode.overwrite
                )

                bytes_uploaded = len(first_chunk)
                while bytes_uploaded < file_size:
                    chunk = file_stream.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    remaining = file_size - bytes_uploaded
                    if len(chunk) >= remaining or len(chunk) < CHUNK_SIZE:
                        # Final chunk
                        metadata = dbx.files_upload_session_finish(
                            chunk,
                            cursor,
                            commit
                        )
                    else:
                        dbx.files_upload_session_append_v2(chunk, cursor)
                        cursor.offset += len(chunk)

                    bytes_uploaded += len(chunk)
                    logger.info(f"Streaming upload progress: {bytes_uploaded / file_size * 100:.1f}%")

            # Keep stored artifacts private. Authorized download routes request
            # temporary links when needed instead of publishing a shared link.
            result["remote_url"] = f"dropbox://{remote_path}"

            result["success"] = True
            result["file_id"] = metadata.id
            result["message"] = f"Streamed successfully to {remote_path}"
            logger.info(f"✅ Dropbox streaming upload complete: {remote_path}")

        except Exception as e:
            result["message"] = f"Stream upload failed: {str(e)}"
            logger.error(f"❌ Dropbox streaming upload failed: {e}", exc_info=True)

        return result

    @classmethod
    def stream_upload_to_gdrive(cls, file_stream: BinaryIO, remote_name: str, file_size: int) -> Dict[str, Any]:
        """
        Stream upload to Google Drive using MediaIoBaseUpload.
        """
        result = {"success": False, "storage_type": STORAGE_GDRIVE}

        try:
            drive_service, msg = cls.get_gdrive_service()
            if not drive_service:
                result["message"] = msg
                return result

            # Get config for shared folder
            config = cls.get_storage_config()
            folder_id = config.get("gdrive_folder_id") or os.getenv("SHARED_GDRIVE_FOLDER_ID")

            if not folder_id:
                result["message"] = "Google Drive folder ID not configured"
                return result

            # Prepare metadata
            file_metadata = {
                'name': remote_name,
                'parents': [folder_id]
            }

            # Create resumable media upload
            # chunk_size needs to be multiple of 256*1024
            chunk_size = 5 * 1024 * 1024 # 5MB chunks

            from googleapiclient.http import MediaIoBaseUpload
            media = MediaIoBaseUpload(
                file_stream,
                mimetype='application/octet-stream',
                chunksize=chunk_size,
                resumable=True
            )

            logger.info(f"Starting GDrive streaming upload: {remote_name} ({file_size} bytes)")

            file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webContentLink, webViewLink'
            ).execute()

            result["success"] = True
            result["file_id"] = file.get('id')
            result["remote_path"] = file.get('id') # GDrive uses ID as path ref
            result["remote_url"] = file.get('webContentLink')
            result["message"] = f"Streamed successfully to Google Drive (ID: {file.get('id')})"

            logger.info(f"✅ GDrive streaming upload complete: {result['file_id']}")

        except Exception as e:
            result["message"] = f"GDrive stream failed: {str(e)}"
            logger.error(f"❌ GDrive streaming upload failed: {e}", exc_info=True)

        return result

    @classmethod
    def stream_upload_file(cls, file_stream: BinaryIO, remote_name: str, file_size: int) -> Dict[str, Any]:
        """
        Stream upload a file to the best available cloud storage.

        Args:
            file_stream: File-like object to upload
            remote_name: Desired remote filename
            file_size: Total file size in bytes

        Returns:
            dict: Upload result with storage_type, success, and details
        """
        remote_name = sanitize_upload_filename(remote_name)
        storage_type, message = cls.get_available_storage()

        if storage_type is None or storage_type == STORAGE_SERVER:
            return {
                "success": False,
                "storage_type": storage_type,
                "message": f"Streaming upload requires cloud storage. {message}"
            }

        logger.info(f"Streaming to: {storage_type} - {message}")

        if storage_type == STORAGE_DROPBOX:
            remote_path = f"/hdp_uploads/{uuid4().hex}-{remote_name}"
            return cls.stream_upload_to_dropbox(file_stream, remote_path, file_size)

        elif storage_type == STORAGE_GDRIVE:
             return cls.stream_upload_to_gdrive(file_stream, remote_name, file_size)

        return {
            "success": False,
            "message": "Unknown storage type for streaming"
        }

    @classmethod
    def get_file_download_url(cls, cloud_path_or_id: str, storage_type: str) -> Optional[str]:
        """
        Get a direct download URL for a cloud file.
        For Dropbox: Returns a temporary link.
        For GDrive: Returns a webContentLink.

        Args:
            cloud_path_or_id: The remote path (Dropbox) or File ID (GDrive)
            storage_type: 'dropbox' or 'gdrive'

        Returns:
            str: Download URL or None if failed
        """
        try:
            if storage_type == STORAGE_DROPBOX:
                import dropbox
                app_key = os.getenv("DROPBOX_APP_KEY")
                app_secret = os.getenv("DROPBOX_APP_SECRET")
                refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")

                dbx = dropbox.Dropbox(
                    app_key=app_key,
                    app_secret=app_secret,
                    oauth2_refresh_token=refresh_token
                )

                # Check if it's a shared link URL already (legacy case)
                if cloud_path_or_id.startswith("http"):
                     return cloud_path_or_id

                # If path doesn't start with /, add it for Dropbox path
                path = cloud_path_or_id
                if not path.startswith("/"):
                    path = f"/{path}"

                # Get temporary link (valid for 4 hours)
                link_metadata = dbx.files_get_temporary_link(path)
                return link_metadata.link

            elif storage_type == STORAGE_GDRIVE:
                # For GDrive, we need to get the file metadata to find the webContentLink
                # OR we assuming cloud_path_or_id is the ID.

                drive_service, msg = cls.get_gdrive_service()
                if not drive_service:
                    logger.error(f"GDrive service unavailable: {msg}")
                    return None

                file_id = cloud_path_or_id

                # If it's already a link, return it
                if file_id.startswith("http"):
                    return file_id

                file = drive_service.files().get(
                    fileId=file_id,
                    fields='webContentLink, webViewLink, size'
                ).execute()

                return file.get('webContentLink')

        except Exception as e:
            logger.error(f"Failed to get download URL for {storage_type}: {e}")
            return None

    @classmethod
    def check_cloud_object_available(cls, cloud_path_or_id: str, storage_type: str) -> Tuple[bool, str]:
        """
        Check whether a mirrored cloud object can be resolved without creating a download URL.

        Args:
            cloud_path_or_id: Dropbox path or Google Drive file ID.
            storage_type: 'dropbox' or 'gdrive'.

        Returns:
            tuple: (available, message)
        """
        if not cloud_path_or_id:
            return False, "Cloud object reference is missing"

        try:
            if storage_type == STORAGE_DROPBOX:
                import dropbox

                app_key = os.getenv("DROPBOX_APP_KEY")
                app_secret = os.getenv("DROPBOX_APP_SECRET")
                refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
                if not all([app_key, app_secret, refresh_token]):
                    return False, "Dropbox credentials are not configured"

                path = cloud_path_or_id
                if path.startswith("http"):
                    return True, "Dropbox shared link is recorded"
                if not path.startswith("/"):
                    path = f"/{path}"

                dbx = dropbox.Dropbox(
                    app_key=app_key,
                    app_secret=app_secret,
                    oauth2_refresh_token=refresh_token,
                )
                dbx.files_get_metadata(path)
                return True, "Dropbox mirror is available"

            if storage_type == STORAGE_GDRIVE:
                if cloud_path_or_id.startswith("http"):
                    return True, "Google Drive link is recorded"

                drive_service, msg = cls.get_gdrive_service()
                if not drive_service:
                    return False, msg

                drive_service.files().get(
                    fileId=cloud_path_or_id,
                    fields="id, trashed",
                    supportsAllDrives=True,
                ).execute()
                return True, "Google Drive mirror is available"

            return False, f"Unsupported cloud storage provider: {storage_type}"

        except Exception as e:
            logger.warning("Cloud object availability check failed for %s: %s", storage_type, e)
            return False, f"Cloud mirror is not reachable: {e}"
