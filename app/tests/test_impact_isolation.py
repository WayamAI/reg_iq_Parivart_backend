"""
Multi-tenant isolation.

Organization A must not be able to read organization B's assessments, impact items or
reports, and must not be able to analyze a regulatory change that arrived on B's document.
A cross-tenant reference is indistinguishable from a missing one: 404, never 403 and never
a partial leak.
"""

import uuid

from sqlalchemy.future import select

from app.db.database import AsyncSessionLocal
from app.models.impact import ImpactItem
from app.models.intelligence import ChangeType, ObligationCategory
from app.models.portfolio import Market, Product, ProductMarket
from app.tests.conftest import create_authority, create_change


async def _register_org(client, slug: str):
    """Create a second tenant through the public API and return (org_id, headers)."""
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "user_in": {
                "name": "Other Admin",
                "email": f"admin@{slug}.example.com",
                "password": "otherpassword123",
                "role": "ADMIN",
            },
            "org_in": {
                "name": slug.replace("-", " ").title(),
                "slug": slug,
                "industry": "Medical Devices",
                "description": "Second tenant",
            },
        },
    )
    assert res.status_code == 201, res.text
    org_id = res.json()["organization_id"]

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": f"admin@{slug}.example.com", "password": "otherpassword123"},
    )
    assert login.status_code == 200, login.text
    return org_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _give_org_a_us_portfolio(org_id: str):
    """Minimum portfolio so org B's own analysis genuinely matches something."""
    async with AsyncSessionLocal() as session:
        market = Market(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name="United States",
            country="USA",
            region="North America",
            regulatory_jurisdiction="FDA",
            status="ACTIVE",
        )
        product = Product(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name="Rival Monitor",
            product_code="RM-001",
            category="Monitoring",
            status="ACTIVE",
            keywords="Rival Monitor, Monitoring",
        )
        session.add_all([market, product])
        await session.flush()
        session.add(
            ProductMarket(
                id=str(uuid.uuid4()),
                product_id=product.id,
                market_id=market.id,
                status="ACTIVE",
            )
        )
        await session.commit()
        return product.id


async def _analyze_for(client, headers, org_id):
    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="FDA", jurisdiction="United States", country="USA"
        )
        change_id = await create_change(
            session,
            organization_id=org_id,
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
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return change_id, res.json()


async def test_org_cannot_read_another_orgs_assessment_items_or_report(
    client, demo_org, auth_headers
):
    org_b_id, headers_b = await _register_org(client, "rival-devices")
    await _give_org_a_us_portfolio(org_b_id)

    _, assessment_b = await _analyze_for(client, headers_b, org_b_id)
    assert assessment_b["items"], "org B's own analysis should match its own portfolio"

    report_b = await client.post(
        "/api/v1/reports/generate",
        json={"impact_assessment_id": assessment_b["id"]},
        headers=headers_b,
    )
    assert report_b.status_code == 201, report_b.text
    report_b_id = report_b.json()["id"]

    # Organization A (the demo org) must see none of it.
    assert (
        await client.get(f"/api/v1/impact/{assessment_b['id']}", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/impact/{assessment_b['id']}/items", headers=auth_headers
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/reports/{report_b_id}", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/reports/{report_b_id}/versions", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/impact/{assessment_b['id']}/reanalyze", headers=auth_headers
        )
    ).status_code == 404

    # Nor in any listing.
    listed = await client.get("/api/v1/impact/", headers=auth_headers)
    assert listed.status_code == 200
    assert assessment_b["id"] not in {a["id"] for a in listed.json()}

    listed_reports = await client.get("/api/v1/reports/", headers=auth_headers)
    assert listed_reports.status_code == 200
    assert report_b_id not in {r["id"] for r in listed_reports.json()}


async def test_org_cannot_analyze_a_change_on_another_orgs_document(
    client, demo_org, auth_headers
):
    org_b_id, _ = await _register_org(client, "rival-devices-two")

    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="FDA", jurisdiction="United States", country="USA"
        )
        change_id = await create_change(
            session,
            organization_id=org_b_id,
            authority=authority,
            summary="Labeling requirement published on organization B's document.",
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )

    res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=auth_headers,
    )
    assert res.status_code == 404, res.text


async def test_matching_never_reads_another_orgs_portfolio(client, demo_org, auth_headers):
    """
    Org B owns a US product too. Analysing for the demo org must not produce impact items
    pointing at B's entities -- the ProductMarket join is scoped through Product.
    """
    org_b_id, _ = await _register_org(client, "rival-devices-three")
    rival_product_id = await _give_org_a_us_portfolio(org_b_id)

    _, assessment = await _analyze_for(client, auth_headers, demo_org.id)

    async with AsyncSessionLocal() as session:
        items = (
            await session.execute(
                select(ImpactItem).where(
                    ImpactItem.impact_assessment_id == assessment["id"]
                )
            )
        ).scalars().all()

    assert items
    assert rival_product_id not in {i.entity_id for i in items}
