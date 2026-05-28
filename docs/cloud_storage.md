# HDP Cloud Storage Architecture

This document describes the storage architecture for batch uploads in the HDP Web Interface. The system supports four distinct storage modes to accommodate different infrastructure constraints and data retention policies.

## Storage Modes

The storage mode is configured by the admin via the Storage Configuration page. The selected mode dictates how files are handled during upload, processing, and long-term storage.

### 1. Pure Cloud Mode (Default)
**Best for:** Processing massive datasets (>100GB) with limited local server storage.

*   **Workflow:**
    1.  **Direct Streaming**: The user uploads a ZIP file via the frontend. The file is streamed purely through the server's memory pipe to the configured cloud provider (Dropbox or Google Drive). **The file is never written to the server's disk.**
    2.  **Streaming Proxy**: The backend acts as a streaming proxy, forwarding data chunks immediately to the cloud API.
    3.  **Remote Access**: Once uploaded, the backend accesses the file remotely using its cloud URL/ID.
    4.  **Selective Extraction**: The system reads the Central Directory of the remote ZIP to list files. It compares these against the uploaded Metadata Source File (MSF) and downloads/extracts **only the matched files** to a temporary session directory.
    5.  **Cleanup**: The temporary extracted files are used for HDP processing and then cleaned up (depending on processing retention settings). The original ZIP remains only in the Cloud.
    6.  **Owner Download**: The streamed upload artifact is registered for owner-only direct Cloud Storage download.

*   **Key Technical Features:**
    *   **RAM Usage**: Constant, low RAM usage due to streaming (chunked transfer).
    *   **Disk Usage**: Minimal. Only stores the extracted *subsets* of files needed for processing.
    *   **Performance**: Depends on upstream bandwidth to Cloud.

### 2. Cloud Backup Mode
**Best for:** redundancy and data safety where local storage is sufficient.

*   **Workflow:**
    1.  **Local Upload**: The ZIP file is uploaded and saved to the local server disk.
    2.  **Processing**: The file is processed locally (standard extraction).
    3.  **Async Backup**: After successful processing, a background task uploads the original ZIP to the Cloud.
    4.  **Retention**: The file remains on the server (for fast access) AND in the cloud (for disaster recovery).
    5.  **Owner Download**: The mirrored upload artifact is registered for owner-only direct Cloud Storage download.

### 3. Server Only Mode
**Best for:** Offline environments or when no cloud credentials are available.

*   **Workflow:**
    1.  **Local Upload**: The ZIP file is uploaded and saved to the local server disk.
    2.  **Processing**: The file is processed locally.
    3.  **Retention**: Files exist only on the server.
    4.  **Cloud Download Status**: The file review UI reports that Cloud Storage download is unavailable because mirroring is disabled.

### 4. Local / HPC Mode
**Best for:** HPC-attached storage and zero-copy scan workflows where files already exist on a mounted filesystem.

*   **Workflow:**
    1.  **Local Selection**: The user selects an existing MSF from the configured local input root.
    2.  **Zero-Copy Scan**: WebHDP scans files in place instead of uploading or mirroring source artifacts.
    3.  **Retention**: Files remain in the HPC/local input path.
    4.  **Cloud Download Status**: The file review UI reports that Cloud Storage download is unavailable because the session was created in HPC/local storage mode.

---

## Pure Cloud Processing Details

The "Pure Cloud" workflow uses a specialized 2-step process to bypass local storage limits.

### Step 1: Streaming Upload Endpoint
*   **Endpoint**: `POST /api/v1/upload/stream`
*   **Mechanism**: Accepts `application/octet-stream`. Uses Python generators to read from the request inputs stream and pipe data directly to the Cloud Provider's upload session (e.g., Dropbox `upload_session_append_v2` or Google Drive `resumable=True`).
*   **Result**: Returns a `cloud_path` or `cloud_id` reference.

### Step 2: Remote Session Initialization
*   **Endpoint**: `POST /api/v1/sessions/directory`
*   **Input**: Receives `cloud_path` (from Step 1) and the `msf_file`.
*   **Logic**:
    1.  **Selective Extraction**: The backend uses `utils.remote_storage.RemoteStorageFile` to wrap the Cloud Download URL as a seekable file-like object (using HTTP Range requests).
    2.  It opens the ZIP structure remotely (reading only headers).
    3.  It matches filenames against the MSF.
    4.  It extracts **only the matched files** to the session workspace.

---

## Cloud Downloads for Uploaded Assets

Newly uploaded source artifacts are persisted as Cloud Storage mirror records whenever cloud mirroring is active. The feature covers the raw artifacts WebHDP receives from the browser:

*   Single-file uploads.
*   Batch ZIP uploads.
*   Uploaded MSF files.

For batch ZIP uploads, the uploaded ZIP is the downloadable artifact. Expanded ZIP members are not registered as separate direct cloud downloads.

Mirror records are stored in the `cloud_mirror_objects` table and include the session, optional file ID, artifact kind, original filename, provider, provider object reference, mirror status, error text, and timestamps. The migration that introduces this table is `b3f8c1d2e4a9_add_cloud_mirror_objects.py`.

### Availability Rules

| Storage mode | Cloud download behavior |
|---|---|
| `pure_cloud` | The streamed upload is registered as an existing cloud object. Availability is checked against the provider before display or download. |
| `cloud_backup` | The locally saved upload artifact is mirrored to the configured provider and registered when the upload succeeds. |
| `server_only` | No mirror record is created. The UI reports that cloud mirroring is disabled. |
| `local` / HPC | No mirror record is created. The UI reports that the session was created in HPC/local storage mode. |

Availability is checked at request time using provider-safe object checks. If credentials are missing, the provider is unreachable, the object no longer exists, or a previous mirror failed, the UI shows the unavailable or failed reason instead of a download button.

### Security Model

Cloud artifact downloads follow the raw `.hdpc` download policy: only the session owner can list and download these mirrored source artifacts. When the owner starts a download, WebHDP creates a temporary provider download URL, records a `cloud_mirror_downloaded` audit event, and redirects the browser to the provider URL.

The existing raw `.hdpc` and shared `.hdpc` download behavior is unchanged.

---

## Implementation Status

### Implemented Features
*   **Storage Configuration**: Admin UI to select modes (Pure Cloud, Backup, Server Only, Local/HPC).
*   **Cloud Providers**:
    *   **Dropbox**: Full support for Upload, Streaming, and Remote Read (Temp Link).
    *   **Google Drive**: Support for Upload and Streaming.
*   **Streaming Logic**:
    *   Backend Proxy (`/api/v1/upload/stream`).
    *   Frontend `uploadFileStream` integration.
    *   Dynamic Progress UI ("Streaming" vs "Uploading").
*   **Remote ZIP access**:
    *   `RemoteStorageFile` adapter for HTTP Range requests.
    *   **Selective Extraction**: Logic to filter ZIP extraction based on MSF matches.
*   **Cloud Downloads for Uploaded Assets**:
    *   Mirror persistence for uploaded single files, batch ZIPs, and uploaded MSF files.
    *   Owner-only availability and download APIs under `/api/v1/sessions/<session_id>/cloud-downloads`.
    *   File review UI panel that shows available download buttons or explicit unavailable reasons.

### Not Implemented / Future Work
*   **Google Drive Remote Read**: While Streaming Upload is supported, the *Remote Read/Extraction* logic (`get_file_download_url` for GDrive) relies on `webContentLink`. For very large files, GDrive's download limits or API behavior may require a provider-specific adapter. Currently, it assumes the `webContentLink` is a direct download link.
*   **Resumable Uploads (Frontend)**: If the browser connection drops during the stream, the upload restarts. Browser-side chunked upload would make retries less expensive.
*   **Background Processing**: The extraction happens synchronously in the request. For massive archives with thousands of files, this should ideally be a background Celery task.
