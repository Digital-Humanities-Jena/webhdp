import logging
import re
from typing import Optional

from sqlalchemy import func, or_

from database.database import db
from database.models import InstitutionMembership, User, UserMfaChallenge, UserRole
from exceptions import ValidationError, ResourceNotFoundError
from services.email_identity import email_for_delivery, normalize_email
from services.notification_service import notify_admins

logger = logging.getLogger(__name__)


INTERNAL_PROFILE_VISIBILITIES = {"private", "internal"}


def validate_new_password(password: object) -> None:
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValidationError("Choose a password between 8 and 128 characters.")
    try:
        password.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError("Choose a password with valid Unicode characters.") from exc


def slugify_user_profile(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text[:120]


def _unique_user_slug(base_value: str, *, exclude_user_id: int | None = None) -> str | None:
    slug_base = slugify_user_profile(base_value)
    if not slug_base:
        return None
    slug = slug_base
    suffix = 1
    while True:
        query = User.query.filter_by(slug=slug)
        if exclude_user_id is not None:
            query = query.filter(User.id != int(exclude_user_id))
        if not query.first():
            return slug
        suffix += 1
        trimmed_base = slug_base[: max(1, 120 - len(str(suffix)) - 1)]
        slug = f"{trimmed_base}-{suffix}"


class UserService:
    """Service for user management and authentication"""

    def add_user(self, email: str, password: str, *, role: UserRole = UserRole.USER, verified: bool = False) -> User:
        """Add an account to the caller's database transaction."""
        email = email_for_delivery(email)
        user = User(
            email=email,
            canonical_email=normalize_email(email),
            slug=_unique_user_slug(email.split("@", 1)[0]),
            role=role,
            is_verified=verified,
            onboarding_required=(role == UserRole.USER),
        )
        user.set_capabilities([])
        user.set_password(password)
        db.session.add(user)
        return user

    def create_user(self, email: str, password: str, role: UserRole = UserRole.USER) -> User:
        """Create an account from a trusted caller, such as CLI bootstrap."""
        if self.find_accounts_for_email(email):
            raise ValidationError("Email already registered")
        user = self.add_user(email, password, role=role, verified=role == UserRole.ADMIN)
        db.session.commit()
        self.notify_registration(user)
        logger.info("User created: user_id=%s, role=%s", user.id, role.value)
        return user

    def set_initial_admin_credentials(self, email: str, password: str) -> User:
        """Initialize the configured administrator using operator-provided credentials."""
        validate_new_password(password)
        accounts = self.find_accounts_for_email(email)
        if len(accounts) > 1:
            raise ValidationError("This email matches multiple accounts. Resolve the legacy address conflict first.")
        if accounts:
            user = accounts[0]
            user.role = UserRole.ADMIN
            user.is_verified = True
            user.canonical_email = normalize_email(email)
            user.legacy_canonical_email = None
            user.verification_token = None
            user.token_version = int(user.token_version or 0) + 1
            user.force_password_change = False
            user.onboarding_required = False
            user.set_password(password)
            self.invalidate_pending_mfa(user)
        else:
            user = self.add_user(email, password, role=UserRole.ADMIN, verified=True)
        db.session.commit()
        return user

    def invalidate_pending_mfa(self, user: User) -> None:
        UserMfaChallenge.query.filter_by(user_id=user.id, consumed_at=None).delete(synchronize_session=False)

    def notify_registration(self, user: User) -> None:
        try:
            notify_admins(
                exclude_user_id=user.id,
                notification_type="admin.user_registered",
                category="admin",
                severity="info",
                title="New user registered",
                body=f"{user.email} created a WebHDP account.",
                entity_type="user",
                entity_id=user.id,
                action_url=f"/profiles/users/{user.slug or user.public_id or user.id}",
                payload={"user_id": user.id, "email": user.email, "role": user.role.value if user.role else "user"},
                dedupe_key=f"admin:user_registered:{user.id}",
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Could not notify administrators of verified user ID %s.", user.id)

    def find_accounts_for_email(self, email: str) -> list[User]:
        """Return up to two accounts so callers can detect legacy identity collisions."""
        key = normalize_email(email)
        return User.query.filter(or_(
            User.canonical_email == key,
            User.legacy_canonical_email == key,
            func.lower(User.email) == key,
        )).order_by(User.id).limit(2).all()

    def authenticate(self, email: str, password: str) -> Optional[User]:
        """
        Authenticate user with email and password.

        Args:
            email: User email
            password: Plain text password

        Returns:
            User object if authenticated, None otherwise
        """
        user = User.query.filter_by(email=email).first()
        if user is None:
            try:
                user = self.get_by_email(email)
            except ValidationError:
                return None
        if user and user.check_password(password):
            return user
        return None

    def get_by_id(self, user_id: int) -> User:
        """
        Get user by ID.

        Args:
            user_id: User ID

        Returns:
            User object

        Raises:
            ResourceNotFoundError: If user not found
        """
        user = db.session.get(User, user_id)
        if not user:
            raise ResourceNotFoundError(f"User {user_id} not found")
        return user

    def get_by_email(self, email: str) -> Optional[User]:
        """Get an account by its canonical email when that identity is unambiguous."""
        accounts = self.find_accounts_for_email(email)
        return accounts[0] if len(accounts) == 1 else None

    def update_password(self, user: User, current_password: str, new_password: str) -> User:
        """
        Update user's password after validating current password.

        Raises:
            ValidationError: If inputs are invalid.
        """
        if not current_password or not new_password:
            raise ValidationError("Current password and new password are required")

        if not user.check_password(current_password):
            raise ValidationError("Current password is incorrect")

        if len(new_password) < 8:
            raise ValidationError("New password must be at least 8 characters")

        if current_password == new_password:
            raise ValidationError("New password must be different from current password")

        user.set_password(new_password)
        user.force_password_change = False
        user.token_version = int(user.token_version or 0) + 1
        self.invalidate_pending_mfa(user)
        db.session.commit()
        logger.info(f"Updated password for user_id={user.id}")
        return user

    def update_capabilities(self, user: User, capabilities: list[str]) -> User:
        user.set_capabilities(capabilities or [])
        db.session.commit()
        logger.info("Updated capabilities for user_id=%s", user.id)
        return user

    def update_profile(self, user: User, payload: dict) -> User:
        data = payload or {}

        if "email" in data and str(data.get("email") or "").strip() != user.email:
            raise ValidationError("Changing the verified sign-in email requires account support.")

        for field in ("display_name", "full_name", "affiliation", "orcid", "bio", "website_url", "avatar_url"):
            if field not in data:
                continue
            value = str(data.get(field) or "").strip()
            setattr(user, field, value or None)

        if "slug" in data:
            raw_slug = str(data.get("slug") or "").strip()
            if raw_slug:
                slug = slugify_user_profile(raw_slug)
                if not slug:
                    raise ValidationError("slug must contain alphanumeric characters")
                existing = User.query.filter(User.slug == slug, User.id != user.id).first()
                if existing:
                    raise ValidationError("slug is already in use")
                user.slug = slug
            else:
                user.slug = _unique_user_slug(user.display_name or user.full_name or user.email.split("@", 1)[0], exclude_user_id=user.id)
        elif not user.slug:
            user.slug = _unique_user_slug(user.display_name or user.full_name or user.email.split("@", 1)[0], exclude_user_id=user.id)

        if "profile_visibility" in data:
            visibility = str(data.get("profile_visibility") or "private").strip().lower()
            if visibility not in INTERNAL_PROFILE_VISIBILITIES:
                raise ValidationError("profile_visibility must be private or internal")
            user.profile_visibility = visibility

        for field in ("show_email", "show_orcid", "show_affiliation"):
            if field in data:
                user_value = data.get(field)
                user_bool = user_value if isinstance(user_value, bool) else str(user_value or "").strip().lower() in {"1", "true", "yes", "on"}
                setattr(user, field, bool(user_bool))

        if "default_institution_id" in data:
            raw_institution_id = data.get("default_institution_id")
            if raw_institution_id in ("", None):
                user.default_institution_id = None
            else:
                try:
                    institution_id = int(raw_institution_id)
                except (TypeError, ValueError) as exc:
                    raise ValidationError("default_institution_id must be an integer") from exc

                membership = InstitutionMembership.query.filter_by(
                    institution_id=institution_id,
                    user_id=user.id,
                ).first()
                if not membership:
                    raise ValidationError("default_institution_id must reference one of your institutions")
                user.default_institution_id = institution_id

        db.session.commit()
        logger.info("Updated profile for user_id=%s", user.id)
        return user
