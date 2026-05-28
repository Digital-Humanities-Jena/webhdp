# services/project_service.py
"""Project service for handling local .hdpc-backed project operations."""

import logging
import os
from typing import Any, Dict, List

from .hdpc_schema_service import connect_hdpc
from .metadata_workflow_service import get_retired_prepare_metadata_message
from .hdpc_zenodo_service import (
    append_community_to_record as append_local_community_to_record,
    create_new_version_with_files as create_local_new_version_with_files,
    create_api_draft as create_local_api_draft,
    discard_draft as discard_local_draft,
    prepare_new_version_draft as prepare_local_new_version_draft,
    publish_record as publish_local_record,
    remove_community_from_record as remove_local_community_from_record,
    upload_files_for_deposition as upload_local_files_for_deposition,
)
from .hdpc_local_service import (
    MANUAL_RECORD_ORIGIN,
    add_local_source_files,
    create_local_record_with_metadata,
    find_hdpc_record_for_file,
    get_hdpc_file_id_map as get_local_hdpc_file_id_map,
    inspect_hdpc_project,
    remove_local_source_files,
)
from .hdpc_scan_service import create_and_scan_hdpc_project

logger = logging.getLogger(__name__)


class ProjectService:
    """Service for managing WebHDP local .hdpc projects."""

    def __init__(self, api_url: str | None = None, api_client=None):
        # Keep path-translation support for local/container deployments.
        self.container_shared_path = os.environ.get("SHARED_SESSION_PATH", "/tmp")
        self.host_shared_path = os.environ.get("HOST_SHARED_PATH", self.container_shared_path)
        self.host_project_path = os.environ.get("HOST_PROJECT_PATH")
        self.container_data_path = "/data"
        self._loaded_hdpc_path: str | None = None

        logger.info(f"ProjectService initialized with:")
        logger.info(f"  Container/Local Path: {self.container_shared_path}")
        logger.info(f"  Host Shared Path:     {self.host_shared_path}")
        if self.host_project_path:
            logger.info(f"  Host Project Path:    {self.host_project_path} -> {self.container_data_path}")

    def _resolve_local_hdpc_path(self, hdpc_path: str | None = None) -> str | None:
        candidate_hdpc_path = hdpc_path or self._loaded_hdpc_path
        if candidate_hdpc_path and os.path.exists(candidate_hdpc_path):
            return candidate_hdpc_path
        return None

    def _resolve_local_source_filename(self, hdpc_path: str, file_id: str | int) -> str | None:
        conn = connect_hdpc(hdpc_path, readonly=True, timeout=30)
        try:
            row = conn.execute(
                "SELECT filename FROM source_files WHERE file_id = ? LIMIT 1",
                (int(file_id),),
            ).fetchone()
            if not row:
                return None
            return str(row[0] or "").strip() or None
        finally:
            conn.close()

    def _translate_path(self, path: str, to_container: bool = False) -> str:
        """
        Translate paths between local host-visible paths and container-visible paths.

        Args:
            path: The path to translate
            to_container: If True, translate host path -> container path.
                         If False, translate container shared path -> host-visible path.
        """
        if not path:
            return path

        if to_container:
            if self.host_project_path and path.startswith(self.host_project_path):
                return path.replace(self.host_project_path, self.container_data_path)
            return path

        if path.startswith(self.container_shared_path):
            return path.replace(self.container_shared_path, self.host_shared_path)
        return path

    def create_and_scan(
        self,
        hdpc_path: str,
        data_in_path: str,
        data_out_path: str,
        project_name: str,
        scan_options: Dict[str, Any],
        provenance: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Create and scan a new project.

        Args:
            hdpc_path: Path where the .hdpc file will be created
            data_in_path: Input directory to scan for files
            data_out_path: Output directory for processed files
            project_name: Name for the project
            scan_options: Scanning configuration options

        Returns:
            dict: Scan results including found files
        """
        logger.info(f"Creating project '{project_name}' to scan path: {data_in_path}")
        self._loaded_hdpc_path = hdpc_path
        result = create_and_scan_hdpc_project(
            hdpc_path=hdpc_path,
            data_in_path=data_in_path,
            data_out_path=data_out_path,
            project_name=project_name,
            short_code="HDP_WEB",
            modalities=["3d_model", "image", "text"],
            scan_options=scan_options,
            batch_entity=scan_options.get("batchEntity", "root"),
            provenance=provenance,
        )
        logger.info("Project created and scanned locally")
        return result

    def load(self, hdpc_path: str) -> None:
        """
        Load an HDP project from the specified path.

        Args:
            hdpc_path: Path to the .hdpc project file
        """
        self._loaded_hdpc_path = hdpc_path
        if hdpc_path and os.path.exists(hdpc_path):
            logger.info("Using local .hdpc context for %s", hdpc_path)
            return
        raise FileNotFoundError(f"Local .hdpc project file not found: {hdpc_path}")

    def inspect(self, hdpc_path: str, show_files: bool = True) -> Dict[str, Any]:
        """
        Inspect a project and retrieve its structure.

        Args:
            hdpc_path: Path to the .hdpc project file
            show_files: Whether to include file tree in response

        Returns:
            dict: Project inspection data
        """
        if hdpc_path and os.path.exists(hdpc_path):
            return inspect_hdpc_project(hdpc_path, show_files=show_files)
        raise FileNotFoundError(f"Local .hdpc project file not found: {hdpc_path}")

    def get_file_id_map(self, hdpc_path: str) -> Dict[str, str]:
        """
        Build a mapping of file paths to file IDs from the project.

        Args:
            hdpc_path: Path to the .hdpc project file

        Returns:
            dict: Mapping of {relative_path: file_id}
        """
        if hdpc_path and os.path.exists(hdpc_path):
            return get_local_hdpc_file_id_map(hdpc_path)

        raise FileNotFoundError(f"Local .hdpc project file not found: {hdpc_path}")

    def create_zenodo_record(
        self,
        file_id: str,
        is_sandbox: bool = True,
        ignore_errors: bool = True,
        *,
        hdpc_path: str | None = None,
    ) -> Dict[str, Any]:
        """
        Create a Zenodo record for a file.

        Args:
            file_id: Database ID of the source file
            is_sandbox: Whether to use Zenodo sandbox
            ignore_errors: If True, don't raise exceptions on API errors

        Returns:
            dict: Record creation result
        """
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("create_zenodo_record requires a local .hdpc context")
        file_label = self._resolve_local_source_filename(candidate_hdpc_path, file_id) or f"file {file_id}"
        prepared_record = create_local_record_with_metadata(
            candidate_hdpc_path,
            file_id=file_id,
            metadata={
                "title": f"Record for {file_label}",
                "upload_type": "other",
                "description": f"Zenodo record automatically created for source file: {file_label}",
                "creators": [{"name": "Heritage Data Processor User"}],
            },
            is_sandbox=is_sandbox,
            access_token=(
                os.environ.get("ZENODO_SANDBOX_API_KEY")
                if is_sandbox
                else os.environ.get("ZENODO_API_KEY")
            ),
            record_origin=MANUAL_RECORD_ORIGIN,
        )
        local_record_id = prepared_record.get("local_record_db_id")
        if not local_record_id:
            return prepared_record
        return create_local_api_draft(candidate_hdpc_path, int(local_record_id))

    def find_record_for_file(self, hdpc_path: str, file_id: str) -> str:
        """
        Find existing Zenodo record for a file.

        Args:
            hdpc_path: Path to the .hdpc project file
            file_id: Database ID of the source file

        Returns:
            str: Record ID if found, None otherwise
        """
        if hdpc_path and os.path.exists(hdpc_path):
            record = find_hdpc_record_for_file(hdpc_path, file_id)
            return str(record.get("record_id")) if record else None

        raise FileNotFoundError(f"Local .hdpc project file not found: {hdpc_path}")

    def prepare_metadata_for_file(
        self, file_id: str, is_sandbox: bool = True, pipeline_id: str = None
    ) -> Dict[str, Any]:
        """
        Legacy prepare-metadata behavior is retired in favor of the native WebHDP workflow.
        """
        raise NotImplementedError(get_retired_prepare_metadata_message())

    def create_record_with_metadata(
        self, file_id: str, metadata: Dict[str, Any], is_sandbox: bool = True, hdpc_path: str | None = None
    ) -> Dict[str, Any]:
        """
        Create a local Zenodo record (in .hdpc) with supplied metadata.
        Used by HDP Web integration instead of spreadsheet mapping.
        """
        zenodo_key = os.environ.get("ZENODO_SANDBOX_API_KEY") if is_sandbox else os.environ.get("ZENODO_API_KEY")
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("create_record_with_metadata requires a local .hdpc context")
        return create_local_record_with_metadata(
            candidate_hdpc_path,
            file_id=file_id,
            metadata=metadata,
            is_sandbox=is_sandbox,
            access_token=zenodo_key,
            record_origin=MANUAL_RECORD_ORIGIN,
        )

    def create_api_draft(
        self,
        local_record_id: int,
        *,
        hdpc_path: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Creates a Zenodo draft record on the Zenodo API.
        """
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("create_api_draft requires a local .hdpc context")
        return create_local_api_draft(candidate_hdpc_path, int(local_record_id), access_token=access_token)

    def discard_draft(
        self,
        local_record_id: int,
        *,
        hdpc_path: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Discard a Zenodo draft and restore the record to a prepared local state.
        """
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("discard_draft requires a local .hdpc context")
        return discard_local_draft(candidate_hdpc_path, int(local_record_id), access_token=access_token)

    def upload_files_for_deposition(
        self,
        local_record_id: int,
        publish: bool = False,
        *,
        hdpc_path: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Uploads all pending files for a record to Zenodo and optionally publishes it.
        """
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("upload_files_for_deposition requires a local .hdpc context")
        return upload_local_files_for_deposition(
            candidate_hdpc_path,
            int(local_record_id),
            publish=bool(publish),
            access_token=access_token,
        )

    def publish_record(
        self,
        local_record_id: int,
        *,
        hdpc_path: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Publishes a Zenodo draft record.
        """
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("publish_record requires a local .hdpc context")
        return publish_local_record(candidate_hdpc_path, int(local_record_id), access_token=access_token)

    def create_new_version_with_files(
        self,
        concept_rec_id: str,
        is_sandbox: bool,
        source_file_path: str,
        absolute_file_paths: List[str],
        publish: bool = False,
        hdpc_path: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        """
        Create a new Zenodo version from a complete local file set.
        """
        normalized_paths = []
        seen_paths = set()
        for path in absolute_file_paths or []:
            if not isinstance(path, str):
                continue
            stripped = path.strip()
            if not stripped:
                continue
            normalized = os.path.normpath(stripped)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            normalized_paths.append(stripped)

        if not concept_rec_id or not source_file_path or not normalized_paths:
            raise ValueError("concept_rec_id, source_file_path, and absolute_file_paths are required")

        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("create_new_version_with_files requires a local .hdpc context")
        return create_local_new_version_with_files(
            candidate_hdpc_path,
            concept_rec_id=concept_rec_id,
            is_sandbox=is_sandbox,
            source_file_path=source_file_path,
            absolute_file_paths=normalized_paths,
            publish=publish,
            access_token=access_token,
        )

    def prepare_new_version_draft(
        self,
        concept_rec_id: str,
        is_sandbox: bool,
        source_file_path: str,
        absolute_file_paths: List[str],
        *,
        hdpc_path: str | None = None,
        access_token: str | None = None,
        reference_record: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Prepare a version draft and register the current local file set without uploading files yet.
        """
        normalized_paths = []
        seen_paths = set()
        for path in absolute_file_paths or []:
            if not isinstance(path, str):
                continue
            stripped = path.strip()
            if not stripped:
                continue
            normalized = os.path.normpath(stripped)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            normalized_paths.append(stripped)

        if not concept_rec_id or not source_file_path or not normalized_paths:
            raise ValueError("concept_rec_id, source_file_path, and absolute_file_paths are required")

        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("prepare_new_version_draft requires a local .hdpc context")

        return prepare_local_new_version_draft(
            candidate_hdpc_path,
            concept_rec_id=concept_rec_id,
            is_sandbox=is_sandbox,
            source_file_path=source_file_path,
            absolute_file_paths=normalized_paths,
            access_token=access_token,
            reference_record=reference_record,
        )

    def add_source_files(
        self,
        absolute_file_paths: List[str],
        record_id_to_associate: int = None,
        pipeline_name: str = None,
        step_name: str = None,
        *,
        hdpc_path: str | None = None,
    ) -> Dict[str, Any]:
        """
        Adds source files to the project database.

        Args:
            absolute_file_paths: List of absolute paths (host paths) to files.
            record_id_to_associate: Optional Zenodo record ID to link files to.
            pipeline_name: Optional pipeline name for provenance.
            step_name: Optional step name for provenance.

        Returns:
            dict: Result of the operation.
        """
        normalized_paths = []
        seen_paths = set()
        for path in absolute_file_paths or []:
            if not isinstance(path, str):
                continue
            stripped = path.strip()
            if not stripped:
                continue
            normalized = os.path.normpath(stripped)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            normalized_paths.append(stripped)

        if not normalized_paths:
            logger.warning(
                "Skipping source file registration because no valid file paths were provided "
                "(record_id=%s, pipeline=%s, step=%s).",
                record_id_to_associate,
                pipeline_name,
                step_name,
            )
            return {
                "success": True,
                "message": "No valid file paths to register.",
                "added_count": 0,
                "skipped_existing_path": 0,
                "errors_count": 0,
                "errors": [],
            }

        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("add_source_files requires a local .hdpc context")
        return add_local_source_files(
            candidate_hdpc_path,
            absolute_file_paths=normalized_paths,
            record_id_to_associate=record_id_to_associate,
            pipeline_name=pipeline_name,
            step_name=step_name,
        )

    def remove_source_files(
        self,
        file_ids: List[int],
        *,
        hdpc_path: str | None = None,
    ) -> Dict[str, Any]:
        normalized_ids = [int(item) for item in file_ids if str(item).isdigit()]
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("remove_source_files requires a local .hdpc context")
        return remove_local_source_files(candidate_hdpc_path, file_ids=normalized_ids)

    def append_community_to_record(
        self,
        local_record_id: int,
        community_identifier: str,
        *,
        hdpc_path: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("append_community_to_record requires a local .hdpc context")
        return append_local_community_to_record(
            candidate_hdpc_path,
            int(local_record_id),
            str(community_identifier or "").strip(),
            access_token=access_token,
        )

    def remove_community_from_record(
        self,
        local_record_id: int,
        community_identifier: str | None = None,
        *,
        remove_all: bool = False,
        hdpc_path: str | None = None,
        access_token: str | None = None,
    ) -> Dict[str, Any]:
        candidate_hdpc_path = self._resolve_local_hdpc_path(hdpc_path)
        if not candidate_hdpc_path:
            raise FileNotFoundError("remove_community_from_record requires a local .hdpc context")
        return remove_local_community_from_record(
            candidate_hdpc_path,
            int(local_record_id),
            community_identifier=str(community_identifier).strip() if community_identifier is not None else None,
            remove_all=bool(remove_all),
            access_token=access_token,
        )
