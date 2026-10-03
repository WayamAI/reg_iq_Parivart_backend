"""
Role enforcement across all five portfolio CRUD routers (products, markets, processes,
controls, registrations): create requires
ADMIN/REGULATORY_MANAGER/COMPLIANCE_MANAGER; read stays open to every role.

One parametrized file rather than five near-identical ones, since the routers share an
identical CRUD/role shape -- a change to the matrix shows up here as one adjustment,
not five.
"""

import uuid

import pytest

from app.tests.conftest import role_headers

PORTFOLIO_ENTITIES = [
    (
        "products",
        lambda: {
            "name": "Authz Product",
            "product_code": f"AP-{uuid.uuid4().hex[:8]}",
        },
    ),
    (
        "markets",
        lambda: {
            "name": "Authz Market",
            "country": "Testland",
        },
    ),
    (
        "processes",
        lambda: {
            "name": "Authz Process",
        },
    ),
    (
        "controls",
        lambda: {
            "name": "Authz Control",
        },
    ),
]


@pytest.mark.parametrize("entity,payload_fn", PORTFOLIO_ENTITIES)
@pytest.mark.parametrize("role", ["REVIEWER", "ANALYST", "VIEWER"])
async def test_denied_roles_cannot_create_portfolio_entity(client, entity, payload_fn, role):
    headers = await role_headers(client, role)
    response = await client.post(
        f"/api/v1/portfolio/{entity}/", json=payload_fn(), headers=headers
    )
    assert response.status_code == 403, (entity, role, response.text)


@pytest.mark.parametrize("entity,payload_fn", PORTFOLIO_ENTITIES)
@pytest.mark.parametrize("role", ["REGULATORY_MANAGER", "COMPLIANCE_MANAGER"])
async def test_allowed_roles_can_create_portfolio_entity(client, entity, payload_fn, role):
    headers = await role_headers(client, role)
    response = await client.post(
        f"/api/v1/portfolio/{entity}/", json=payload_fn(), headers=headers
    )
    assert response.status_code == 201, (entity, role, response.text)


@pytest.mark.parametrize("entity,_", PORTFOLIO_ENTITIES)
async def test_admin_fixture_is_unaffected(client, auth_headers, entity, _):
    """Regression guard: the existing, most-used auth_headers fixture (ADMIN) must not
    be broken by role enforcement on any of these five routers."""
    response = await client.get(f"/api/v1/portfolio/{entity}/", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.parametrize("entity,_", PORTFOLIO_ENTITIES)
@pytest.mark.parametrize("role", ["ADMIN", "REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER", "ANALYST", "VIEWER"])
async def test_every_role_can_list_portfolio_entity(client, entity, _, role):
    headers = await role_headers(client, role)
    response = await client.get(f"/api/v1/portfolio/{entity}/", headers=headers)
    assert response.status_code == 200


async def test_denied_role_cannot_create_registration(client, auth_headers):
    """Registration also needs a product_id/market_id -- tested separately since its
    payload shape differs from the other four entities."""
    product = await client.post(
        "/api/v1/portfolio/products/",
        json={"name": "Reg Test Product", "product_code": f"RTP-{uuid.uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    market = await client.post(
        "/api/v1/portfolio/markets/",
        json={"name": "Reg Test Market", "country": "Testland"},
        headers=auth_headers,
    )
    assert product.status_code == 201 and market.status_code == 201

    viewer = await role_headers(client, "VIEWER")
    response = await client.post(
        "/api/v1/portfolio/registrations/",
        json={
            "product_id": product.json()["id"],
            "market_id": market.json()["id"],
            "registration_number": "REG-TEST-001",
        },
        headers=viewer,
    )
    assert response.status_code == 403
