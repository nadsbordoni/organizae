from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.auth.exceptions import InvalidAccessTokenError
from app.modules.business_categories.models import BusinessCategory
from app.modules.businesses.exceptions import (
    BusinessCategoryNotFoundError,
    BusinessConflictError,
    BusinessNotFoundError,
    BusinessNotPublishableError,
    InvalidBusinessPaginationError,
)
from app.modules.businesses.models import Business
from app.modules.businesses.repository import BusinessRepository
from app.modules.businesses.schemas import (
    BusinessCreate,
    BusinessUpdate,
    PublicPageResponse,
    PublicPageServiceResponse,
)
from app.modules.users.repository import UserRepository

# The column holds 80 characters; this leaves room for the "-<n>" suffix used
# when two businesses share a name.
SLUG_BASE_MAX_LENGTH = 70


def slugify(name: str) -> str:
    """Turn "Salão da Ana" into "salao-da-ana"."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug[:SLUG_BASE_MAX_LENGTH].rstrip("-") or "pagina"


class BusinessService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = BusinessRepository(session)
        self.user_repository = UserRepository(session)

    def get_by_id(self, business_id: UUID) -> Business:
        business = self.repository.get_by_id(business_id)
        if business is None:
            raise BusinessNotFoundError("Business not found")
        return business

    def list(
        self, *, business_id: UUID | None = None, offset: int = 0, limit: int = 100
    ) -> list[Business]:
        if offset < 0 or limit < 1:
            raise InvalidBusinessPaginationError(
                "offset must be non-negative and limit must be positive"
            )
        return self.repository.list(business_id=business_id, offset=offset, limit=limit)

    def create(self, business_data: BusinessCreate) -> Business:
        with self._transaction():
            self._validate_category(business_data.category_id)
            business = self.repository.create(business_data)
            self.session.commit()
            self.session.refresh(business)
        return business

    def create_for_user(
        self, business_data: BusinessCreate, *, user_id: UUID
    ) -> Business:
        with self._transaction():
            # Reload under a row lock: concurrent onboarding requests must serialize.
            user = self.user_repository.get_by_id_for_update(user_id)
            if user is None or not user.is_active:
                raise InvalidAccessTokenError("Could not validate credentials")
            if user.business_id is not None:
                raise BusinessConflictError("User already has a business")
            self._validate_category(business_data.category_id)
            business = self.repository.create(business_data)
            self.user_repository.update(user, business_id=business.id)
            self.session.commit()
            self.session.refresh(business)
        return business

    def update(self, business_id: UUID, business_data: BusinessUpdate) -> Business:
        with self._transaction():
            business = self.get_by_id(business_id)

            if business_data.category_id is not None:
                self._validate_category(business_data.category_id)

            business = self.repository.update(business, business_data)
            self.session.commit()
            self.session.refresh(business)

        return business

    def delete(self, business_id: UUID) -> None:
        with self._transaction():
            if not self.repository.delete(business_id):
                raise BusinessNotFoundError("Business not found")
            self.session.commit()

    def publish(self, business_id: UUID) -> Business:
        with self._transaction():
            # Row lock: two clicks on "Publicar" must not generate two slugs.
            business = self.repository.get_by_id_for_update(business_id)
            if business is None:
                raise BusinessNotFoundError("Business not found")
            if business.is_published:
                return business

            missing_fields = self._missing_fields_to_publish(business)
            if missing_fields:
                raise BusinessNotPublishableError(missing_fields)

            business = self.repository.publish(
                business,
                slug=business.slug or self._generate_unique_slug(business.name),
                published_at=datetime.now(UTC),
            )
            self.session.commit()
            self.session.refresh(business)
        return business

    def get_public_page(self, slug: str) -> PublicPageResponse:
        business = self.repository.get_published_by_slug(slug)
        if business is None:
            # Same answer for "never existed" and "not published yet".
            raise BusinessNotFoundError("Business page not found")

        services = self.repository.list_active_services(business.id)
        return PublicPageResponse(
            id=business.id,
            slug=business.slug,
            name=business.name,
            logo_url=business.logo_url,
            description=business.description,
            whatsapp=business.whatsapp,
            instagram=business.instagram,
            address=business.address,
            service_mode=business.service_mode,
            services=[
                PublicPageServiceResponse.model_validate(service)
                for service in services
            ],
        )

    def _missing_fields_to_publish(self, business: Business) -> list[str]:
        # Name and WhatsApp are already mandatory when the business is created.
        missing_fields = []
        if not (business.description or "").strip():
            missing_fields.append("description")
        if not self.repository.has_active_services(business.id):
            missing_fields.append("services")
        return missing_fields

    def _generate_unique_slug(self, name: str) -> str:
        base_slug = slugify(name)
        slug = base_slug
        suffix = 2
        while self.repository.slug_exists(slug):
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        return slug

    def _validate_category(self, category_id: int) -> None:
        if self.session.get(BusinessCategory, category_id) is None:
            raise BusinessCategoryNotFoundError("Business category not found")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            yield

        except IntegrityError as exc:
            self.session.rollback()
            raise BusinessConflictError(
                "Operation conflicts with related data or database constraints"
            ) from exc

        except Exception:
            # Cleanup must also cover unexpected errors without hiding them.
            self.session.rollback()
            raise
