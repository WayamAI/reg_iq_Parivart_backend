"""
Shared test fixtures.

Environment is pinned before `app.core.config` is imported anywhere, so the whole suite
runs against an in-memory SQLite database and never touches a real Postgres instance or an
external AI provider.
"""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing"
os.environ["FRONTEND_ORIGIN"] = "http://localhost:3000"
os.environ["AI_ENRICHMENT_ENABLED"] = "false"
os.environ["DEMO_AUTH_ALLOW_ANY"] = "false"

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from httpx import ASGITransport, AsyncClient

from app.db.base import Base
from app.db.database import AsyncSessionLocal, engine
from app.main import app
from app.models.document import RegulatoryDocument
from app.models.intelligence import (
    ChangeType,
    ObligationCategory,
    RegulatoryChange,
    RegulatoryObligation,
)
from app.models.user import User
from app.models.regulatory import (
    ConnectorType,
    RegulatoryAuthority,
    RegulatorySource,
    SourceType,
)
from app.seeds.demo_data import seed_demo_data

# SQLite disables foreign key enforcement by default; PostgreSQL does not. Without this,
# a dangling foreign key passes in tests and only fails in production.
@event.listens_for(engine.sync_engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# The in-memory database lives on a single StaticPool connection, so the schema is rebuilt
# per test to keep tests independent of each other's writes.
@pytest_asyncio.fixture(autouse=True)
async def fresh_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    # follow_redirects mirrors a real client: collection routes are registered at "/"
    # and FastAPI 307s "/products" -> "/products/".
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def demo_org():
    """The seeded Asterion Medical Systems organization."""
    async with AsyncSessionLocal() as session:
        org = await seed_demo_data(session)
        await session.refresh(org)
        return org


@pytest_asyncio.fixture
async def auth_headers(client, demo_org):
    res = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@asterion.com", "password": "admin123"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def role_headers(client, role: str, organization_id: str | None = None) -> dict:
    """
    Register a fresh user with the given role (in their own new organization, via the
    public /auth/register endpoint) and return their auth header.

    Used for authorization tests: the user is intentionally NOT in the demo
    organization, so a test exercising a cross-tenant-denied case can use this directly,
    and a same-tenant role-denied case should instead use a role-only check (the
    permission dependency, not tenant scoping, is what's under test there).
    """
    suffix = uuid.uuid4().hex[:8]
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "user_in": {
                "name": f"{role} Test User",
                # email-validator rejects reserved/special-use TLDs like .invalid; a
                # unique local part under a real-shaped domain satisfies validation
                # without this ever being a deliverable address.
                "email": f"{role.lower()}-{suffix}@example.com",
                "password": "testpassword123",
                "role": role,
            },
            "org_in": {
                "name": f"Role Test Org {suffix}",
                "slug": f"role-test-org-{suffix}",
            },
        },
    )
    assert register.status_code == 201, register.text

    login = await client.post(
        "/api/v1/auth/login",
        data={
            "username": f"{role.lower()}-{suffix}@example.com",
            "password": "testpassword123",
        },
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def create_authority(
    session, short_name: str, jurisdiction: str, country: str, name: str = None
) -> RegulatoryAuthority:
    """Get-or-update an authority. short_name is unique and the demo seed creates several."""
    existing = (
        await session.execute(
            select(RegulatoryAuthority).where(
                RegulatoryAuthority.short_name == short_name
            )
        )
    ).scalars().first()
    if existing is not None:
        existing.jurisdiction = jurisdiction
        existing.country = country
        await session.flush()
        return existing

    authority = RegulatoryAuthority(
        id=str(uuid.uuid4()),
        name=name or f"{short_name} Authority",
        short_name=short_name,
        jurisdiction=jurisdiction,
        country=country,
        is_active=True,
    )
    session.add(authority)
    await session.flush()
    return authority


async def create_change(
    session,
    organization_id: str,
    authority: RegulatoryAuthority,
    *,
    title: str = "Regulatory Update",
    summary: str,
    change_type: ChangeType = ChangeType.LABELING_CHANGE,
    obligation_category: ObligationCategory = None,
    obligation_text: str = "Affected devices must carry updated electronic labeling.",
) -> str:
    """Create a document + change (+ optional obligation) owned by `organization_id`."""
    source = RegulatorySource(
        id=str(uuid.uuid4()),
        authority_id=authority.id,
        name=f"{authority.short_name} Test Source {uuid.uuid4().hex[:8]}",
        jurisdiction=authority.jurisdiction,
        country=authority.country,
        source_type=SourceType.DOCUMENT,
        connector_type=ConnectorType.DOCUMENT,
        enabled=True,
    )
    session.add(source)
    await session.flush()

    document = RegulatoryDocument(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        authority_id=authority.id,
        source_id=source.id,
        title=title,
        document_type="REGULATION",
        jurisdiction=authority.jurisdiction,
        country=authority.country,
        sha256=uuid.uuid4().hex,
        processing_status="ANALYZED",
        publication_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    session.add(document)
    await session.flush()

    change = RegulatoryChange(
        id=str(uuid.uuid4()),
        document_id=document.id,
        section="Section 4.2",
        change_type=change_type,
        summary=summary,
        confidence=0.95,
    )
    session.add(change)
    await session.flush()

    if obligation_category is not None:
        session.add(
            RegulatoryObligation(
                id=str(uuid.uuid4()),
                change_id=change.id,
                document_id=document.id,
                text=obligation_text,
                category=obligation_category,
                jurisdiction=authority.jurisdiction,
                source_section="Section 4.2",
                confidence=0.9,
            )
        )

    await session.commit()
    return change.id


@pytest_asyncio.fixture
async def seeded_assessment(client, demo_org, auth_headers):
    """
    A real assessment produced by a real deterministic analysis, plus the ids the
    governance tests hang off it.

    Built through the HTTP analyze endpoint rather than by inserting rows, so the
    impact items are the ones the matching engine actually produces and an action or
    a piece of evidence attached to one is attached to something real.
    """
    from app.models.impact import ImpactItem
    from app.models.intelligence import ChangeType, ObligationCategory

    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="FDA", jurisdiction="United States", country="USA"
        )
        change_id = await create_change(
            session,
            organization_id=demo_org.id,
            authority=authority,
            summary=(
                "Mandatory electronic labeling requirements for monitoring medical "
                "devices in the US market."
            ),
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )

    res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    assessment_id = res.json()["id"]

    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(User.organization_id == demo_org.id)
            )
        ).scalars().first()
        item = (
            await session.execute(
                select(ImpactItem).where(
                    ImpactItem.impact_assessment_id == assessment_id
                )
            )
        ).scalars().first()
        assert item is not None, "the analysis produced no impact items to attach to"
        return {
            "assessment_id": assessment_id,
            "regulatory_change_id": change_id,
            "user_id": user.id,
            "impact_item_id": item.id,
        }
