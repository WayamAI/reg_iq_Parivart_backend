"""
Seed coverage for registrations, and the idempotency the seed claims.

The registration matching rule scores against the publishing authority and the resolved
market, so an empty registrations table quietly disables a whole matching axis. These
tests keep the demo portfolio complete enough for that rule to fire.
"""

import pytest
from sqlalchemy import func, select

from app.db.database import AsyncSessionLocal
from app.models.portfolio import Market, Product, Registration, RegistrationStatus
from app.seeds.demo_data import seed_demo_data


@pytest.mark.asyncio
async def test_seed_creates_registrations_for_every_product(demo_org):
    async with AsyncSessionLocal() as session:
        registrations = (
            await session.execute(
                select(Registration).where(
                    Registration.organization_id == demo_org.id
                )
            )
        ).scalars().all()

        assert registrations, "the demo portfolio must carry registrations"

        products = {
            p.id: p.name
            for p in (
                await session.execute(
                    select(Product).where(Product.organization_id == demo_org.id)
                )
            ).scalars().all()
        }
        registered = {products[r.product_id] for r in registrations}
        assert registered == set(products.values()), (
            "every demo product should be registered in at least one market"
        )


@pytest.mark.asyncio
async def test_registrations_resolve_to_a_market_and_authority(demo_org):
    async with AsyncSessionLocal() as session:
        registrations = (
            await session.execute(
                select(Registration).where(
                    Registration.organization_id == demo_org.id
                )
            )
        ).scalars().all()

        market_ids = {
            m.id
            for m in (
                await session.execute(
                    select(Market).where(Market.organization_id == demo_org.id)
                )
            ).scalars().all()
        }

        for registration in registrations:
            assert registration.market_id in market_ids
            # The authority link is what REGISTRATION_MATCH scores against when a
            # document is published by the same regulator.
            assert registration.authority_id is not None
            assert registration.status == RegistrationStatus.ACTIVE
            assert registration.registration_number


@pytest.mark.asyncio
async def test_seeding_twice_does_not_duplicate_registrations(demo_org):
    """The seed documents itself as idempotent per entity. Hold it to that."""
    async with AsyncSessionLocal() as session:
        before = (
            await session.execute(
                select(func.count()).select_from(Registration)
            )
        ).scalar_one()

    async with AsyncSessionLocal() as session:
        await seed_demo_data(session)

    async with AsyncSessionLocal() as session:
        after = (
            await session.execute(
                select(func.count()).select_from(Registration)
            )
        ).scalar_one()

    assert before == after
