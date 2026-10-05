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
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import hash_password
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
        "organizations",
        "users",
        "authorities",
        "sources",
        "markets",
        "products",
        "processes",
        "controls",
        "registrations",
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
    print(f"CEO demo seed: created={created} existing={existing} (org {org_id})")
    return {"organization_id": org_id, "created": created, "existing": existing}
