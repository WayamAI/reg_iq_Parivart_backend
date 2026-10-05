"""
Verify the CEO demo tenant against what app/seeds/seed_ceo_demo.py claims to have seeded.

    python -m scripts.verify_ceo_demo

Read-only: it queries, it never writes. Exit code 0 when every check passes, 1 otherwise,
so it can gate a demo.

It checks row counts, but the checks that actually matter are the three it would be easy
not to write:

  * Provenance. Every RegulatoryChange and RegulatoryObligation must have ai_model IS NULL
    and prompt_version IS NULL. This data was produced by deterministic rules, and a demo
    that implied an AI wrote it would be a false claim about the product.
  * Tenant isolation. The pre-existing "asterion-medical-systems" organization must still
    be there exactly once, and none of this tenant's natural keys (FMDA, PROD-001, ...)
    may appear under any other organization. Asserted as a property rather than against a
    hardcoded pre-seed baseline, which would rot the first time anyone touched that tenant.
  * Duplicate natural keys. A reseed that was not idempotent shows up as two authorities
    with the same short_name or two products with the same product_code long before it
    shows up as a wrong total.

Impact-assessment levels are REPORTED, not asserted. They are whatever the matching engine
computed; a verifier that failed on them would be asserting a conclusion the engine owns.
"""

import asyncio
from collections import Counter

from sqlalchemy import func, select

from app.db.database import AsyncSessionLocal, engine
from app.models.document import RegulatoryDocument, RegulatoryVersion
from app.models.governance import Action, AuditEvent, Evidence, ImpactReview
from app.models.impact import ImpactAssessment, ImpactItem
from app.models.intelligence import RegulatoryChange, RegulatoryObligation
from app.models.organization import Organization
from app.models.portfolio import (
    Control,
    Market,
    Process,
    Product,
    ProductMarket,
    Registration,
)
from app.models.regulatory import RegulatoryAuthority, RegulatorySource
from app.models.user import User
from app.seeds.seed_ceo_demo import (
    CEO_DEMO_AUTHORITIES,
    CEO_DEMO_ORG_SLUG,
    CEO_DEMO_PRODUCTS,
    CEO_DEMO_USERS,
)

OTHER_ORG_SLUG = "asterion-medical-systems"

# Final statuses the actions seed walks ACT-001..006 to, by title prefix.
EXPECTED_ACTION_STATUSES = {
    "ACT-001": "IN_PROGRESS",
    "ACT-002": "OPEN",
    "ACT-003": "COMPLETED",
    "ACT-004": "OPEN",
    "ACT-005": "IN_PROGRESS",
    "ACT-006": "OPEN",
}

# Every event type the seed's own writes produce. A zero count for any of them means a
# step ran without leaving a trail.
EXPECTED_AUDIT_EVENTS = (
    "DOCUMENT_UPLOADED",
    "REGULATORY_CHANGE_CREATED",
    "OBLIGATION_CREATED",
    "IMPACT_ASSESSMENT_CREATED",
    "REVIEW_FILED",
    "ACTION_CREATED",
    "ACTION_STATUS_CHANGED",
    "EVIDENCE_ATTACHED",
)

REQ_MARKERS = [f"REQ-{n:03d}" for n in range(1, 11)]


class Report:
    """Collects PASS/FAIL lines and whether anything failed."""

    def __init__(self) -> None:
        self.failed = False

    def check(self, label: str, ok: bool, detail: str) -> None:
        if not ok:
            self.failed = True
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:28} {detail}")

    def note(self, label: str, detail: str) -> None:
        print(f"  [INFO] {label:28} {detail}")

    def count(self, label: str, actual: int, expected: int) -> None:
        self.check(
            label,
            actual == expected,
            f"{actual} (expected {expected})",
        )


async def _count(db, model, *where) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()


async def verify() -> bool:
    report = Report()
    async with AsyncSessionLocal() as db:
        print(f"\nCEO demo verification — {engine.url.render_as_string(hide_password=True)}")

        print("\norganization")
        org = (
            await db.execute(
                select(Organization).where(Organization.slug == CEO_DEMO_ORG_SLUG)
            )
        ).scalars().first()
        report.check("organization", org is not None, CEO_DEMO_ORG_SLUG)
        if org is None:
            print("\nVERDICT: FAIL — the CEO demo organization does not exist; nothing else "
                  "can be checked.")
            return False
        org_id = org.id
        report.note("organization_id", org_id)

        print("\nusers and sources")
        report.count("users", await _count(db, User, User.organization_id == org_id),
                     len(CEO_DEMO_USERS))
        # Authorities and sources are global rows, keyed by the demo's own names.
        short_names = [a["short_name"] for a in CEO_DEMO_AUTHORITIES]
        report.count(
            "authorities",
            await _count(db, RegulatoryAuthority,
                         RegulatoryAuthority.short_name.in_(short_names)),
            len(short_names),
        )
        authority_ids = (
            await db.execute(
                select(RegulatoryAuthority.id).where(
                    RegulatoryAuthority.short_name.in_(short_names)
                )
            )
        ).scalars().all()
        report.count(
            "sources",
            await _count(db, RegulatorySource,
                         RegulatorySource.authority_id.in_(authority_ids)),
            3,
        )

        print("\nportfolio")
        report.count("markets", await _count(db, Market, Market.organization_id == org_id), 5)
        report.count("products", await _count(db, Product, Product.organization_id == org_id), 5)
        report.count("processes", await _count(db, Process, Process.organization_id == org_id), 11)
        report.count("controls", await _count(db, Control, Control.organization_id == org_id), 8)
        report.count(
            "registrations",
            await _count(db, Registration, Registration.organization_id == org_id),
            12,
        )
        # ProductMarket carries no organization_id; it is scoped through Product, the same
        # way the matching engine scopes it.
        product_market_pairs = (
            await db.execute(
                select(ProductMarket.product_id, ProductMarket.market_id)
                .join(Product, Product.id == ProductMarket.product_id)
                .where(Product.organization_id == org_id)
            )
        ).all()
        report.count("product_markets", len(product_market_pairs), 12)
        registration_pairs = set(
            (
                await db.execute(
                    select(Registration.product_id, Registration.market_id).where(
                        Registration.organization_id == org_id
                    )
                )
            ).all()
        )
        report.check(
            "product_markets mirror regs",
            set(product_market_pairs) == registration_pairs,
            f"{len(set(product_market_pairs) & registration_pairs)} of "
            f"{len(registration_pairs)} registration pairs linked",
        )

        print("\ndocument")
        documents = (
            await db.execute(
                select(RegulatoryDocument).where(
                    RegulatoryDocument.organization_id == org_id
                )
            )
        ).scalars().all()
        report.count("documents", len(documents), 1)
        if documents:
            versions = (
                await db.execute(
                    select(RegulatoryVersion).where(
                        RegulatoryVersion.document_id == documents[0].id
                    )
                )
            ).scalars().all()
            report.count("regulatory_versions", len(versions), 1)
            # extracted_text lives on the document, not the version.
            text = documents[0].extracted_text or ""
            missing = [m for m in REQ_MARKERS if m not in text]
            report.check(
                "extracted_text REQ markers",
                not missing,
                f"{len(REQ_MARKERS) - len(missing)}/10 present"
                + (f", missing {missing}" if missing else ""),
            )

        print("\nintelligence (provenance)")
        changes = (
            await db.execute(
                select(RegulatoryChange).join(
                    RegulatoryDocument,
                    RegulatoryDocument.id == RegulatoryChange.document_id,
                ).where(RegulatoryDocument.organization_id == org_id)
            )
        ).scalars().all()
        report.count("regulatory_changes", len(changes), 3)
        change_ids = [c.id for c in changes]
        obligations = (
            await db.execute(
                select(RegulatoryObligation).where(
                    RegulatoryObligation.change_id.in_(change_ids or [""])
                )
            )
        ).scalars().all()
        report.count("obligations", len(obligations), 10)
        tainted = [
            r.id for r in (*changes, *obligations)
            if r.ai_model is not None or r.prompt_version is not None
        ]
        report.check(
            "ai_model/prompt_version NULL",
            not tainted,
            "all deterministic" if not tainted else f"{len(tainted)} row(s) claim AI provenance",
        )

        print("\nimpact and governance")
        assessments = (
            await db.execute(
                select(ImpactAssessment)
                .where(ImpactAssessment.organization_id == org_id)
                .order_by(ImpactAssessment.regulatory_change_id,
                          ImpactAssessment.analysis_version)
            )
        ).scalars().all()
        # One assessment per change is the invariant; a reanalysis adds versions, so the
        # count is of distinct changes, not of rows.
        report.count(
            "assessed changes",
            len({a.regulatory_change_id for a in assessments}),
            3,
        )
        for a in assessments:
            items = await _count(db, ImpactItem, ImpactItem.impact_assessment_id == a.id)
            kinds = Counter(
                (
                    await db.execute(
                        select(ImpactItem.entity_type).where(
                            ImpactItem.impact_assessment_id == a.id
                        )
                    )
                ).scalars().all()
            )
            report.note(
                f"  v{a.analysis_version} {a.regulatory_change_id[:8]}",
                f"{a.overall_impact_level.value} conf={a.overall_confidence} "
                f"status={a.status.value} items={items} "
                f"({', '.join(f'{getattr(k, 'value', k)}={v}' for k, v in sorted(kinds.items(), key=str))})",
            )
        report.count(
            "reviews",
            await _count(db, ImpactReview, ImpactReview.organization_id == org_id),
            4,
        )
        # Reviews are append-only, so the count alone cannot say whether the *current*
        # analysis has been signed off. Checked instead: of the latest version per change,
        # exactly one is unreviewed. That one is the demo's review queue -- a tenant where
        # everything is already accepted has nothing to show -- and anything else means
        # either a reanalysis left an accepted finding stranded behind a newer one, or the
        # queue is empty.
        latest = {}
        for a in assessments:
            if a.analysis_version >= getattr(
                latest.get(a.regulatory_change_id), "analysis_version", 0
            ):
                latest[a.regulatory_change_id] = a
        unreviewed = [
            a for a in latest.values()
            if not await _count(
                db, ImpactReview, ImpactReview.impact_assessment_id == a.id
            )
        ]
        report.check(
            "latest assessment reviewed (1 left in queue)",
            len(unreviewed) == 1,
            f"{len(latest) - len(unreviewed)}/{len(latest)} reviewed, queue: "
            + (", ".join(f"v{a.analysis_version} {a.regulatory_change_id[:8]}"
                         for a in unreviewed) or "empty"),
        )

        actions = (
            await db.execute(select(Action).where(Action.organization_id == org_id))
        ).scalars().all()
        report.count("actions", len(actions), 6)
        statuses = {}
        for action in actions:
            prefix = action.title.split(":")[0].strip()
            statuses[prefix] = getattr(action.status, "value", action.status)
        report.check(
            "action final statuses",
            statuses == EXPECTED_ACTION_STATUSES,
            ", ".join(f"{k}={statuses.get(k, 'MISSING')}"
                      for k in sorted(EXPECTED_ACTION_STATUSES)),
        )
        report.count(
            "evidence",
            await _count(db, Evidence, Evidence.organization_id == org_id),
            6,
        )
        # Actions point at a specific ImpactItem; a reanalysis must not have left them
        # pointing at a row that no longer exists.
        dangling = [
            a.title for a in actions
            if a.impact_item_id
            and not await _count(db, ImpactItem, ImpactItem.id == a.impact_item_id)
        ]
        report.check(
            "action -> impact_item intact",
            not dangling,
            "all resolve" if not dangling else f"dangling: {dangling}",
        )
        # Stronger than "intact": the item must belong to the latest assessment for its
        # change. A superseded item is still a valid foreign key, so the check above passes
        # on an action nobody can reach from the assessment the application displays.
        latest_item_ids = set()
        for a in latest.values():
            latest_item_ids.update(
                (
                    await db.execute(
                        select(ImpactItem.id).where(
                            ImpactItem.impact_assessment_id == a.id
                        )
                    )
                ).scalars().all()
            )
        stale = [
            a.title.split(":")[0] for a in actions
            if a.impact_item_id and a.impact_item_id not in latest_item_ids
        ]
        report.check(
            "action -> latest-version impact_item",
            not stale,
            "all on current analysis" if not stale else f"superseded: {sorted(stale)}",
        )

        print("\naudit trail")
        audit = Counter(
            (
                await db.execute(
                    select(AuditEvent.event_type).where(
                        AuditEvent.organization_id == org_id
                    )
                )
            ).scalars().all()
        )
        for event_type in EXPECTED_AUDIT_EVENTS:
            count = audit.get(event_type, 0)
            report.check(event_type.lower(), count > 0, str(count))
        for event_type, count in sorted(audit.items()):
            if event_type not in EXPECTED_AUDIT_EVENTS:
                report.note(event_type.lower(), f"{count} (additional)")

        print("\nduplicate natural keys")
        for label, column, model, expected in (
            ("authority short_name", RegulatoryAuthority.short_name, RegulatoryAuthority,
             short_names),
            ("product product_code", Product.product_code, Product,
             [p["product_code"] for p in CEO_DEMO_PRODUCTS]),
            ("user email", User.email, User, [u[1] for u in CEO_DEMO_USERS]),
        ):
            values = (
                await db.execute(select(column).where(column.in_(expected)))
            ).scalars().all()
            dupes = [v for v, n in Counter(values).items() if n > 1]
            report.check(label, not dupes,
                         f"{len(values)} row(s), no duplicates" if not dupes else f"duplicated: {dupes}")

        print("\ntenant isolation")
        other = (
            await db.execute(
                select(Organization.id).where(Organization.slug == OTHER_ORG_SLUG)
            )
        ).scalars().all()
        report.check(f"{OTHER_ORG_SLUG}", len(other) == 1, f"{len(other)} row(s)")
        # The real check: none of this tenant's natural keys leaked into another org.
        for label, model, column, expected in (
            ("products elsewhere", Product, Product.product_code,
             [p["product_code"] for p in CEO_DEMO_PRODUCTS]),
            ("users elsewhere", User, User.email, [u[1] for u in CEO_DEMO_USERS]),
        ):
            leaked = (
                await db.execute(
                    select(column).where(
                        column.in_(expected), model.organization_id != org_id
                    )
                )
            ).scalars().all()
            report.check(label, not leaked,
                         "none" if not leaked else f"found under another org: {leaked}")

    print(f"\nVERDICT: {'FAIL' if report.failed else 'PASS'}\n")
    return not report.failed


async def main() -> int:
    ok = await verify()
    await engine.dispose()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
