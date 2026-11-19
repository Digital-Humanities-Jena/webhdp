import re
import unicodedata
from contextlib import contextmanager
from difflib import SequenceMatcher
from typing import Iterable
from urllib.parse import urlsplit

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from database.database import db
from database.models import Institution, InstitutionMembership, InstitutionRole, InstitutionZenodoCommunity, User, UserRole
from exceptions import ResourceNotFoundError, SecurityError, ValidationError
from services.audit_service import record_audit_event
from services.model_publication_accounts import is_demo
from services.notification_service import notify_user
from services.registry_lock import registry_lock


_ROLE_RANKS = {
    InstitutionRole.READER.value: 1,
    InstitutionRole.CURATOR.value: 2,
    InstitutionRole.MANAGER.value: 3,
    InstitutionRole.OWNER.value: 4,
}
INTERNAL_PROFILE_VISIBILITIES = {"private", "internal"}


def slugify_institution_name(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return text[:120]


def normalize_institution_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return " ".join("".join(
        char if char.isalnum() or unicodedata.category(char).startswith("M") else " "
        for char in text
    ).split())


def validate_institution_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Institution name is required")
    name = value.strip()
    if not name or len(name) > 255 or not any(char.isalnum() for char in normalize_institution_name(name)):
        raise ValidationError("Provide an institution name with letters or numbers, up to 255 characters")
    return name


def _validated_web_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and len(value) <= 500 and not any(char.isspace() or char == "\\" for char in value):
        try:
            url = urlsplit(value)
            if url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password:
                return value
        except ValueError:
            pass
    raise ValidationError("Provide a valid HTTP or HTTPS URL")


def _optional_workspace_text(value: str | None, *, field: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValidationError(f"{field} must be text of up to {limit:,} characters")
    return value.strip() or None


def serialize_member_identity(member: User | None, *, viewer: User) -> dict | None:
    if member is None:
        return None
    payload = {"id": member.id}
    is_self = viewer.id == member.id
    profile_visible = member.profile_visibility in {"internal", "public"}
    if is_self or profile_visible:
        payload.update(display_name=member.display_name, full_name=member.full_name)
    if is_self or (profile_visible and member.show_email):
        payload["email"] = member.email
    return payload


@contextmanager
def institution_membership_lock(institution_id: int):
    with registry_lock(f"institution-memberships:{int(institution_id)}"):
        try:
            yield
        except Exception:
            db.session.rollback()
            raise


@contextmanager
def institution_directory_lock():
    with registry_lock("institution-directory"):
        try:
            yield
        except Exception:
            db.session.rollback()
            raise


class InstitutionService:
    def _owner_count(self, institution_id: int) -> int:
        return (
            InstitutionMembership.query.filter_by(
                institution_id=int(institution_id),
                role=InstitutionRole.OWNER,
            ).count()
        )

    def get_by_id(self, institution_id: int) -> Institution:
        institution = db.session.get(Institution, int(institution_id))
        if not institution:
            raise ResourceNotFoundError("Institution not found")
        return institution

    def _serialize_suggestion(self, institution: Institution, *, query: str | None = None, score: float | None = None) -> dict:
        if score is None and query:
            score = self.similarity_score(query, institution.name)
        return {
            "id": institution.id,
            "name": institution.name,
            "display_name": institution.display_name,
            "slug": institution.slug,
            "similarity": round(float(score or 0), 3),
        }

    def similarity_score(self, left: str, right: str) -> float:
        normalized_left = normalize_institution_name(left)
        normalized_right = normalize_institution_name(right)
        if not normalized_left or not normalized_right:
            return 0.0
        if normalized_left == normalized_right:
            return 1.0
        if normalized_left in normalized_right or normalized_right in normalized_left:
            shorter = min(len(normalized_left), len(normalized_right))
            longer = max(len(normalized_left), len(normalized_right))
            return max(0.86, shorter / longer)
        return SequenceMatcher(None, normalized_left, normalized_right).ratio()

    def find_exact_by_name(self, name: str, *, user: User | None = None, exclude_id: int | None = None) -> Institution | None:
        normalized_name = normalize_institution_name(name)
        if not normalized_name:
            return None
        candidates = self._visible_affiliations(user) if user else Institution.query
        if exclude_id is not None:
            candidates = candidates.filter(Institution.id != exclude_id)
        for identifier, candidate in candidates.with_entities(Institution.id, Institution.name).order_by(Institution.id):
            if normalize_institution_name(candidate) == normalized_name:
                return db.session.get(Institution, identifier)
        return None

    def _visible_affiliations(self, user: User):
        if user.role in {UserRole.ADMIN, UserRole.MODERATOR}:
            return Institution.query
        memberships = db.session.query(InstitutionMembership.institution_id).filter_by(user_id=user.id)
        return Institution.query.filter(or_(Institution.profile_visibility == "internal", Institution.id.in_(memberships)))

    def suggest_institutions(self, query: str, *, user: User, limit: int = 8) -> list[dict]:
        text = str(query or "").strip()
        normalized = normalize_institution_name(text)
        if not normalized:
            return []
        visible = self._visible_affiliations(user)
        limit = min(int(limit), 20)
        slug = slugify_institution_name(text)
        filters = [Institution.name.icontains(text, autoescape=True), Institution.display_name.icontains(text, autoescape=True)]
        if slug:
            filters.append(Institution.slug.contains(slug, autoescape=True))
        candidates = visible.filter(or_(*filters)).order_by(Institution.name).limit(limit * 2).all()
        if len(candidates) < limit:
            candidates = list({institution.id: institution for institution in (
                candidates + visible.order_by(Institution.name).limit(250).all()
            )}.values())
        scored = [
            (institution, max(self.similarity_score(text, institution.name),
                              self.similarity_score(text, institution.display_name or "")))
            for institution in candidates
        ]
        ranked = sorted(scored, key=lambda item: (-item[1], item[0].name.casefold()))
        return [
            self._serialize_suggestion(institution, query=text, score=score)
            for institution, score in ranked if score >= 0.55
        ][:limit]

    def list_for_user(self, user_id: int) -> list[InstitutionMembership]:
        return (
            InstitutionMembership.query.filter_by(user_id=int(user_id))
            .join(Institution, InstitutionMembership.institution_id == Institution.id)
            .options(selectinload(InstitutionMembership.institution))
            .order_by(Institution.name.asc())
            .all()
        )

    def list_manageable_for_user(self, user_id: int, *, required_role: str = "curator") -> list[InstitutionMembership]:
        memberships = self.list_for_user(user_id)
        return [membership for membership in memberships if self.has_role(membership, required_role)]

    def get_membership(self, institution_id: int, user_id: int) -> InstitutionMembership | None:
        return InstitutionMembership.query.filter_by(
            institution_id=int(institution_id),
            user_id=int(user_id),
        ).populate_existing().first()

    def _set_user_affiliation(self, *, user: User, institution: Institution) -> InstitutionMembership | None:
        membership = self.get_membership(institution.id, user.id)
        if membership is None and institution.profile_visibility != "internal" and user.role not in {UserRole.ADMIN, UserRole.MODERATOR}:
            raise ResourceNotFoundError("Institution not found")
        if membership:
            user.default_institution_id = institution.id
        user.affiliation = institution.display_name or institution.name
        db.session.commit()
        return membership

    def configure_user_affiliation(
        self,
        *,
        user: User,
        institution_id: int | None = None,
        name: str | None = None,
    ) -> dict:
        if institution_id not in (None, ""):
            try:
                institution = self.get_by_id(int(institution_id))
            except (TypeError, ValueError) as exc:
                raise ValidationError("institution_id must be an integer") from exc
            membership = self._set_user_affiliation(user=user, institution=institution)
            return {"institution": institution, "membership": membership}

        if not isinstance(name, str) or len(name.strip()) > 255:
            raise ValidationError("Affiliation must be text of up to 255 characters")
        label = name.strip()
        existing = self.find_exact_by_name(label, user=user)
        if existing:
            membership = self._set_user_affiliation(user=user, institution=existing)
            return {"institution": existing, "membership": membership}
        user.affiliation = label or None
        db.session.commit()
        return {"institution": None, "membership": None}

    def has_role(self, membership: InstitutionMembership | None, required_role: str) -> bool:
        if not membership:
            return False
        current = membership.role.value if membership.role else InstitutionRole.READER.value
        return _ROLE_RANKS.get(current, 0) >= _ROLE_RANKS.get(str(required_role or "").strip().lower(), 0)

    def create_institution(
        self,
        *,
        name: str,
        description: str | None,
        actor: User,
        display_name: str | None = None,
        website_url: str | None = None,
        logo_url: str | None = None,
        profile_visibility: str | None = None,
        owner: User | None = None,
        commit: bool = True,
    ) -> Institution:
        with institution_directory_lock():
            db.session.refresh(actor)
            if not self._eligible_account(actor) or actor.role != UserRole.ADMIN:
                raise SecurityError("Site administration is required to create an institution workspace")
            owner = owner or actor
            db.session.refresh(owner)
            if not self._eligible_account(owner):
                raise ValidationError("The first owner must have a verified, active account")
            name = validate_institution_name(name)
            if self.find_exact_by_name(name):
                raise ValidationError("An institution with this name already exists")

            slug_base = slugify_institution_name(name) or "institution"
            slug = slug_base
            suffix = 1
            while Institution.query.filter_by(slug=slug).first():
                suffix += 1
                ending = f"-{suffix}"
                slug = f"{slug_base[:120 - len(ending)]}{ending}"

            institution = Institution(
                name=name,
                slug=slug,
                description=_optional_workspace_text(description, field="Description", limit=10000),
                display_name=_optional_workspace_text(display_name, field="Display name", limit=255),
                website_url=_validated_web_url(website_url),
                logo_url=_validated_web_url(logo_url),
                profile_visibility=self._normalize_profile_visibility(profile_visibility),
                created_by_user_id=actor.id,
            )
            db.session.add(institution)
            db.session.flush()
            db.session.add(
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=owner.id,
                    role=InstitutionRole.OWNER,
                )
            )
            record_audit_event(
                actor_user_id=actor.id,
                institution_id=institution.id,
                event_type="institution_created",
                entity_type="institution",
                entity_id=institution.id,
                details={"name": institution.name, "slug": institution.slug, "owner_user_id": owner.id},
            )
            if commit:
                db.session.commit()
            return institution

    def _normalize_profile_visibility(self, value: str | None) -> str:
        visibility = str(value or "private").strip().lower()
        if visibility not in INTERNAL_PROFILE_VISIBILITIES:
            raise ValidationError("profile_visibility must be private or internal")
        return visibility

    def update_institution(
        self,
        institution: Institution,
        *,
        actor: User,
        name: str | None,
        description: str | None,
        display_name: str | None = None,
        website_url: str | None = None,
        logo_url: str | None = None,
        profile_visibility: str | None = None,
    ) -> Institution:
        with institution_membership_lock(institution.id), institution_directory_lock():
            self.require_membership_manager(institution.id, actor)
            db.session.refresh(institution)
            if name is not None and name != institution.name:
                if actor.role != UserRole.ADMIN:
                    raise SecurityError("Ask a site administrator to change the official institution name")
                name = validate_institution_name(name)
                if self.find_exact_by_name(name, exclude_id=institution.id):
                    raise ValidationError("An institution with this name already exists")
                institution.name = name
            if description is not None:
                institution.description = _optional_workspace_text(description, field="Description", limit=10000)
            if display_name is not None:
                institution.display_name = _optional_workspace_text(display_name, field="Display name", limit=255)
            if website_url is not None:
                institution.website_url = _validated_web_url(website_url)
            if logo_url is not None:
                institution.logo_url = _validated_web_url(logo_url)
            if profile_visibility is not None:
                institution.profile_visibility = self._normalize_profile_visibility(profile_visibility)
            record_audit_event(
                actor_user_id=actor.id,
                institution_id=institution.id,
                event_type="institution_updated",
                entity_type="institution",
                entity_id=institution.id,
                details={"name": institution.name, "description": institution.description},
            )
            db.session.commit()
            return institution

    @staticmethod
    def _eligible_account(user: User | None) -> bool:
        return bool(user and user.is_verified and not user.force_password_change and not is_demo(user))

    def require_membership_manager(self, institution_id: int, actor: User) -> None:
        db.session.refresh(actor)
        if self._eligible_account(actor) and actor.role == UserRole.ADMIN:
            return
        membership = self.get_membership(institution_id, actor.id)
        if not self._eligible_account(actor) or not self.has_role(membership, "manager"):
            raise ResourceNotFoundError("Institution not found")

    def _require_owner_role_change(self, actor: User, institution_id: int, *roles) -> None:
        if InstitutionRole.OWNER not in roles or actor.role == UserRole.ADMIN:
            return
        if not self.has_role(self.get_membership(institution_id, actor.id), "owner"):
            raise SecurityError("Only an institution owner or administrator can change owner membership")

    def validate_membership_role(self, institution_id: int, role: str, *, actor: User) -> InstitutionRole:
        self.require_membership_manager(institution_id, actor)
        try:
            role_enum = role if isinstance(role, InstitutionRole) else InstitutionRole(str(role or "").strip().lower())
        except ValueError as exc:
            raise ValidationError(f"Invalid institution role: {role}") from exc
        self._require_owner_role_change(actor, institution_id, role_enum)
        return role_enum

    def upsert_membership(
        self, institution_id: int, user_id: int, role: str, *, actor: User, commit: bool = True,
        existing_only: bool = False, notify_change: bool = True,
    ) -> InstitutionMembership:
        with institution_membership_lock(institution_id):
            role_enum = self.validate_membership_role(institution_id, role, actor=actor)
            membership = self.get_membership(institution_id, user_id)
            if not membership and existing_only:
                raise ResourceNotFoundError("Institution membership not found")
            target = db.session.get(User, int(user_id), populate_existing=True)
            if not self._eligible_account(target):
                raise ValidationError("Institution membership requires a verified, active account")
            if membership and membership.role == role_enum:
                return membership
            previous_role = membership.role if membership else None
            self._require_owner_role_change(actor, institution_id, previous_role)
            if previous_role == InstitutionRole.OWNER and self._owner_count(institution_id) <= 1:
                raise ValidationError("Cannot remove the last institution owner")
            if membership:
                membership.role = role_enum
            else:
                membership = InstitutionMembership(institution_id=institution_id, user_id=user_id, role=role_enum)
                db.session.add(membership)
            db.session.flush()
            record_audit_event(
                actor_user_id=actor.id,
                institution_id=institution_id,
                event_type="institution_membership_upserted",
                entity_type="institution_membership",
                entity_id=membership.id,
                details={"user_id": user_id, "role": role_enum.value},
            )
            if notify_change:
                institution = self.get_by_id(institution_id)
                notify_user(
                    recipient_user_id=user_id,
                    notification_type="institution.membership_updated" if previous_role else "institution.membership_added",
                    title="Institution membership updated" if previous_role else "Institution membership added",
                    body=f"You are now {role_enum.value} in {institution.display_name or institution.name}.",
                    institution_id=institution_id,
                    entity_type="institution",
                    entity_id=institution_id,
                    action_url="/account/institutions",
                    dedupe_key=f"institution:{institution_id}:membership:{user_id}:{role_enum.value}",
                )
            if commit:
                db.session.commit()
            return membership

    def remove_membership(self, institution_id: int, user_id: int, *, actor: User) -> bool:
        with institution_membership_lock(institution_id):
            self.require_membership_manager(institution_id, actor)
            membership = self.get_membership(institution_id, user_id)
            if not membership:
                return False
            self._require_owner_role_change(actor, institution_id, membership.role)
            if membership.role == InstitutionRole.OWNER and self._owner_count(institution_id) <= 1:
                raise ValidationError("Cannot remove the last institution owner")
            target = db.session.get(User, user_id)
            if target and target.default_institution_id == institution_id:
                target.default_institution_id = None

            record_audit_event(
                actor_user_id=actor.id,
                institution_id=institution_id,
                event_type="institution_membership_removed",
                entity_type="institution_membership",
                entity_id=membership.id,
                details={"user_id": user_id, "role": membership.role.value},
            )
            institution = self.get_by_id(institution_id)
            notify_user(
                recipient_user_id=user_id,
                notification_type="institution.membership_removed",
                severity="warning",
                title="Institution membership removed",
                body=f"Your membership in {institution.display_name or institution.name} was removed.",
                institution_id=institution_id,
                entity_type="institution",
                entity_id=institution_id,
                action_url="/account/institutions",
                dedupe_key=f"institution:{institution_id}:membership:{user_id}:removed",
            )
            db.session.delete(membership)
            db.session.commit()
            return True

    def list_members(self, institution_id: int) -> list[InstitutionMembership]:
        return (
            InstitutionMembership.query.filter_by(institution_id=int(institution_id))
            .options(
                selectinload(InstitutionMembership.user),
                selectinload(InstitutionMembership.institution),
            )
            .order_by(InstitutionMembership.created_at.asc())
            .all()
        )

    def list_member_counts(self, institution_ids: Iterable[int] | None) -> dict[int, int]:
        normalized_ids = sorted({int(item) for item in institution_ids or [] if item})
        if not normalized_ids:
            return {}

        counts = {institution_id: 0 for institution_id in normalized_ids}
        rows = (
            db.session.query(
                InstitutionMembership.institution_id,
                func.count(InstitutionMembership.id),
            )
            .filter(InstitutionMembership.institution_id.in_(normalized_ids))
            .group_by(InstitutionMembership.institution_id)
            .all()
        )
        for institution_id, member_count in rows:
            counts[int(institution_id)] = int(member_count or 0)
        return counts

    def get_membership_map(self, user_id: int, institution_ids: Iterable[int] | None) -> dict[int, InstitutionMembership]:
        normalized_ids = sorted({int(item) for item in institution_ids or [] if item})
        if not normalized_ids:
            return {}
        rows = (
            InstitutionMembership.query.filter(
                InstitutionMembership.user_id == int(user_id),
                InstitutionMembership.institution_id.in_(normalized_ids),
            )
            .options(selectinload(InstitutionMembership.institution))
            .all()
        )
        return {int(row.institution_id): row for row in rows}

    def list_communities(self, institution_id: int, *, enabled_only: bool = False) -> list[InstitutionZenodoCommunity]:
        query = InstitutionZenodoCommunity.query.filter_by(institution_id=int(institution_id))
        if enabled_only:
            query = query.filter_by(enabled=True)
        return query.order_by(InstitutionZenodoCommunity.sort_order.asc(), InstitutionZenodoCommunity.id.asc()).all()

    def validate_community_identifier(
        self,
        institution_id: int,
        identifier: str,
        *,
        exclude_community_id: int | None = None,
    ) -> str:
        normalized_identifier = str(identifier or "").strip()
        if not normalized_identifier:
            raise ValidationError("identifier is required")
        existing = InstitutionZenodoCommunity.query.filter_by(
            institution_id=int(institution_id),
            identifier=normalized_identifier,
        ).first()
        if existing and existing.id != int(exclude_community_id or 0):
            raise ValidationError("Institution community identifier already exists")
        return normalized_identifier

    def apply_primary_submission_selection(self, institution_id: int, primary_community_id: int | None) -> None:
        normalized_primary_id = int(primary_community_id) if primary_community_id is not None else None
        rows = InstitutionZenodoCommunity.query.filter_by(institution_id=int(institution_id)).all()
        for row in rows:
            row.is_primary_submission = bool(normalized_primary_id and row.id == normalized_primary_id)
        db.session.flush()

    def _empty_community_policy(self) -> dict:
        return {
            "enabled_communities": [],
            "default_communities": [],
            "primary_submission_community": None,
            "moderation_default_communities": [],
        }

    def build_community_policy_map(self, institution_ids: Iterable[int] | None) -> dict[int, dict]:
        normalized_ids = sorted({int(item) for item in institution_ids or [] if item})
        if not normalized_ids:
            return {}

        rows = (
            InstitutionZenodoCommunity.query.filter(
                InstitutionZenodoCommunity.institution_id.in_(normalized_ids),
                InstitutionZenodoCommunity.enabled.is_(True),
            )
            .order_by(
                InstitutionZenodoCommunity.institution_id.asc(),
                InstitutionZenodoCommunity.sort_order.asc(),
                InstitutionZenodoCommunity.id.asc(),
            )
            .all()
        )

        grouped_rows: dict[int, list[InstitutionZenodoCommunity]] = {institution_id: [] for institution_id in normalized_ids}
        for row in rows:
            grouped_rows.setdefault(int(row.institution_id), []).append(row)

        policies: dict[int, dict] = {}
        for institution_id in normalized_ids:
            enabled_rows = grouped_rows.get(institution_id, [])
            if not enabled_rows:
                policies[institution_id] = self._empty_community_policy()
                continue

            primary_row = next((row for row in enabled_rows if row.is_primary_submission), None) or enabled_rows[0]
            ordered_identifiers = [primary_row.identifier]
            ordered_identifiers.extend(row.identifier for row in enabled_rows if row.id != primary_row.id)
            moderation_defaults = [row.identifier for row in enabled_rows if row.is_moderation_default]

            policies[institution_id] = {
                "enabled_communities": [row.to_dict() for row in enabled_rows],
                "default_communities": ordered_identifiers,
                "primary_submission_community": primary_row.identifier,
                "moderation_default_communities": moderation_defaults,
            }

        return policies

    def build_community_policy(self, institution_id: int | None) -> dict:
        if not institution_id:
            return self._empty_community_policy()

        return self.build_community_policy_map([int(institution_id)]).get(int(institution_id), self._empty_community_policy())

    def list_roles(self) -> Iterable[str]:
        return [item.value for item in InstitutionRole]
