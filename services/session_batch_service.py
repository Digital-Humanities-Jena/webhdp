import os
from typing import Any, Callable, Dict, List

from database.models import Session as DBSession
from services.dataset_integrity_service import DatasetIntegrityConflictError, ensure_record_operation_allowed
from services.hdpc_local_service import read_hdpc_zenodo_records


ProgressCallback = Callable[[Dict[str, Any]], None]

ALLOWED_BATCH_OPERATION_TYPES = {
    "create_drafts",
    "discard_drafts",
    "upload_files",
    "publish_records",
    "remove_files",
}


def _coerce_target_ids(values: List[Any]) -> List[int]:
    normalized: List[int] = []
    seen: set[int] = set()
    for value in values or []:
        if not str(value).isdigit():
            continue
        item = int(value)
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def execute_session_batch_operation(
    *,
    session: DBSession,
    project_service,
    operation_type: str,
    target_ids: List[Any],
    options: Dict[str, Any] | None = None,
    access_token: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Dict[str, Any]:
    normalized_operation = str(operation_type or "").strip().lower()
    if normalized_operation not in ALLOWED_BATCH_OPERATION_TYPES:
        raise ValueError("Unsupported operation_type")
    if not session.hdpc_path or not os.path.exists(session.hdpc_path):
        raise FileNotFoundError("Session .hdpc is not available")

    normalized_ids = _coerce_target_ids(target_ids)
    total = len(normalized_ids)
    options = dict(options or {})
    records_by_id = {
        int(record.get("record_id")): record
        for record in read_hdpc_zenodo_records(session.hdpc_path, canonical_only=True)
        if record.get("record_id") is not None
    }

    def _emit(progress: Dict[str, Any]) -> None:
        if progress_callback is not None:
            progress_callback(progress)

    results: List[Dict[str, Any]] = []
    completed = 0
    skipped = 0
    failed = 0

    for index, target_id in enumerate(normalized_ids, start=1):
        item_result: Dict[str, Any]
        try:
            if normalized_operation == "remove_files":
                response = project_service.remove_source_files([target_id], hdpc_path=session.hdpc_path)
                inner = (response.get("results") or [{}])[0]
                item_result = {
                    "target_id": target_id,
                    "status": inner.get("status", "completed"),
                    "result_code": inner.get("result_code", "completed"),
                    "details": inner,
                }
            else:
                record = records_by_id.get(target_id)
                if record is None:
                    item_result = {
                        "target_id": target_id,
                        "status": "skipped",
                        "result_code": "skipped_not_found",
                    }
                else:
                    try:
                        ensure_record_operation_allowed(
                            session,
                            local_record_id=target_id,
                            allow_allowed_versioning=(normalized_operation == "publish_records"),
                            exclude_current_record=False,
                        )
                    except DatasetIntegrityConflictError as exc:
                        item_result = {
                            "target_id": target_id,
                            "status": "failed",
                            "result_code": "failed_validation",
                            "error": str(exc),
                            "details": exc.details,
                        }
                    else:
                        item_result = _execute_record_operation(
                            project_service=project_service,
                            hdpc_path=session.hdpc_path,
                            operation_type=normalized_operation,
                            target_id=target_id,
                            record=record,
                            options=options,
                            access_token=access_token,
                        )
        except Exception as exc:
            item_result = {
                "target_id": target_id,
                "status": "failed",
                "result_code": "failed_runtime",
                "error": str(exc),
            }

        if item_result.get("status") == "completed":
            completed += 1
        elif item_result.get("status") == "failed":
            failed += 1
        else:
            skipped += 1
        results.append(item_result)

        _emit(
            {
                "total_items": total,
                "processed": index,
                "completed": completed,
                "skipped": skipped,
                "failed": failed,
                "percent": int((index / total) * 100) if total else 100,
                "current_target_id": target_id,
            }
        )

    final_state = "completed" if failed == 0 else "completed_with_errors"
    return {
        "status": final_state,
        "operation_type": normalized_operation,
        "results": results,
        "progress": {
            "total_items": total,
            "processed": total,
            "completed": completed,
            "skipped": skipped,
            "failed": failed,
            "percent": 100,
            "current_target_id": None,
        },
        "summary": {
            "total_items": total,
            "completed": completed,
            "skipped": skipped,
            "failed": failed,
        },
    }


def _execute_record_operation(
    *,
    project_service,
    hdpc_path: str,
    operation_type: str,
    target_id: int,
    record: Dict[str, Any],
    options: Dict[str, Any],
    access_token: str | None = None,
) -> Dict[str, Any]:
    status = str(record.get("record_status") or "").strip().lower()
    if operation_type == "create_drafts":
        if status == "prepared" and not str(record.get("zenodo_record_id") or "").strip():
            response = project_service.create_api_draft(target_id, hdpc_path=hdpc_path, access_token=access_token)
            success = bool(response.get("success"))
            return {
                "target_id": target_id,
                "status": "completed" if success else "failed",
                "result_code": "completed" if success else "failed_remote_api",
                "details": response,
            }
        return {
            "target_id": target_id,
            "status": "skipped",
            "result_code": "skipped_invalid_state",
        }

    if operation_type == "discard_drafts":
        if status != "draft":
            return {"target_id": target_id, "status": "skipped", "result_code": "skipped_missing_draft"}
        response = project_service.discard_draft(target_id, hdpc_path=hdpc_path, access_token=access_token)
        success = bool(response.get("success"))
        return {
            "target_id": target_id,
            "status": "completed" if success else "failed",
            "result_code": "completed" if success else "failed_remote_api",
            "details": response,
        }

    if operation_type == "upload_files":
        if status != "draft":
            return {"target_id": target_id, "status": "skipped", "result_code": "skipped_missing_draft"}
        response = project_service.upload_files_for_deposition(
            target_id,
            publish=False,
            hdpc_path=hdpc_path,
            access_token=access_token,
        )
        success = bool(response.get("success"))
        return {
            "target_id": target_id,
            "status": "completed" if success else "failed",
            "result_code": "completed" if success else "failed_remote_api",
            "details": response,
        }

    if operation_type == "publish_records":
        if status == "published":
            return {"target_id": target_id, "status": "skipped", "result_code": "skipped_already_published"}
        if status != "draft":
            return {"target_id": target_id, "status": "skipped", "result_code": "skipped_missing_draft"}
        response = project_service.publish_record(target_id, hdpc_path=hdpc_path, access_token=access_token)
        success = bool(response.get("success"))
        return {
            "target_id": target_id,
            "status": "completed" if success else "failed",
            "result_code": "completed" if success else "failed_remote_api",
            "details": response,
        }

    raise ValueError("Unsupported record operation")
