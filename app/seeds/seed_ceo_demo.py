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


async def _exists(db: AsyncSession, model, *conditions) -> bool:
    result = await db.execute(select(model.id).where(*conditions).limit(1))
    return result.scalars().first() is not None


async def seed_ceo_demo(db: AsyncSession) -> dict:
    """
    Seed the CEO demo organization and its four users.

    Returns a summary of what was created versus what was already there, so a caller can
    report it honestly. Every "created" value is 0 on a second run.
    """
    created = {"organizations": 0, "users": 0}
    existing = {"organizations": 0, "users": 0}

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
    await db.commit()
    print(f"CEO demo seed: created={created} existing={existing} (org {org_id})")
    return {"organization_id": org_id, "created": created, "existing": existing}
