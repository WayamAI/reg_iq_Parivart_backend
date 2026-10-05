"""
The CEO demo tenant: a synthetic organization built for a walkthrough.

Deliberately a separate organization from the existing demo seed's
"asterion-medical-systems". A demo narrative needs to add, rename and transition
records freely; doing that in the shared demo tenant would rewrite data the rest of
the suite and the existing demo login depend on. Nothing here touches that tenant.

Idempotent per entity, like app/seeds/demo_data.py: every row is checked by its natural
key before insert, so a second run creates nothing and the ids stay stable.
"""

import io
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import hash_password
from app.models.document import DocumentType, RegulatoryVersion
from app.models.intelligence import (
    ChangeType,
    ObligationCategory,
    RegulatoryChange,
    RegulatoryObligation,
)
from app.models.impact import ImpactAssessment
from app.models.organization import Organization
from app.models.portfolio import (
    Control,
    ControlCategory,
    ControlStatus,
    Market,
    MarketStatus,
    Process,
    Product,
    ProductStatus,
    Registration,
    RegistrationStatus,
)
from app.models.regulatory import (
    ConnectorType,
    RegulatoryAuthority,
    RegulatorySource,
    SourceType,
)
from app.models.user import User, UserRole
from app.matching.engine import MatchingEngineService
from app.services.audit_service import (
    ENTITY_REGULATORY_CHANGE,
    ENTITY_REGULATORY_OBLIGATION,
    EVENT_OBLIGATION_CREATED,
    EVENT_REGULATORY_CHANGE_CREATED,
    AuditService,
)
from app.services.document_processing import process_document
from app.services.document_service import upload_and_create_document

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

# country values follow demo_data.py's convention for the same five markets (USA/EU/UK/
# IN/CA) so the two tenants describe the same jurisdictions the same way.
CEO_DEMO_MARKETS = [
    {"name": "United States", "country": "USA", "region": "North America", "regulatory_jurisdiction": "FMDA"},
    {"name": "European Union", "country": "EU", "region": "Europe", "regulatory_jurisdiction": "EMDA"},
    {"name": "United Kingdom", "country": "UK", "region": "Europe", "regulatory_jurisdiction": "UKDSA"},
    {"name": "India", "country": "IN", "region": "Asia", "regulatory_jurisdiction": "IMDA"},
    {"name": "Canada", "country": "CA", "region": "North America", "regulatory_jurisdiction": "CDA"},
]

# product_code is globally unique, not per-organization: the PROD-00N codes are distinct
# from demo_data.py's APS-001/ACT-002/ANM-003/AVH-004/AIF-005.
CEO_DEMO_PRODUCTS = [
    {
        "product_code": "PROD-001",
        "name": "Asterion PulseSense",
        "regulatory_class": "Class II",
        "category": "Remote monitoring",
        "sub_category": "Cybersecurity",
        "description": "Connected pulse oximeter for remote patient monitoring, with a networked companion app.",
    },
    {
        "product_code": "PROD-002",
        "name": "Asterion CardioTrack",
        "regulatory_class": "Class II",
        "category": "Cardiac monitoring",
        "sub_category": "Software updates",
        "description": "Ambulatory cardiac monitor whose arrhythmia detection ships as field-updatable software.",
    },
    {
        "product_code": "PROD-003",
        "name": "Asterion NeoMonitor",
        "regulatory_class": "Class II",
        "category": "Neonatal monitoring",
        "sub_category": "Safety",
        "description": "Neonatal ICU monitoring system with alarm-safety-critical thresholds.",
    },
    {
        "product_code": "PROD-004",
        "name": "Asterion VitalHub",
        "regulatory_class": "Class II",
        "category": "Connected device gateway",
        "sub_category": "Interoperability",
        "description": "Ward gateway aggregating bedside device telemetry into the hospital network.",
    },
    {
        "product_code": "PROD-005",
        "name": "Asterion InfuFlow",
        "regulatory_class": "Class III",
        "category": "Infusion control",
        "sub_category": "Software integrity",
        "description": "Smart infusion pump whose dose-error-reduction software is safety critical.",
    },
]

CEO_DEMO_PROCESSES = [
    ("Product Design", "Engineering"),
    ("Manufacturing", "Operations"),
    ("Quality Assurance", "Quality"),
    ("Labeling", "Regulatory Affairs"),
    ("Packaging", "Operations"),
    ("Regulatory Submission", "Regulatory Affairs"),
    ("Post-Market Surveillance", "Quality"),
    ("Clinical Evaluation", "Clinical"),
    ("Risk Management", "Risk"),
    ("Software Change Control", "Software Quality"),
    ("CAPA", "Quality"),
]

# Each control hangs off the process that actually performs it. The two software controls
# split: validation belongs to Software Change Control (it gates a release), while the
# vulnerability assessment belongs to Risk Management (it feeds the risk file).
CEO_DEMO_CONTROLS = [
    {
        "name": "Design Control",
        "process": "Product Design",
        "category": ControlCategory.QUALITY,
        "owner": "Quality Manager",
        "description": "Controls the design process so design inputs, outputs and transfers stay traceable.",
    },
    {
        "name": "Supplier Quality Agreement",
        "process": "Manufacturing",
        "category": ControlCategory.MANUFACTURING,
        "owner": "Procurement Lead",
        "description": "Agreements holding suppliers to incoming material and component quality requirements.",
    },
    {
        "name": "Labeling Review Process",
        "process": "Labeling",
        "category": ControlCategory.LABELING,
        "owner": "Regulatory Affairs Lead",
        "description": "Review and approval of product labeling and instructions for use before release.",
    },
    {
        "name": "Software Validation Protocol",
        "process": "Software Change Control",
        "category": ControlCategory.QUALITY,
        "owner": "Software Engineering Lead",
        "description": "Validation evidence required before any device software change is released.",
    },
    {
        "name": "Cybersecurity Vulnerability Assessment",
        "process": "Risk Management",
        "category": ControlCategory.CYBERSECURITY,
        "owner": "Software Engineering Lead",
        "description": "Assessment of known vulnerabilities in connected devices, feeding the risk management file.",
    },
    {
        "name": "Post-Market Surveillance Review",
        "process": "Post-Market Surveillance",
        "category": ControlCategory.SAFETY,
        "owner": "Quality Manager",
        "description": "Periodic review of field complaints, incidents and trends for marketed devices.",
    },
    {
        "name": "Risk Management File Review",
        "process": "Risk Management",
        "category": ControlCategory.RISK,
        "owner": "Risk Management Lead",
        "description": "Review keeping the risk management file current against the device's residual risks.",
    },
    {
        "name": "CAPA Effectiveness Review",
        "process": "CAPA",
        "category": ControlCategory.QUALITY,
        "owner": "Quality Manager",
        "description": "Verification that corrective and preventive actions achieved their intended effect.",
    },
]


# (dataset registration id, product name, market name, expiry). Deliberately uneven
# coverage -- a portfolio registered everywhere makes impact analysis look trivial. The
# authority is not listed: it is the market's own regulatory_jurisdiction above, which for
# this tenant already *is* the synthetic authority short_name (FMDA/EMDA/UKDSA/IMDA/CDA).
CEO_DEMO_REGISTRATIONS = [
    ("REG-001", "Asterion PulseSense", "United States", (2028, 3, 31)),
    ("REG-002", "Asterion PulseSense", "European Union", (2028, 6, 30)),
    ("REG-003", "Asterion CardioTrack", "United States", (2028, 2, 28)),
    ("REG-004", "Asterion CardioTrack", "European Union", (2028, 5, 31)),
    ("REG-005", "Asterion NeoMonitor", "United States", (2027, 12, 31)),
    ("REG-006", "Asterion NeoMonitor", "European Union", (2028, 1, 31)),
    ("REG-007", "Asterion VitalHub", "United States", (2028, 4, 30)),
    ("REG-008", "Asterion VitalHub", "United Kingdom", (2028, 7, 31)),
    ("REG-009", "Asterion InfuFlow", "United States", (2029, 1, 31)),
    ("REG-010", "Asterion InfuFlow", "European Union", (2029, 2, 28)),
    ("REG-011", "Asterion InfuFlow", "India", (2028, 11, 30)),
    ("REG-012", "Asterion PulseSense", "Canada", (2028, 9, 30)),
]

# Before the notice's 05 Oct 2026 publication date, so every registration is already in
# force when the demo narrative's regulatory change lands.
CEO_DEMO_REGISTRATION_VALID_FROM = datetime(2024, 1, 1, tzinfo=timezone.utc)


CEO_DEMO_NOTICE_TITLE = (
    "Cybersecurity, Post-Market Surveillance and Software Traceability Requirements for "
    "Connected Medical Devices"
)

# The ten clauses verbatim from the demo dataset, quoted rather than paraphrased: the
# matching engine and the AI enrichment step both read this text, so demo results only
# mean anything if the words are the dataset's own.
CEO_DEMO_NOTICE_CLAUSES = [
    ("REQ-001", "Quarterly Post-Market Surveillance Review",
     "Manufacturers shall perform and document a post-market surveillance review for "
     "each covered connected device at least once every calendar quarter."),
    ("REQ-002", "Cybersecurity Vulnerability Assessment",
     "A documented cybersecurity vulnerability assessment shall be completed within 10 "
     "business days after identification of a material vulnerability affecting a covered "
     "product."),
    ("REQ-003", "Software Update Evidence Retention",
     "Manufacturers shall retain records demonstrating the testing, approval, release and "
     "deployment status of safety-relevant software updates."),
    ("REQ-004", "Risk Management File Review",
     "The risk-management file shall be reviewed after a safety-relevant software change, "
     "material cybersecurity finding, or significant post-market signal."),
    ("REQ-005", "Labeling and User Instruction Consistency",
     "Product labeling, electronic labeling and user instructions shall remain consistent "
     "with the current approved product configuration and identified safety controls."),
    ("REQ-006", "Safety Incident Escalation",
     "A confirmed reportable safety incident shall be escalated to the responsible "
     "regulatory and safety functions within two business days of confirmation."),
    ("REQ-007", "Regulatory Record Retention",
     "Records supporting compliance with the requirements of this notice shall be retained "
     "for at least seven years after creation or the applicable longer period required by "
     "the product’s market."),
    ("REQ-008", "End-to-End Traceability",
     "For each safety-relevant software change, the manufacturer shall maintain "
     "traceability between the product version, software change record, risk assessment, "
     "validation evidence and any resulting CAPA."),
    ("REQ-009", "Vulnerability Remediation Verification",
     "Material cybersecurity vulnerabilities shall have documented remediation or "
     "risk-acceptance decisions, including verification evidence and responsible-owner "
     "approval."),
    ("REQ-010", "Periodic Control Effectiveness Review",
     "Controls used to manage cybersecurity, software validation and post-market "
     "surveillance shall be reviewed periodically for effectiveness and documented "
     "deficiencies shall be assigned for remediation."),
]


# The three changes the notice introduces, grouped by subject rather than one per clause:
# a change is the unit a reviewer assesses, and the ten clauses genuinely cluster into
# three themes. Keyed on (document_id, summary).
#
# No confidence, prompt_version or ai_model on any row here, deliberately and by
# omission rather than by writing a placeholder: these rows are hand-authored seed data,
# and a non-NULL ai_model would claim an AI extraction that never ran.
CEO_DEMO_CHANGES = [
    {
        "key": "CHG-001",
        "section": "REQ-002, REQ-003, REQ-008, REQ-009 — Cybersecurity and Software Traceability",
        "change_type": ChangeType.NEW_REQUIREMENT,
        "summary": "Enhanced Cybersecurity and Software Traceability Requirements",
        "new_text": (
            "A documented cybersecurity vulnerability assessment must be completed within "
            "10 business days of identifying a material vulnerability (REQ-002); records "
            "of testing, approval, release and deployment of safety-relevant software "
            "updates must be retained (REQ-003); each safety-relevant software change must "
            "be traceable across product version, change record, risk assessment, "
            "validation evidence and any resulting CAPA (REQ-008); and material "
            "vulnerabilities must carry documented remediation or risk-acceptance "
            "decisions with verification evidence and owner approval (REQ-009)."
        ),
        "source_reference": "FMDA-2026-041-SYN REQ-002, REQ-003, REQ-008, REQ-009",
    },
    {
        "key": "CHG-002",
        "section": "REQ-001, REQ-006 — Post-Market Surveillance and Safety Escalation",
        "change_type": ChangeType.NEW_REQUIREMENT,
        "summary": "Expanded Post-Market Surveillance and Safety Escalation",
        "new_text": (
            "A post-market surveillance review must be performed and documented for each "
            "covered connected device at least once every calendar quarter (REQ-001), and "
            "a confirmed reportable safety incident must be escalated to the responsible "
            "regulatory and safety functions within two business days of confirmation "
            "(REQ-006)."
        ),
        "source_reference": "FMDA-2026-041-SYN REQ-001, REQ-006",
    },
    {
        "key": "CHG-003",
        "section": "REQ-005, REQ-007, REQ-010 — Quality Records and Labeling",
        "change_type": ChangeType.NEW_REQUIREMENT,
        "summary": "Strengthened Quality Record and Labeling Controls",
        "new_text": (
            "Product labeling, electronic labeling and user instructions must stay "
            "consistent with the approved product configuration and identified safety "
            "controls (REQ-005); supporting records must be retained for at least seven "
            "years (REQ-007); and the controls managing cybersecurity, software validation "
            "and post-market surveillance must be reviewed periodically for effectiveness "
            "with deficiencies assigned for remediation (REQ-010)."
        ),
        "source_reference": "FMDA-2026-041-SYN REQ-005, REQ-007, REQ-010",
    },
]

# effective_date splits on what the notice itself allows. An obligation that is triggered
# by an event -- a vulnerability found, an incident confirmed, a release cut, a record
# created -- has to be met from the effective date itself, 01 Jan 2027, because the
# trigger can happen that day. An obligation that is a programme to stand up or a cycle to
# run -- the quarterly review, the traceability matrix, the labeling reconciliation, the
# periodic effectiveness review -- is given the 30 Jun 2027 transition deadline, the date
# the notice sets for full demonstrated compliance.
CEO_DEMO_OBLIGATION_IMMEDIATE = datetime(2027, 1, 1, tzinfo=timezone.utc)
CEO_DEMO_OBLIGATION_TRANSITION = datetime(2027, 6, 30, tzinfo=timezone.utc)

# (key, change key, text, category, applicability, source_section, effective_date).
# Keyed on (change_id, text).
CEO_DEMO_OBLIGATIONS = [
    (
        "OBL-001", "CHG-002",
        "Perform quarterly post-market surveillance review",
        ObligationCategory.POST_MARKET,
        "All covered connected and software-enabled devices on the market.",
        "REQ-001", CEO_DEMO_OBLIGATION_TRANSITION,
    ),
    (
        "OBL-002", "CHG-001",
        "Complete material cybersecurity vulnerability assessment within 10 business days",
        ObligationCategory.CYBERSECURITY,
        "Connected and networked devices, including companion apps and ward gateways.",
        "REQ-002", CEO_DEMO_OBLIGATION_IMMEDIATE,
    ),
    (
        "OBL-003", "CHG-001",
        "Retain software update release and validation evidence",
        ObligationCategory.RECORDKEEPING,
        "Devices with field-updatable or safety-relevant software.",
        "REQ-003", CEO_DEMO_OBLIGATION_IMMEDIATE,
    ),
    (
        "OBL-004", "CHG-001",
        "Review risk-management file after qualifying software or safety event",
        ObligationCategory.SAFETY,
        "All covered devices, on a safety-relevant software change, material "
        "cybersecurity finding or significant post-market signal.",
        "REQ-004", CEO_DEMO_OBLIGATION_IMMEDIATE,
    ),
    (
        "OBL-005", "CHG-003",
        "Maintain labeling and electronic instructions consistency",
        ObligationCategory.LABELING,
        "All marketed devices, including electronic labeling and instructions for use.",
        "REQ-005", CEO_DEMO_OBLIGATION_TRANSITION,
    ),
    (
        "OBL-006", "CHG-002",
        "Escalate confirmed reportable safety incidents within two business days",
        ObligationCategory.REPORTING,
        "All covered devices once an incident is confirmed reportable.",
        "REQ-006", CEO_DEMO_OBLIGATION_IMMEDIATE,
    ),
    (
        "OBL-007", "CHG-003",
        "Retain supporting records for at least seven years",
        ObligationCategory.RECORDKEEPING,
        "All records supporting compliance with this notice, across every covered device.",
        "REQ-007", CEO_DEMO_OBLIGATION_IMMEDIATE,
    ),
    (
        "OBL-008", "CHG-001",
        "Maintain product-version-to-CAPA traceability",
        ObligationCategory.QUALITY,
        "Software-enabled and connected products with safety-relevant software changes.",
        "REQ-008", CEO_DEMO_OBLIGATION_TRANSITION,
    ),
    (
        "OBL-009", "CHG-001",
        "Document vulnerability remediation or risk acceptance",
        ObligationCategory.CYBERSECURITY,
        "Connected devices with a material cybersecurity vulnerability identified.",
        "REQ-009", CEO_DEMO_OBLIGATION_IMMEDIATE,
    ),
    (
        "OBL-010", "CHG-003",
        "Review cybersecurity, validation and PMS control effectiveness",
        ObligationCategory.QUALITY,
        "The quality system controls covering all connected and software-enabled devices.",
        "REQ-010", CEO_DEMO_OBLIGATION_TRANSITION,
    ),
]


def _ceo_demo_notice_body() -> bytes:
    """
    The uploaded file's actual bytes. text/plain, because that is what
    app/processing/extraction.py can extract -- an .md upload would come back as an
    unsupported MIME type and the document would be marked FAILED.

    The banner is the first line so the synthetic origin is unmissable in any excerpt,
    preview or search hit, not only to someone who reads to the end. The transition
    deadline is stated in the body because RegulatoryDocument has publication_date and
    effective_date but no transition_date column.
    """
    lines = [
        "PARIVART DEMO DATA — SYNTHETIC / NON-PRODUCTION. Notice ID: FMDA-2026-041-SYN. "
        "This is not a real regulation.",
        "",
        "Issuing Authority: Federal Medical Device Authority (FMDA) — synthetic",
        f"Title: {CEO_DEMO_NOTICE_TITLE}",
        "Publication Date: 05 October 2026",
        "Effective Date: 01 January 2027",
        "Transition Deadline: 30 June 2027",
        "Jurisdiction: United States (synthetic)",
        "Applies To: Manufacturers of connected medical devices and software-enabled "
        "medical devices",
        "",
        "EXECUTIVE SUMMARY",
        "",
        "This synthetic notice introduces enhanced requirements for cybersecurity "
        "vulnerability assessment, post-market surveillance, software-update traceability, "
        "risk-management review, labeling consistency, safety-event escalation, record "
        "retention, and linkage between product versions and quality records. "
        "Manufacturers must establish documented procedures, maintain evidence, and ensure "
        "that relevant software-enabled products and post-market processes can demonstrate "
        "traceability. All requirements below take effect on 01 January 2027, with a "
        "transition deadline of 30 June 2027 for full demonstrated compliance.",
        "",
        "REGULATORY REQUIREMENTS / CLAUSES",
        "",
    ]
    for req_id, heading, text in CEO_DEMO_NOTICE_CLAUSES:
        lines += [f"{req_id} — {heading}", text, ""]
    lines += [
        "APPLICABILITY NOTES",
        "",
        "REQ-002 applies when a vulnerability is material or has a plausible safety "
        "impact; routine low-risk informational findings are outside the synthetic "
        "scenario.",
        "REQ-004 applies after safety-relevant software changes, material cybersecurity "
        "findings, or significant post-market signals.",
        "REQ-006 applies only after an incident has been confirmed as reportable under the "
        "synthetic notice.",
        "REQ-008 is particularly relevant to software-enabled and connected products.",
        "",
        "END OF SYNTHETIC NOTICE — PARIVART DEMO DATA, NOT A REAL REGULATION.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


async def _exists(db: AsyncSession, model, *conditions) -> bool:
    result = await db.execute(select(model.id).where(*conditions).limit(1))
    return result.scalars().first() is not None


async def seed_ceo_demo(db: AsyncSession) -> dict:
    """
    Seed the CEO demo organization and its four users.

    Returns a summary of what was created versus what was already there, so a caller can
    report it honestly. Every "created" value is 0 on a second run.
    """
    counters = (
        "assessments",
        "organizations",
        "users",
        "authorities",
        "sources",
        "markets",
        "products",
        "processes",
        "controls",
        "registrations",
        "documents",
        "changes",
        "obligations",
    )
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

    # Markets, processes and controls are org-scoped with no unique column, so each batch
    # is gated on the org having none yet -- the same all-or-nothing-per-batch rule
    # demo_data.py uses, which keeps a renamed demo row from being silently re-created.
    if await _exists(db, Market, Market.organization_id == org_id):
        existing["markets"] += len(CEO_DEMO_MARKETS)
    else:
        for market_data in CEO_DEMO_MARKETS:
            db.add(
                Market(
                    id=str(uuid.uuid4()),
                    organization_id=org_id,
                    status=MarketStatus.ACTIVE,
                    **market_data,
                )
            )
            created["markets"] += 1

    # product_code is unique globally, so products can be keyed individually.
    for product_data in CEO_DEMO_PRODUCTS:
        if await _exists(db, Product, Product.product_code == product_data["product_code"]):
            existing["products"] += 1
            continue
        db.add(
            Product(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                status=ProductStatus.ACTIVE,
                keywords=f"{product_data['name']}, {product_data['category']}, {product_data['sub_category']}",
                **product_data,
            )
        )
        created["products"] += 1

    if await _exists(db, Process, Process.organization_id == org_id):
        existing["processes"] += len(CEO_DEMO_PROCESSES)
    else:
        for name, category in CEO_DEMO_PROCESSES:
            db.add(
                Process(
                    id=str(uuid.uuid4()),
                    organization_id=org_id,
                    name=name,
                    description=f"Process for {name} in the medical device lifecycle.",
                    category=category,
                )
            )
            created["processes"] += 1
    # Flushed before the controls: they carry process_id as a foreign key.
    await db.flush()

    if await _exists(db, Control, Control.organization_id == org_id):
        existing["controls"] += len(CEO_DEMO_CONTROLS)
    else:
        # Re-queried by name for the same reason as the authorities above: on a run where
        # the processes already existed, no in-memory object holds their ids.
        process_ids = dict(
            (
                await db.execute(
                    select(Process.name, Process.id).where(
                        Process.organization_id == org_id
                    )
                )
            ).all()
        )
        for control_data in CEO_DEMO_CONTROLS:
            fields = {k: v for k, v in control_data.items() if k != "process"}
            db.add(
                Control(
                    id=str(uuid.uuid4()),
                    organization_id=org_id,
                    product_id=None,
                    process_id=process_ids[control_data["process"]],
                    status=ControlStatus.ACTIVE,
                    **fields,
                )
            )
            created["controls"] += 1

    # Flushed before the registrations: they carry product_id and market_id.
    await db.flush()

    # Re-queried by natural key for the same reason as the authorities above: on a run
    # where the products and markets already existed, no in-memory object holds their ids.
    product_ids = dict(
        (
            await db.execute(
                select(Product.name, Product.id).where(Product.organization_id == org_id)
            )
        ).all()
    )
    market_rows = (
        await db.execute(
            select(Market.name, Market.id, Market.regulatory_jurisdiction).where(
                Market.organization_id == org_id
            )
        )
    ).all()
    markets_by_name = {name: (mid, jur) for name, mid, jur in market_rows}

    for reg_id, product_name, market_name, expiry in CEO_DEMO_REGISTRATIONS:
        product_id = product_ids.get(product_name)
        market = markets_by_name.get(market_name)
        if product_id is None or market is None:
            continue
        market_id, jurisdiction = market
        # Keyed on (product_id, market_id) like demo_data.py: one registration per
        # product per market, so a rerun re-finds it instead of inserting a twin.
        if await _exists(
            db, Registration,
            Registration.product_id == product_id,
            Registration.market_id == market_id,
        ):
            existing["registrations"] += 1
            continue
        db.add(
            Registration(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                product_id=product_id,
                market_id=market_id,
                authority_id=authority_ids.get(jurisdiction),
                registration_number=f"{jurisdiction}-{reg_id}",
                status=RegistrationStatus.ACTIVE,
                valid_from=CEO_DEMO_REGISTRATION_VALID_FROM,
                valid_until=datetime(*expiry, tzinfo=timezone.utc),
            )
        )
        created["registrations"] += 1

    await db.flush()
    await db.commit()

    document_id = await _seed_ceo_demo_notice(db, org_id, authority_ids["FMDA"], created, existing)

    change_ids: dict[str, str] = {}
    if document_id is not None:
        change_ids = await _seed_ceo_demo_intelligence(
            db, org_id, document_id, created, existing
        )
        await _seed_ceo_demo_assessments(db, org_id, change_ids, created, existing)

    print(f"CEO demo seed: created={created} existing={existing} (org {org_id})")
    return {
        "organization_id": org_id,
        "notice_document_id": document_id,
        "created": created,
        "existing": existing,
    }


async def _seed_ceo_demo_notice(
    db: AsyncSession, org_id: str, authority_id: str, created: dict, existing: dict
) -> str | None:
    """
    Upload the synthetic FMDA notice through the real document service and process it
    through the real processing pipeline, rather than inserting the rows by hand -- the
    demo is only meaningful if the document arrived the way a real upload does, with the
    same sha256, storage key, audit event and version record.

    Idempotency is the service's own per-tenant sha256 dedup: a rerun hashes identical
    bytes, upload_and_create_document returns (existing_document, True), and nothing is
    inserted. process_document is then skipped, because it is not itself idempotent -- it
    would supersede the current version and add a second one for unchanged content.
    """
    source_id = (
        await db.execute(
            select(RegulatorySource.id).where(
                RegulatorySource.authority_id == authority_id,
                RegulatorySource.name == "Synthetic Regulatory Uploads",
            )
        )
    ).scalars().first()
    if source_id is None:
        return None

    document, is_duplicate = await upload_and_create_document(
        db,
        organization_id=org_id,
        authority_id=authority_id,
        source_id=source_id,
        file_data=io.BytesIO(_ceo_demo_notice_body()),
        file_name="FMDA-2026-041-SYN.txt",
        content_type="text/plain",
        title=CEO_DEMO_NOTICE_TITLE,
        description=(
            "Synthetic demo notice (FMDA-2026-041-SYN). Not a real regulation. Introduces "
            "cybersecurity, post-market surveillance and software traceability "
            "requirements REQ-001 through REQ-010."
        ),
        document_type=DocumentType.NOTICE.value,
        jurisdiction="United States",
        country="USA",
    )
    if is_duplicate:
        existing["documents"] += 1
        return document.id

    created["documents"] += 1
    # Set by hand because upload_and_create_document takes no date arguments: it describes
    # the upload, not the notice. Written before process_document, which copies
    # publication_date onto the version's published_at.
    document.publication_date = datetime(2026, 10, 5, tzinfo=timezone.utc)
    document.effective_date = datetime(2027, 1, 1, tzinfo=timezone.utc)
    await db.commit()

    await process_document(document.id, db)
    return document.id


async def _seed_ceo_demo_intelligence(
    db: AsyncSession, org_id: str, document_id: str, created: dict, existing: dict
) -> dict[str, str]:
    """
    The three regulatory changes and ten obligations the notice introduces, written as
    plain ORM rows.

    These are *not* AI output. AI enrichment never ran for this document -- the provider
    registry is only wired at FastAPI startup, so `AIService()` has no providers in a
    seed script -- so `ai_model`, `prompt_version` and `confidence` are left unset rather
    than filled with a plausible-looking model name. A seeded row that claims an
    extraction that never happened would make every provenance field in the demo
    worthless.

    The audit events are written in this same unit of work, only on the insert path: a
    rerun that creates nothing must also claim nothing, or the trail would record one
    creation per seed run.
    """
    version_id = (
        await db.execute(
            select(RegulatoryVersion.id).where(
                RegulatoryVersion.document_id == document_id,
                RegulatoryVersion.is_current.is_(True),
            )
        )
    ).scalars().first()

    # The analyst, because in the real product this is who works a parsed notice into
    # changes and obligations.
    actor_id = (
        await db.execute(
            select(User.id).where(
                User.email == "regulatory.analyst@asterion-parivart.example"
            )
        )
    ).scalars().first()

    change_ids: dict[str, str] = {}
    for change_data in CEO_DEMO_CHANGES:
        key = change_data["key"]
        fields = {k: v for k, v in change_data.items() if k != "key"}
        existing_id = (
            await db.execute(
                select(RegulatoryChange.id).where(
                    RegulatoryChange.document_id == document_id,
                    RegulatoryChange.summary == fields["summary"],
                )
            )
        ).scalars().first()
        if existing_id is not None:
            change_ids[key] = existing_id
            existing["changes"] += 1
            continue

        change_id = str(uuid.uuid4())
        db.add(
            RegulatoryChange(
                id=change_id,
                document_id=document_id,
                version_id=version_id,
                **fields,
            )
        )
        change_ids[key] = change_id
        created["changes"] += 1
        AuditService.record(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            event_type=EVENT_REGULATORY_CHANGE_CREATED,
            entity_type=ENTITY_REGULATORY_CHANGE,
            entity_id=change_id,
            payload={
                "change_id": change_id,
                "document_id": document_id,
                "summary": fields["summary"],
                "change_type": fields["change_type"].value,
                "source_reference": fields["source_reference"],
                "source": "ceo_demo_seed",
            },
        )

    # Flushed so the obligations' change_id foreign keys point at rows the database has.
    await db.flush()

    for (
        key, change_key, text, category, applicability, source_section, effective_date
    ) in CEO_DEMO_OBLIGATIONS:
        change_id = change_ids[change_key]
        if await _exists(
            db, RegulatoryObligation,
            RegulatoryObligation.change_id == change_id,
            RegulatoryObligation.text == text,
        ):
            existing["obligations"] += 1
            continue

        obligation_id = str(uuid.uuid4())
        db.add(
            RegulatoryObligation(
                id=obligation_id,
                change_id=change_id,
                document_id=document_id,
                text=text,
                category=category,
                applicability=applicability,
                # The notice is a United States (synthetic) instrument; every obligation
                # in it is US-scoped, so none is left without a jurisdiction.
                jurisdiction="United States",
                effective_date=effective_date,
                source_section=source_section,
            )
        )
        created["obligations"] += 1
        AuditService.record(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            event_type=EVENT_OBLIGATION_CREATED,
            entity_type=ENTITY_REGULATORY_OBLIGATION,
            entity_id=obligation_id,
            payload={
                "obligation_id": obligation_id,
                "change_id": change_id,
                "document_id": document_id,
                "text": text,
                "category": category.value,
                "source_section": source_section,
                "seed_key": key,
                "source": "ceo_demo_seed",
            },
        )

    await db.commit()
    return change_ids


async def _seed_ceo_demo_assessments(
    db: AsyncSession, org_id: str, change_ids: dict[str, str], created: dict, existing: dict
) -> dict[str, str]:
    """
    One Impact Assessment per regulatory change, produced by the real matching engine.

    Nothing is asserted about the result. The engine computes overall_impact_level and
    overall_confidence from the evidence it actually found; the demo dataset's advisory
    confidence figures are not written anywhere, because a seeded number would be a claim
    about an analysis that did not produce it.

    Idempotency is checked here rather than left to the engine. `analyze_change_impact`
    is itself idempotent without force_reanalyze, but it only knows that *after* loading
    the portfolio and the obligations; skipping the call outright on a rerun is cheaper and
    makes the created/existing counters honest without inferring them from the returned row.
    """
    actor_id = (
        await db.execute(
            select(User.id).where(
                User.email == "regulatory.analyst@asterion-parivart.example"
            )
        )
    ).scalars().first()

    assessment_ids: dict[str, str] = {}
    for key in ("CHG-001", "CHG-002", "CHG-003"):
        change_id = change_ids.get(key)
        if change_id is None:
            continue
        existing_id = (
            await db.execute(
                select(ImpactAssessment.id).where(
                    ImpactAssessment.organization_id == org_id,
                    ImpactAssessment.regulatory_change_id == change_id,
                )
            )
        ).scalars().first()
        if existing_id is not None:
            assessment_ids[key] = existing_id
            existing["assessments"] += 1
            continue

        assessment = await MatchingEngineService.analyze_change_impact(
            db,
            organization_id=org_id,
            regulatory_change_id=change_id,
            actor_id=actor_id,
        )
        assessment_ids[key] = assessment.id
        created["assessments"] += 1

    return assessment_ids
