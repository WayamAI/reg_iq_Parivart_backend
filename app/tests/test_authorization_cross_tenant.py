"""
Role enforcement is additive to tenant scoping, never a substitute for it: an ADMIN in
one organization must not see another organization's data, even though ADMIN passes
every role check in the system.
"""

from app.tests.conftest import teammate_headers


async def test_admin_cannot_read_another_organizations_action(client, demo_org):
    owner = await teammate_headers(client, demo_org.id, "ADMIN")
    created = await client.post(
        "/api/v1/actions/", json={"title": "Org A Action"}, headers=owner
    )
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]

    from app.models.organization import Organization
    import uuid

    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        other_org = Organization(
            id=str(uuid.uuid4()), name="Other Org", slug=f"other-org-{uuid.uuid4().hex[:8]}"
        )
        session.add(other_org)
        await session.commit()
        other_org_id = other_org.id

    other_admin = await teammate_headers(client, other_org_id, "ADMIN")

    response = await client.get(f"/api/v1/actions/{action_id}", headers=other_admin)

    # Cross-tenant, never 200 and never 403 -- an unknown-looking 404, exactly like a
    # same-tenant lookup of a nonexistent id. Role (ADMIN, which passes every
    # permission check) grants no cross-tenant visibility.
    assert response.status_code == 404
