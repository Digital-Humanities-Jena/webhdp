import os
from typing import Any

from database.models import Session as DBSession, UserZenodoActiveCredential, ZenodoCredential
from exceptions import ValidationError
from services.institution_service import InstitutionService
from services.zenodo_config_service import ZenodoConfigService
from services.zenodo_credential_service import ZenodoCredentialService, mask_secret, normalize_environment


def _dedupe_communities(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        signature = text.lower()
        if signature in seen:
            continue
        seen.add(signature)
        normalized.append(text)
    return normalized


def _extract_communities(metadata: dict[str, Any]) -> list[str]:
    items = metadata.get("communities") if isinstance(metadata, dict) else []
    values: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                values.append(str(item.get("identifier") or "").strip())
            else:
                values.append(str(item or "").strip())
    return _dedupe_communities(values)


def _merge_communities(metadata: dict[str, Any], additions: list[str]) -> dict[str, Any]:
    result = dict(metadata or {})
    combined = _dedupe_communities(_extract_communities(result) + list(additions or []))
    if combined:
        result["communities"] = [{"identifier": item} for item in combined]
    return result


class PublishingContextService:
    def __init__(self):
        self.credential_service = ZenodoCredentialService()
        self.institution_service = InstitutionService()

    def _empty_community_policy(self) -> dict[str, Any]:
        return {
            "enabled_communities": [],
            "default_communities": [],
            "primary_submission_community": None,
            "moderation_default_communities": [],
        }

    def _batch_credential_lookup(
        self,
        owner_type: str,
        lookup_keys: set[tuple[int, str]],
    ) -> set[tuple[int, str]]:
        if not lookup_keys:
            return set()

        owner_ids = sorted({owner_id for owner_id, _ in lookup_keys})
        environments = sorted({environment for _, environment in lookup_keys})
        rows = (
            ZenodoCredential.query.filter(
                ZenodoCredential.owner_type == owner_type,
                ZenodoCredential.owner_id.in_(owner_ids),
                ZenodoCredential.environment.in_(environments),
            )
            .all()
        )
        return {
            (int(row.owner_id), str(row.environment).strip().lower())
            for row in rows
        }

    def _batch_active_credential_lookup(self, lookup_keys: set[tuple[int, str]]) -> set[tuple[int, str]]:
        if not lookup_keys:
            return set()
        user_ids = sorted({user_id for user_id, _ in lookup_keys})
        environments = sorted({environment for _, environment in lookup_keys})
        rows = (
            UserZenodoActiveCredential.query.join(ZenodoCredential)
            .filter(
                UserZenodoActiveCredential.user_id.in_(user_ids),
                UserZenodoActiveCredential.environment.in_(environments),
                ZenodoCredential.environment == UserZenodoActiveCredential.environment,
            )
            .all()
        )
        available: set[tuple[int, str]] = set()
        for row in rows:
            if not row.credential:
                continue
            try:
                self.credential_service._ensure_accessible_by_user(row.credential, int(row.user_id))
            except Exception:
                continue
            available.add((int(row.user_id), str(row.environment).strip().lower()))
        return available

    def resolve_token_for_session(
        self,
        session_row: DBSession,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized_environment = normalize_environment(
            environment or getattr(session_row, "default_zenodo_environment", None) or "sandbox"
        )
        publishing_user_id = int(
            getattr(session_row, "publishing_user_id", None) or getattr(session_row, "user_id", 0) or 0
        )
        credential_preference = str(getattr(session_row, "credential_preference", None) or "user").strip().lower()

        if credential_preference == "user" and publishing_user_id:
            user_credential = self.credential_service.get_active_credential(publishing_user_id, normalized_environment)
            if user_credential:
                return {
                    "environment": normalized_environment,
                    "source": "user",
                    "owner_type": "user",
                    "owner_id": user_credential.owner_id,
                    "selected_by_user_id": publishing_user_id,
                    "credential_id": user_credential.id,
                    "token": self.credential_service.decrypt_value(user_credential),
                    "masked_preview": user_credential.masked_preview,
                    "shared": int(user_credential.owner_id) != int(publishing_user_id),
                }

        institution_id = getattr(session_row, "institution_id", None)
        if institution_id:
            institution_credential = self.credential_service.get_credential(
                "institution",
                int(institution_id),
                normalized_environment,
            )
            if institution_credential:
                return {
                    "environment": normalized_environment,
                    "source": "institution",
                    "owner_type": "institution",
                    "owner_id": int(institution_id),
                    "credential_id": institution_credential.id,
                    "token": self.credential_service.decrypt_value(institution_credential),
                    "masked_preview": institution_credential.masked_preview,
                }

        env_key = "ZENODO_SANDBOX_API_KEY" if normalized_environment == "sandbox" else "ZENODO_API_KEY"
        system_token = str(os.environ.get(env_key) or "").strip()
        return {
            "environment": normalized_environment,
            "source": "system",
            "owner_type": "system",
            "owner_id": None,
            "credential_id": None,
            "token": system_token or None,
            "masked_preview": mask_secret(system_token) if system_token else None,
        }

    def get_institution_default_communities(self, institution_id: int | None) -> list[str]:
        return _dedupe_communities(self.get_institution_community_policy(institution_id).get("default_communities", []))

    def get_institution_community_policy(self, institution_id: int | None) -> dict[str, Any]:
        return self.institution_service.build_community_policy(institution_id)

    def apply_community_policy(self, session_row: DBSession | None, metadata: dict[str, Any]) -> dict[str, Any]:
        result = dict(metadata or {})
        if session_row and getattr(session_row, "institution_id", None):
            if getattr(session_row, "use_institution_default_communities", False):
                community_policy = self.get_institution_community_policy(getattr(session_row, "institution_id", None))
                return _merge_communities(
                    result,
                    community_policy.get("default_communities", []),
                )
            return result
        return ZenodoConfigService.apply_community_override(result)

    def describe_session(self, session_row: DBSession) -> dict[str, Any]:
        return self.describe_sessions([session_row]).get(int(session_row.id), self._empty_session_description(session_row))

    def _empty_session_description(self, session_row: DBSession) -> dict[str, Any]:
        environment = str(getattr(session_row, "default_zenodo_environment", None) or "sandbox").strip().lower()
        return {
            "workspace_type": "institution" if getattr(session_row, "institution_id", None) else "personal",
            "sharing_scope": getattr(session_row, "sharing_scope", None) or "private",
            "credential_preference": getattr(session_row, "credential_preference", None) or "user",
            "publishing_user_id": getattr(session_row, "publishing_user_id", None) or getattr(session_row, "user_id", None),
            "default_zenodo_environment": environment,
            "effective_credential_source": "system",
            "institution_id": getattr(session_row, "institution_id", None),
            "default_communities": [],
            "primary_submission_community": None,
            "moderation_default_communities": [],
            "use_institution_default_communities": bool(
                getattr(session_row, "use_institution_default_communities", False)
            ),
        }

    def describe_sessions(self, session_rows: list[DBSession] | tuple[DBSession, ...]) -> dict[int, dict[str, Any]]:
        rows = [row for row in session_rows or [] if row]
        if not rows:
            return {}

        institution_ids = {int(getattr(row, "institution_id", 0) or 0) for row in rows if getattr(row, "institution_id", None)}
        community_policies = self.institution_service.build_community_policy_map(institution_ids)

        user_lookup_keys: set[tuple[int, str]] = set()
        institution_lookup_keys: set[tuple[int, str]] = set()
        environments_by_session: dict[int, str] = {}

        for row in rows:
            session_id = int(row.id)
            try:
                normalized_environment = normalize_environment(
                    getattr(row, "default_zenodo_environment", None) or "sandbox"
                )
            except ValidationError:
                normalized_environment = "sandbox"
            environments_by_session[session_id] = normalized_environment

            publishing_user_id = int(
                getattr(row, "publishing_user_id", None) or getattr(row, "user_id", 0) or 0
            )
            credential_preference = str(getattr(row, "credential_preference", None) or "user").strip().lower()
            if credential_preference == "user" and publishing_user_id:
                user_lookup_keys.add((publishing_user_id, normalized_environment))

            institution_id = int(getattr(row, "institution_id", 0) or 0)
            if institution_id:
                institution_lookup_keys.add((institution_id, normalized_environment))

        user_credentials = self._batch_active_credential_lookup(user_lookup_keys)
        institution_credentials = self._batch_credential_lookup("institution", institution_lookup_keys)

        descriptions: dict[int, dict[str, Any]] = {}
        for row in rows:
            session_id = int(row.id)
            environment = environments_by_session[session_id]
            publishing_user_id = int(
                getattr(row, "publishing_user_id", None) or getattr(row, "user_id", 0) or 0
            )
            credential_preference = str(getattr(row, "credential_preference", None) or "user").strip().lower()
            institution_id = int(getattr(row, "institution_id", 0) or 0) or None
            community_policy = community_policies.get(int(institution_id), self._empty_community_policy()) if institution_id else self._empty_community_policy()

            effective_source = "system"
            if credential_preference == "user" and publishing_user_id and (publishing_user_id, environment) in user_credentials:
                effective_source = "user"
            elif institution_id and (int(institution_id), environment) in institution_credentials:
                effective_source = "institution"

            descriptions[session_id] = {
                "workspace_type": "institution" if institution_id else "personal",
                "sharing_scope": getattr(row, "sharing_scope", None) or "private",
                "credential_preference": credential_preference,
                "publishing_user_id": publishing_user_id,
                "default_zenodo_environment": environment,
                "effective_credential_source": effective_source,
                "institution_id": institution_id,
                "default_communities": community_policy.get("default_communities", []),
                "primary_submission_community": community_policy.get("primary_submission_community"),
                "moderation_default_communities": community_policy.get("moderation_default_communities", []),
                "use_institution_default_communities": bool(
                    getattr(row, "use_institution_default_communities", False)
                ),
            }

        return descriptions
