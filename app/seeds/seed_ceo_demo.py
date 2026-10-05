"""
The CEO demo tenant: a synthetic organization built for a walkthrough.

Deliberately a separate organization from the existing demo seed's
"asterion-medical-systems". A demo narrative needs to add, rename and transition
records freely; doing that in the shared demo tenant would rewrite data the rest of
the suite and the existing demo login depend on. Nothing here touches that tenant.

Idempotent per entity, like app/seeds/demo_data.py: every row is checked by its natural
key before insert, so a second run creates nothing and the ids stay stable.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import hash_password
from app.models.organization import Organization
from app.models.regulatory import (
    ConnectorType,
    RegulatoryAuthority,
    RegulatorySource,
    SourceType,
)
from app.models.user import User, UserRole

# The CEO demo organization every entity in this module belongs to, and its idempotency
# key.
CEO_DEMO_ORG_SLUG = "asterion-parivart-ceo-demo"

# Email is the natural key -- the column is unique, and the role is what the demo
# actually exercises.
CEO_DEMO_USERS = [
    ("Maya Chen", "demo.admin@asterion-parivart.example", UserRole.ADMIN),
    ("Daniel Rao", "regulatory.analyst@asterion-parivart.example", UserRole.ANALYST),
    ("Sofia Martinez", "regulatory.reviewer@asterion-parivart.example", UserRole.REVIEWER),
    ("James Wilson", "quality.lead@asterion-parivart.example", UserRole.COMPLIANCE_MANAGER),
]

# Shared demo password, same convention as demo_data.py's seeded logins: a known weak
# credential for a synthetic tenant, never printed and never reused outside it.
CEO_DEMO_PASSWORD = "parivart-demo-2026"

# regulatory_authorities is global, not org-scoped, and short_name is unique. These five
# synthetic short names are deliberately distinct from demo_data.py's real-world
# FDA/EMA/MHRA/CDSCO/HC rows so the two seeds never contend for the same row.
CEO_DEMO_AUTHORITIES = [
    {
        "short_name": "FMDA",
        "name": "Federal Medical Device Authority (FMDA)",
        "jurisdiction": "United States",
        "country": "USA",
        "description": (
            "Synthetic demo authority for medical devices-software oversight, including "
            "device cybersecurity and premarket software documentation."
        ),
    },
    {
        "short_name": "EMDA",
        "name": "European Medical Device Authority (EMDA)",
        "jurisdiction": "European Union",
        "country": "EU",
        "description": (
            "Synthetic demo authority for medical devices-software oversight across the "
            "European Union."
        ),
    },
    {
        "short_name": "UKDSA",
        "name": "United Kingdom Device Safety Authority (UKDSA)",
        "jurisdiction": "United Kingdom",
        "country": "UK",
        "description": (
            "Synthetic demo authority for medical devices-software safety in the United "
            "Kingdom."
        ),
    },
    {
        "short_name": "IMDA",
        "name": "Indian Medical Device Authority (IMDA)",
        "jurisdiction": "India",
        "country": "IN",
        "description": (
            "Synthetic demo authority for medical devices-software registration in India."
        ),
    },
    {
        "short_name": "CDA",
        "name": "Canadian Device Authority (CDA)",
        "jurisdiction": "Canada",
        "country": "CA",
        "description": (
            "Synthetic demo authority for medical devices-software licensing in Canada."
        ),
    },
]

# Keyed on (authority short_name, name): name alone is not unique across authorities.
CEO_DEMO_SOURCES = [
    {
        "authority": "FMDA",
        "name": "FMDA Regulatory Bulletins",
        "source_type": SourceType.RSS,
        "connector_type": ConnectorType.RSS,
        "url": "https://demo.parivart.invalid/fmda/rss",
    },
    {
        "authority": "EMDA",
        "name": "EMDA Safety & Compliance Notices",
        "source_type": SourceType.WEB_SERVICE,
        "connector_type": ConnectorType.WEB_SERVICE,
        "url": "https://demo.parivart.invalid/emda/notices",
    },
    {
        # Manual uploads: no URL to poll, the connector reads documents handed to it.
        "authority": "FMDA",
        "name": "Synthetic Regulatory Uploads",
        "source_type": SourceType.DOCUMENT,
        "connector_type": ConnectorType.DOCUMENT,
        "url": None,
    },
]


async def _exists(db: AsyncSession, model, *conditions) -> bool:
    result = await db.execute(select(model.id).where(*conditions).limit(1))
    return result.scalars().first() is not None


async def seed_ceo_demo(db: AsyncSession) -> dict:
    """
    Seed the CEO demo organization and its four users.

    Returns a summary of what was created versus what was already there, so a caller can
    report it honestly. Every "created" value is 0 on a second run.
    """
    counters = ("organizations", "users", "authorities", "sources")
    created = dict.fromkeys(counters, 0)
    existing = dict.fromkeys(counters, 0)

    org = (
        await db.execute(
            select(Organization).where(Organization.slug == CEO_DEMO_ORG_SLUG)
        )
    ).scalars().first()
    if org is None:
        org = Organization(
            id=str(uuid.uuid4()),
            name="Asterion Medical Systems — PARIVART Demo",
            slug=CEO_DEMO_ORG_SLUG,
            industry="Medical Devices",
            description=(
                "Synthetic demonstration tenant for the PARIVART regulatory intelligence "
                "walkthrough."
            ),
        )
        db.add(org)
        # Flushed before the users below: they carry organization_id as a foreign key.
        await db.flush()
        created["organizations"] += 1
    else:
        existing["organizations"] += 1
    org_id = org.id

    for name, email, role in CEO_DEMO_USERS:
        if await _exists(db, User, User.email == email):
            existing["users"] += 1
            continue
        db.add(
            User(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                name=name,
                email=email,
                password_hash=hash_password(CEO_DEMO_PASSWORD),
                role=role,
                is_active=True,
            )
        )
        created["users"] += 1

    await db.flush()

    # Authorities are global rows; a missing short_name is the only reason to insert one.
    for auth_data in CEO_DEMO_AUTHORITIES:
        if await _exists(
            db, RegulatoryAuthority,
            RegulatoryAuthority.short_name == auth_data["short_name"],
        ):
            existing["authorities"] += 1
            continue
        db.add(RegulatoryAuthority(id=str(uuid.uuid4()), is_active=True, **auth_data))
        created["authorities"] += 1
    # Flushed before the sources: they carry authority_id as a foreign key.
    await db.flush()

    # Re-queried rather than reused from the loop above: on a second run the authority
    # objects were never added to this session, so only a query has their ids.
    authority_ids = dict(
        (
            await db.execute(
                select(RegulatoryAuthority.short_name, RegulatoryAuthority.id).where(
                    RegulatoryAuthority.short_name.in_(
                        [a["short_name"] for a in CEO_DEMO_AUTHORITIES]
                    )
                )
            )
        ).all()
    )

    for source_data in CEO_DEMO_SOURCES:
        authority_id = authority_ids[source_data["authority"]]
        if await _exists(
            db, RegulatorySource,
            RegulatorySource.authority_id == authority_id,
            RegulatorySource.name == source_data["name"],
        ):
            existing["sources"] += 1
            continue
        fields = {k: v for k, v in source_data.items() if k != "authority"}
        db.add(
            RegulatorySource(
                id=str(uuid.uuid4()),
                authority_id=authority_id,
                enabled=True,
                **fields,
            )
        )
        created["sources"] += 1

    await db.flush()
    await db.commit()
    print(f"CEO demo seed: created={created} existing={existing} (org {org_id})")
    return {"organization_id": org_id, "created": created, "existing": existing}
