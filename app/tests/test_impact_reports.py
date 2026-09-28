"""End-to-end deterministic flow: change -> obligation -> match -> assessment -> report."""

from app.db.database import AsyncSessionLocal
from app.models.intelligence import ChangeType, ObligationCategory
from app.tests.conftest import create_authority, create_change


async def test_impact_and_report_flow(client, demo_org, auth_headers):
    prod_res = await client.get("/api/v1/portfolio/products", headers=auth_headers)
    assert prod_res.status_code == 200, prod_res.text
    assert len(prod_res.json()) >= 5

    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session,
            short_name="FDA",
            jurisdiction="United States",
            country="USA",
            name="US Food and Drug Administration",
        )
        change_id = await create_change(
            session,
            organization_id=demo_org.id,
            authority=authority,
            title="FDA Medical Device Labeling and Cybersecurity Update",
            summary=(
                "Mandatory electronic labeling requirements for diagnostic and monitoring "
                "medical devices in the US market."
            ),
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )

    impact_res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=auth_headers,
    )
    assert impact_res.status_code == 201, impact_res.text
    assessment = impact_res.json()
    assert assessment["status"] == "COMPLETED"
    assert len(assessment["items"]) > 0

    # No AI was involved in producing this assessment, and it says so plainly.
    assert assessment["ai_enrichment_status"] == "DISABLED"
    assert assessment["ai_narrative"] is None
    assert assessment["ai_model"] is None
    assert assessment["engine_version"] == "deterministic-v2"

    report_res = await client.post(
        "/api/v1/reports/generate",
        json={
            "impact_assessment_id": assessment["id"],
            "title": "Asterion US Labeling Delta Report",
        },
        headers=auth_headers,
    )
    assert report_res.status_code == 201, report_res.text
    report = report_res.json()
    assert report["title"] == "Asterion US Labeling Delta Report"
    for section in (
        "FACT",
        "SOURCE_EVIDENCE",
        "RESULTING_OBLIGATIONS",
        "SYSTEM_INTERPRETATION",
        "AI_ENRICHMENT",
        "HUMAN_DECISION",
    ):
        assert section in report["report_data"], section

    get_rep = await client.get(f"/api/v1/reports/{report['id']}", headers=auth_headers)
    assert get_rep.status_code == 200
    assert get_rep.json()["id"] == report["id"]
