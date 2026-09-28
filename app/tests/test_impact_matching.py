"""
Deterministic matching behaviour.

These tests run with no AI provider registered and AI_ENRICHMENT_ENABLED=false, which is
the point: the engine must reach a complete, defensible answer on database evidence alone.
"""

import json

from sqlalchemy.future import select

from app.db.database import AsyncSessionLocal
from app.matching.rules import ENGINE_VERSION
from app.models.intelligence import ChangeType, ObligationCategory
from app.models.portfolio import Product, ProductMarket
from app.tests.conftest import create_authority, create_change


async def _fda_labeling_change(demo_org):
    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="FDA", jurisdiction="United States", country="USA"
        )
        return await create_change(
            session,
            organization_id=demo_org.id,
            authority=authority,
            title="FDA Labeling Update",
            summary=(
                "Mandatory electronic labeling requirements for diagnostic and monitoring "
                "medical devices in the US market."
            ),
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )


async def test_deterministic_chain_produces_evidence_backed_items(
    client, demo_org, auth_headers
):
    change_id = await _fda_labeling_change(demo_org)

    res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    assessment = res.json()

    assert assessment["engine_version"] == ENGINE_VERSION
    assert assessment["items"], "deterministic matching produced no items"

    by_type = {}
    for item in assessment["items"]:
        by_type.setdefault(item["entity_type"], []).append(item)

    # The FDA reaches the US market on three independent axes, so that market is matched.
    assert "MARKET" in by_type
    market_item = by_type["MARKET"][0]
    axes = {s["axis"] for s in json.loads(market_item["evidence"])["signals"]}
    assert axes == {"authority_short_name", "jurisdiction", "country"}
    assert market_item["confidence"] == 0.90  # three independent axes

    # A LABELING obligation exists, so the Labeling process and Labeling control match.
    assert "Labeling" in by_type["PROCESS"][0]["reason"]
    assert "Labeling Review Process" in by_type["CONTROL"][0]["reason"]

    # Every item states a MatchType and explains itself.
    for item in assessment["items"]:
        assert item["match_types"], item
        assert item["reason"].strip()
        assert 0.0 < item["match_score"] <= 1.0
        assert 0.0 < item["confidence"] <= 1.0


async def test_products_outside_a_resolved_market_are_not_reported(
    client, demo_org, auth_headers
):
    """
    The seed links only two products to markets. The other three have no ProductMarket row
    for the US market, so no evidence connects them to an FDA change and they must be
    absent -- rather than swept in by an "assume everything matches" fallback.
    """
    change_id = await _fda_labeling_change(demo_org)

    res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=auth_headers,
    )
    assert res.status_code == 201
    reported_product_ids = {
        i["entity_id"] for i in res.json()["items"] if i["entity_type"] == "PRODUCT"
    }

    async with AsyncSessionLocal() as session:
        all_products = (
            await session.execute(
                select(Product).where(Product.organization_id == demo_org.id)
            )
        ).scalars().all()
        linked_product_ids = {
            pm.product_id
            for pm in (await session.execute(select(ProductMarket))).scalars().all()
        }

    assert reported_product_ids
    assert reported_product_ids <= linked_product_ids
    unlinked = {p.id for p in all_products} - linked_product_ids
    assert unlinked, "fixture assumption: some products have no market link"
    assert not (reported_product_ids & unlinked)


async def test_change_with_no_portfolio_link_yields_no_match(client, demo_org, auth_headers):
    """An authority the organization has no market for must produce a clean NO_MATCH."""
    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="PMDA", jurisdiction="Japan", country="JP"
        )
        change_id = await create_change(
            session,
            organization_id=demo_org.id,
            authority=authority,
            title="Japanese Sterilisation Requirement",
            summary="Revised sterilisation validation requirement for the Japanese market.",
            change_type=ChangeType.REQUIREMENT_CHANGE,
        )

    res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    assessment = res.json()
    assert assessment["status"] == "COMPLETED"
    assert assessment["overall_impact_level"] == "NO_MATCH"
    assert assessment["items"] == []

    # A no-match result is still reportable, and must not invent impact.
    report_res = await client.post(
        "/api/v1/reports/generate",
        json={"impact_assessment_id": assessment["id"]},
        headers=auth_headers,
    )
    assert report_res.status_code == 201, report_res.text
    data = report_res.json()["report_data"]
    assert data["SYSTEM_INTERPRETATION"]["affected_portfolio_count"] == 0
    assert data["RESULTING_OBLIGATIONS"]["status"] == "UNASSESSED"
    assert data["HUMAN_DECISION"]["status"] == "UNASSESSED"
    assert data["HUMAN_DECISION"]["recommended_actions"] == []
