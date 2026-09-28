import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.core.security import hash_password
from app.models.portfolio import (
    Product,
    ProductStatus,
    Market,
    MarketStatus,
    ProductMarket,
    Process,
    Control,
    ControlCategory,
    ControlStatus,
    Registration,
    RegistrationStatus,
)
from app.models.regulatory import RegulatoryAuthority, RegulatorySource, ConnectorType, SourceType, IngestionStatus

async def _exists(db: AsyncSession, model, *conditions) -> bool:
    result = await db.execute(select(model.id).where(*conditions).limit(1))
    return result.scalars().first() is not None


async def seed_demo_data(db: AsyncSession):
    """
    Seed the demo organization Asterion Medical Systems and its portfolio.

    Idempotent per entity rather than all-or-nothing. An earlier version returned early if
    the organization already existed, so a database where the organization had been created
    by hand (or where a previous seed failed part-way) could never be topped up and was
    left with an empty portfolio. Nothing here overwrites or deletes existing rows.
    """
    result = await db.execute(select(Organization).where(Organization.slug == "asterion-medical-systems"))
    org = result.scalars().first()
    if org is None:
        org = Organization(
            id=str(uuid.uuid4()),
            name="Asterion Medical Systems",
            slug="asterion-medical-systems",
            industry="Medical Devices",
            description="A leading medical device company focused on innovative monitoring and therapeutic solutions.",
        )
        db.add(org)
        await db.flush()
    org_id = org.id

    # Create demo admin user
    admin_id = str(uuid.uuid4())
    admin_user = User(
        id=admin_id,
        organization_id=org_id,
        name="Admin User",
        email="admin@asterion.com",
        password_hash=hash_password("admin123"),  # In production, use a strong password and force change
        role=UserRole.ADMIN,
        is_active=True,
    )
    if not await _exists(db, User, User.email == admin_user.email):
        db.add(admin_user)

    # Create demo regular user (analyst)
    analyst_id = str(uuid.uuid4())
    analyst_user = User(
        id=analyst_id,
        organization_id=org_id,
        name="Analyst User",
        email="analyst@asterion.com",
        password_hash=hash_password("analyst123"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    if not await _exists(db, User, User.email == analyst_user.email):
        db.add(analyst_user)
    await db.flush()

    # Create markets for the demo organization
    markets_data = [
        {"name": "United States", "country": "USA", "region": "North America", "regulatory_jurisdiction": "FDA"},
        {"name": "European Union", "country": "EU", "region": "Europe", "regulatory_jurisdiction": "EMA"},
        {"name": "United Kingdom", "country": "UK", "region": "Europe", "regulatory_jurisdiction": "MHRA"},
        {"name": "India", "country": "IN", "region": "Asia", "regulatory_jurisdiction": "CDSCO"},
        {"name": "Canada", "country": "CA", "region": "North America", "regulatory_jurisdiction": "Health Canada"},
    ]

    market_objects = []
    seed_markets = not await _exists(db, Market, Market.organization_id == org_id)
    for market_data in markets_data:
        market_id = str(uuid.uuid4())
        market = Market(
            id=market_id,
            organization_id=org_id,
            name=market_data["name"],
            country=market_data["country"],
            region=market_data["region"],
            regulatory_jurisdiction=market_data["regulatory_jurisdiction"],
            status=MarketStatus.ACTIVE,
        )
        if seed_markets:
            db.add(market)
        market_objects.append(market)

    # Create products for the demo organization
    products_data = [
        {"name": "Asterion PulseSense", "product_code": "APS-001", "description": "Wearable pulse oximeter for continuous monitoring.", "category": "Diagnostic", "sub_category": "Wearable", "regulatory_class": "Class II"},
        {"name": "Asterion CardioTrack", "product_code": "ACT-002", "description": "Implantable cardiac monitor for arrhythmia detection.", "category": "Implantable", "sub_category": "Cardiac", "regulatory_class": "Class III"},
        {"name": "Asterion NeoMonitor", "product_code": "ANM-003", "description": "Neonatal monitoring system for ICU use.", "category": "Monitoring", "sub_category": "Neonatal", "regulatory_class": "Class II"},
        {"name": "Asterion VitalHub", "product_code": "AVH-004", "description": "Central vital signs monitor for hospital wards.", "category": "Monitoring", "sub_category": "Bedside", "regulatory_class": "Class II"},
        {"name": "Asterion InfuFlow", "product_code": "AIF-005", "description": "Smart infusion pump with dose error reduction software.", "category": "Therapeutic", "sub_category": "Infusion", "regulatory_class": "Class II"},
    ]

    product_objects = []
    seed_products = not await _exists(db, Product, Product.organization_id == org_id)
    for product_data in products_data:
        product_id = str(uuid.uuid4())
        product = Product(
            id=product_id,
            organization_id=org_id,
            name=product_data["name"],
            product_code=product_data["product_code"],
            description=product_data["description"],
            category=product_data["category"],
            sub_category=product_data["sub_category"],
            status=ProductStatus.ACTIVE,
            regulatory_class=product_data["regulatory_class"],
            keywords=f"{product_data['name']}, {product_data['category']}, {product_data['sub_category']}",
        )
        if seed_products:
            db.add(product)
        product_objects.append(product)

    # Create processes for the demo organization
    processes_data = [
        "Product Design",
        "Manufacturing",
        "Quality Assurance",
        "Labeling",
        "Packaging",
        "Regulatory Submission",
        "Post-Market Surveillance",
        "Clinical Evaluation",
        "Risk Management",
    ]

    process_objects = []
    seed_processes = not await _exists(db, Process, Process.organization_id == org_id)
    for process_name in processes_data:
        process_id = str(uuid.uuid4())
        process = Process(
            id=process_id,
            organization_id=org_id,
            name=process_name,
            description=f"Process for {process_name} in medical device lifecycle.",
            category="Operational",
        )
        if seed_processes:
            db.add(process)
        process_objects.append(process)

    # Create controls for the demo organization (example: link some controls to products and processes)
    # We'll create a few example controls
    controls_data = [
        {
            "name": "Design Control Procedure",
            "description": "Procedure for controlling the design process to ensure regulatory compliance.",
            "category": ControlCategory.QUALITY,
            "owner": "Quality Manager",
        },
        {
            "name": "Supplier Quality Agreement",
            "description": "Agreements with suppliers to ensure incoming material quality.",
            "category": ControlCategory.QUALITY,
            "owner": "Procurement Lead",
        },
        {
            "name": "Labeling Review Process",
            "description": "Process to review and approve product labeling and instructions for use.",
            "category": ControlCategory.LABELING,
            "owner": "Regulatory Affairs Lead",
        },
        {
            "name": "Software Validation Protocol",
            "description": "Protocol for validating software used in medical devices.",
            "category": ControlCategory.CYBERSECURITY,
            "owner": "Software Engineering Lead",
        },
    ]

    control_objects = []
    seed_controls = not await _exists(db, Control, Control.organization_id == org_id)
    for control_data in controls_data:
        control_id = str(uuid.uuid4())
        # For simplicity, we won't link to specific products/processes in this seed, but we could.
        control = Control(
            id=control_id,
            organization_id=org_id,
            product_id=None,  # Could be set to a specific product
            process_id=None,  # Could be set to a specific process
            name=control_data["name"],
            description=control_data["description"],
            category=control_data["category"],
            owner=control_data["owner"],
            status=ControlStatus.ACTIVE,
        )
        if seed_controls:
            db.add(control)
        control_objects.append(control)

    # Create some example product-market relationships (for demonstration, link first two products to first three markets)
    # In a real system, these would be more comprehensive.
    seed_links = seed_products and seed_markets and not await _exists(
        db, ProductMarket, ProductMarket.product_id.in_([p.id for p in product_objects])
    )
    for i, product in enumerate(product_objects[:2] if seed_links else []):  # First two products
        for j, market in enumerate(market_objects[:3]):  # First three markets
            product_market_id = str(uuid.uuid4())
            product_market = ProductMarket(
                id=product_market_id,
                product_id=product.id,
                market_id=market.id,
                status=MarketStatus.ACTIVE,
                launch_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
                registration_status="Registered" if (i + j) % 2 == 0 else "Pending",
                registration_reference=f"REG-{product.product_code}-{market.country[:2]}-{1000 + i*j}",
            )
            db.add(product_market)

    # Create some example regulatory authorities (global, not tied to organization)
    # We'll create a few if they don't already exist.
    authorities_data = [
        {
            "name": "Food and Drug Administration",
            "short_name": "FDA",
            "jurisdiction": "United States",
            "country": "USA",
            "website": "https://www.fda.gov",
            "description": "The FDA is responsible for protecting the public health by ensuring the safety, efficacy, and security of human and veterinary drugs, biological products, and medical devices.",
        },
        {
            "name": "European Medicines Agency",
            "short_name": "EMA",
            "jurisdiction": "European Union",
            "country": "EU",
            "website": "https://www.ema.europa.eu",
            "description": "The EMA is responsible for the scientific evaluation, supervision and safety monitoring of medicines in the EU.",
        },
        {
            "name": "Medicines and Healthcare products Regulatory Agency",
            "short_name": "MHRA",
            "jurisdiction": "United Kingdom",
            "country": "UK",
            "website": "https://www.gov.uk/government/organisations/medicines-and-healthcare-products-regulatory-agency",
            "description": "The MHRA regulates medicines, medical devices and blood components for transfusion in the UK.",
        },
        {
            "name": "Central Drugs Standard Control Organization",
            "short_name": "CDSCO",
            "jurisdiction": "India",
            "country": "IN",
            "website": "https://cdsco.gov.in",
            "description": "CDSCO is the national regulatory body for Indian pharmaceuticals and medical devices.",
        },
        {
            "name": "Health Canada",
            "short_name": "HC",
            "jurisdiction": "Canada",
            "country": "CA",
            "website": "https://www.canada.ca/en/health-canada.html",
            "description": "Health Canada is the federal department responsible for helping Canadians maintain and improve their health.",
        },
    ]

    for auth_data in authorities_data:
        # Check if authority already exists (by short_name)
        result = await db.execute(select(RegulatoryAuthority).where(RegulatoryAuthority.short_name == auth_data["short_name"]))
        auth = result.scalars().first()
        if not auth:
            auth_id = str(uuid.uuid4())
            authority = RegulatoryAuthority(
                id=auth_id,
                name=auth_data["name"],
                short_name=auth_data["short_name"],
                jurisdiction=auth_data["jurisdiction"],
                country=auth_data["country"],
                website=auth_data["website"],
                description=auth_data["description"],
                is_active=True,
            )
            db.add(authority)

    # Create some example regulatory sources (global)
    # We'll create an example RSS source for FDA and a manual upload source.
    sources_data = [
        {
            "authority_short_name": "FDA",
            "name": "FDA Medical Device Recalls",
            "description": "RSS feed for FDA medical device recalls and safety alerts.",
            "source_type": SourceType.RSS,
            "connector_type": ConnectorType.RSS,
            "url": "https://www.fda.gov/medical-devices/medical-device-safety/medical-device-recalls",
            "enabled": True,
            "schedule": "0 */6 * * *",  # Every 6 hours
        },
        {
            "authority_short_name": "EMA",
            "name": "EMA Public Statements",
            "description": "Web source for EMA public statements on medicines.",
            "source_type": SourceType.HTML,
            "connector_type": ConnectorType.HTML,
            "url": "https://www.ema.europa.eu/en/news/public-statements",
            "enabled": True,
            "schedule": "0 0 * * *",  # Daily
        },
        {
            "authority_short_name": "FDA",
            "name": "Manual Upload Source",
            "description": "Source for manually uploaded regulatory documents (e.g., PDFs, guidance documents).",
            "source_type": SourceType.DOCUMENT,
            "connector_type": ConnectorType.DOCUMENT,
            # Manually uploaded documents have nothing to poll. The column is nullable;
            # "" is not a URL and fails HttpUrl validation on the way back out.
            "url": None,
            "enabled": True,
            "schedule": "manual",
        },
    ]

    for source_data in sources_data:
        # Find the authority by short_name
        result = await db.execute(select(RegulatoryAuthority).where(RegulatoryAuthority.short_name == source_data["authority_short_name"]))
        authority = result.scalars().first()
        if authority:
            # Check if source already exists (by name and authority_id) to avoid duplicates
            result = await db.execute(
                select(RegulatorySource).where(
                    RegulatorySource.authority_id == authority.id,
                    RegulatorySource.name == source_data["name"]
                )
            )
            existing_source = result.scalars().first()
            if not existing_source:
                source_id = str(uuid.uuid4())
                source = RegulatorySource(
                    id=source_id,
                    authority_id=authority.id,
                    name=source_data["name"],
                    description=source_data["description"],
                    jurisdiction=authority.jurisdiction,
                    country=authority.country,
                    source_type=source_data["source_type"],
                    connector_type=source_data["connector_type"],
                    url=source_data["url"],
                    enabled=source_data["enabled"],
                    schedule=source_data["schedule"],
                    last_run_at=None,
                    last_success_at=None,
                    last_error=None,
                )
                db.add(source)

    # Commit all the seeded data
    await db.commit()
    print(f"Seeded demo organization: {org.name} (ID: {org.id})")
    return org