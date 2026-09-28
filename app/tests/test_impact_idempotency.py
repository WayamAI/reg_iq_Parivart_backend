"""
Idempotency and versioning.

Re-running an analysis must not silently accumulate duplicate assessments or items.
Explicitly re-analysing must produce a new, numbered analysis_version instead of mutating
history, and each report generation must be a new version of the report.
"""

from sqlalchemy import func
from sqlalchemy.future import select

from app.db.database import AsyncSessionLocal
from app.models.impact import ImpactAssessment, ImpactItem, ImpactReport
from app.models.intelligence import ChangeType, ObligationCategory
from app.tests.conftest import create_authority, create_change


async def _change(demo_org) -> str:
    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="FDA", jurisdiction="United States", country="USA"
        )
        return await create_change(
            session,
            organization_id=demo_org.id,
            authority=authority,
            summary=(
                "Mandatory electronic labeling requirements for diagnostic and monitoring "
                "medical devices in the US market."
            ),
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )


async def _count(model, **filters) -> int:
    async with AsyncSessionLocal() as session:
        query = select(func.count()).select_from(model)
        for attr, value in filters.items():
            query = query.where(getattr(model, attr) == value)
        return (await session.execute(query)).scalar()


async def test_repeat_analyze_reuses_the_existing_assessment(
    client, demo_org, auth_headers
):
    change_id = await _change(demo_org)
    payload = {"regulatory_change_id": change_id, "force_reanalyze": False}

    first = await client.post("/api/v1/impact/analyze", json=payload, headers=auth_headers)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/impact/analyze", json=payload, headers=auth_headers)
    assert second.status_code == 201, second.text

    assert second.json()["id"] == first.json()["id"]
    assert second.json()["analysis_version"] == 1

    assert await _count(ImpactAssessment, regulatory_change_id=change_id) == 1
    assert await _count(
        ImpactItem, impact_assessment_id=first.json()["id"]
    ) == len(first.json()["items"])


async def test_force_reanalyze_creates_a_new_version(client, demo_org, auth_headers):
    change_id = await _change(demo_org)

    first = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": False},
        headers=auth_headers,
    )
    assert first.json()["analysis_version"] == 1

    second = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=auth_headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["analysis_version"] == 2

    # History is preserved rather than overwritten.
    assert await _count(ImpactAssessment, regulatory_change_id=change_id) == 2
    assert (
        await client.get(f"/api/v1/impact/{first.json()['id']}", headers=auth_headers)
    ).status_code == 200


async def test_reanalyze_endpoint_versions_forward(client, demo_org, auth_headers):
    change_id = await _change(demo_org)
    first = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": False},
        headers=auth_headers,
    )
    assessment_id = first.json()["id"]

    again = await client.post(
        f"/api/v1/impact/{assessment_id}/reanalyze", headers=auth_headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["analysis_version"] == 2
    assert again.json()["id"] != assessment_id


async def test_report_generation_increments_version(client, demo_org, auth_headers):
    change_id = await _change(demo_org)
    assessment = (
        await client.post(
            "/api/v1/impact/analyze",
            json={"regulatory_change_id": change_id, "force_reanalyze": False},
            headers=auth_headers,
        )
    ).json()

    payload = {"impact_assessment_id": assessment["id"]}
    first = await client.post("/api/v1/reports/generate", json=payload, headers=auth_headers)
    second = await client.post("/api/v1/reports/generate", json=payload, headers=auth_headers)

    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert await _count(ImpactReport, impact_assessment_id=assessment["id"]) == 2

    versions = await client.get(
        f"/api/v1/reports/{second.json()['id']}/versions", headers=auth_headers
    )
    assert versions.status_code == 200
    assert [r["version"] for r in versions.json()] == [2, 1]
