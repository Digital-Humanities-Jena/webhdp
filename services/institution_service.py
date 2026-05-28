import re
from difflib import SequenceMatcher
from typing import Iterable

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from database.database import db
from database.models import Institution, InstitutionMembership, InstitutionRole, InstitutionZenodoCommunity, User
from exceptions import ResourceNotFoundError, ValidationError
from services.notification_service import notify_user


_ROLE_RANKS = {
    InstitutionRole.READER.value: 1,
    InstitutionRole.CURATOR.value: 2,
    InstitutionRole.MANAGER.value: 3,
    InstitutionRole.OWNER.value: 4,
}
INTERNAL_PROFILE_VISIBILITIES = {"private", "internal"}
SIMILAR_INSTITUTION_THRESHOLD = 0.82


def slugify_institution_name(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text[:120]


def normalize_institution_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return re.sub(r"[^a-z0-9 ]+", "", text)


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
        payload = institution.to_dict()
        if score is None and query:
            score = self.similarity_score(query, institution.name)
        payload["similarity"] = round(float(score or 0), 3)
        return payload

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

    def find_exact_by_name(self, name: str) -> Institution | None:
        normalized_name = normalize_institution_name(name)
        if not normalized_name:
            return None
        return Institution.query.filter(func.lower(Institution.name) == normalized_name).first()

    def suggest_institutions(self, query: str, *, limit: int = 8) -> list[dict]:
        text = str(query or "").strip()
        normalized = normalize_institution_name(text)
        if not normalized:
            return []
        like_value = f"%{text}%"
        candidates = (
            Institution.query.filter(
                or_(
                    Institution.name.ilike(like_value),
                    Institution.slug.ilike(f"%{slugify_institution_name(text)}%"),
                )
            )
            .order_by(Institution.name.asc())
            .limit(max(1, min(int(limit or 8), 20)) * 2)
            .all()
        )
        scored_by_id: dict[int, tuple[Institution, float]] = {
            institution.id: (institution, self.similarity_score(text, institution.name))
            for institution in candidates
        }
        if len(scored_by_id) < limit:
            for institution in Institution.query.order_by(Institution.name.asc()).limit(250).all():
                score = self.similarity_score(text, institution.name)
                if score >= 0.55:
                    scored_by_id[institution.id] = (institution, max(score, scored_by_id.get(institution.id, (institution, 0))[1]))
        ranked = sorted(
            scored_by_id.values(),
            key=lambda item: (-item[1], item[0].name.lower()),
        )
        return [
            self._serialize_suggestion(institution, query=text, score=score)
            for institution, score in ranked[: max(1, min(int(limit or 8), 20))]
        ]

    def similar_institutions(self, name: str, *, threshold: float = SIMILAR_INSTITUTION_THRESHOLD, limit: int = 5) -> list[dict]:
        text = str(name or "").strip()
        if not text:
            return []
        scored = []
        for institution in Institution.query.order_by(Institution.name.asc()).limit(500).all():
            score = self.similarity_score(text, institution.name)
            if score >= float(threshold):
                scored.append((institution, score))
        scored.sort(key=lambda item: (-item[1], item[0].name.lower()))
        return [
            self._serialize_suggestion(institution, query=text, score=score)
            for institution, score in scored[: max(1, min(int(limit or 5), 20))]
        ]

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
        ).first()

    def ensure_user_affiliation(self, *, user: User, institution: Institution, role: str = "reader") -> InstitutionMembership:
        try:
            role_enum = InstitutionRole(str(role or "reader").strip().lower())
        except ValueError as exc:
            raise ValidationError(f"Invalid institution role: {role}") from exc

        membership = self.get_membership(institution.id, user.id)
        if membership is None:
            membership = InstitutionMembership(
                institution_id=int(institution.id),
                user_id=int(user.id),
                role=role_enum,
            )
            db.session.add(membership)
        user.default_institution_id = int(institution.id)
        user.affiliation = institution.display_name or institution.name
        db.session.commit()
        return membership

    def configure_user_affiliation(
        self,
        *,
        user: User,
        institution_id: int | None = None,
        name: str | None = None,
        confirm_create: bool = False,
    ) -> dict:
        if institution_id not in (None, ""):
            institution = self.get_by_id(int(institution_id))
            membership = self.ensure_user_affiliation(user=user, institution=institution)
            return {"institution": institution, "membership": membership, "created": False, "similar": []}

        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValidationError("Institution name is required")

        existing = self.find_exact_by_name(normalized_name)
        if existing:
            membership = self.ensure_user_affiliation(user=user, institution=existing)
            return {"institution": existing, "membership": membership, "created": False, "similar": []}

        similar = self.similar_institutions(normalized_name)
        if similar and not confirm_create:
            return {"institution": None, "membership": None, "created": False, "similar": similar}

        institution = self.create_institution(
            name=normalized_name,
            description=None,
            created_by_user_id=int(user.id),
            profile_visibility="internal",
        )
        user.default_institution_id = int(institution.id)
        user.affiliation = institution.display_name or institution.name
        membership = self.get_membership(institution.id, user.id)
        db.session.commit()
        return {"institution": institution, "membership": membership, "created": True, "similar": similar}

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
        created_by_user_id: int | None,
        display_name: str | None = None,
        website_url: str | None = None,
        logo_url: str | None = None,
        profile_visibility: str | None = None,
    ) -> Institution:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValidationError("Institution name is required")

        slug_base = slugify_institution_name(normalized_name)
        if not slug_base:
            raise ValidationError("Institution name must contain alphanumeric characters")

        slug = slug_base
        suffix = 1
        while Institution.query.filter_by(slug=slug).first():
            suffix += 1
            slug = f"{slug_base}-{suffix}"

        institution = Institution(
            name=normalized_name,
            slug=slug,
            description=str(description or "").strip() or None,
            display_name=str(display_name or "").strip() or None,
            website_url=str(website_url or "").strip() or None,
            logo_url=str(logo_url or "").strip() or None,
            profile_visibility=self._normalize_profile_visibility(profile_visibility),
            created_by_user_id=created_by_user_id,
        )
        db.session.add(institution)
        db.session.flush()
        if created_by_user_id is not None:
            db.session.add(
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=int(created_by_user_id),
                    role=InstitutionRole.OWNER,
                )
            )
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
        name: str | None,
        description: str | None,
        display_name: str | None = None,
        website_url: str | None = None,
        logo_url: str | None = None,
        profile_visibility: str | None = None,
    ) -> Institution:
        if name is not None:
            normalized_name = str(name or "").strip()
            if not normalized_name:
                raise ValidationError("Institution name is required")
            existing = Institution.query.filter_by(name=normalized_name).first()
            if existing and existing.id != institution.id:
                raise ValidationError("Institution name already exists")
            institution.name = normalized_name
        if description is not None:
            institution.description = str(description or "").strip() or None
        if display_name is not None:
            institution.display_name = str(display_name or "").strip() or None
        if website_url is not None:
            institution.website_url = str(website_url or "").strip() or None
        if logo_url is not None:
            institution.logo_url = str(logo_url or "").strip() or None
        if profile_visibility is not None:
            institution.profile_visibility = self._normalize_profile_visibility(profile_visibility)
        db.session.commit()
        return institution

    def upsert_membership(self, institution_id: int, user_id: int, role: str) -> InstitutionMembership:
        try:
            role_enum = InstitutionRole(str(role or "").strip().lower())
        except ValueError as exc:
            raise ValidationError(f"Invalid institution role: {role}") from exc

        membership = self.get_membership(institution_id, user_id)
        previous_role = membership.role.value if membership and membership.role else None
        if membership and membership.role == InstitutionRole.OWNER and role_enum != InstitutionRole.OWNER:
            if self._owner_count(institution_id) <= 1:
                raise ValidationError("Cannot remove the last institution owner")
        if membership:
            membership.role = role_enum
        else:
            membership = InstitutionMembership(
                institution_id=int(institution_id),
                user_id=int(user_id),
                role=role_enum,
            )
            db.session.add(membership)
        institution = db.session.get(Institution, int(institution_id))
        notify_user(
            recipient_user_id=int(user_id),
            notification_type="institution.membership_updated" if previous_role else "institution.membership_added",
            category="profiles",
            severity="info",
            title="Institution membership updated" if previous_role else "Institution membership added",
            body=f"You are now {role_enum.value} in {institution.display_name or institution.name if institution else 'an institution'}.",
            institution_id=int(institution_id),
            entity_type="institution",
            entity_id=int(institution_id),
            action_url="/account/institutions",
            dedupe_key=f"institution:{institution_id}:membership:{user_id}:{role_enum.value}",
        )
        db.session.commit()
        return membership

    def remove_membership(self, institution_id: int, user_id: int) -> bool:
        membership = self.get_membership(institution_id, user_id)
        if not membership:
            return False
        if membership.role == InstitutionRole.OWNER and self._owner_count(institution_id) <= 1:
            raise ValidationError("Cannot remove the last institution owner")

        user = db.session.get(User, int(user_id))
        if user and int(user.default_institution_id or 0) == int(institution_id):
            user.default_institution_id = None

        institution = db.session.get(Institution, int(institution_id))
        notify_user(
            recipient_user_id=int(user_id),
            notification_type="institution.membership_removed",
            category="profiles",
            severity="warning",
            title="Institution membership removed",
            body=f"Your membership in {institution.display_name or institution.name if institution else 'an institution'} was removed.",
            institution_id=int(institution_id),
            entity_type="institution",
            entity_id=int(institution_id),
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
