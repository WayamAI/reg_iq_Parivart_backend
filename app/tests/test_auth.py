import pytest

@pytest.mark.asyncio
async def test_register_and_login(client):
    # Test registration
    response = await client.post("/api/v1/auth/register", json={
        "user_in": {
            "name": "Test User",
            "email": "test@example.com",
            "password": "securepassword123",
            "role": "ANALYST",
        },
        "org_in": {
            "name": "Test Org",
            "slug": "test-org",
            "industry": "Testing",
            "description": "Test organization for unit tests",
        },
    })

    print(f"Registration response status: {response.status_code}")
    print(f"Registration response body: {response.json()}")

    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["email"] == "test@example.com"
    assert data["name"] == "Test User"
    assert data["role"] == "ANALYST"

    # Test login
    response = await client.post("/api/v1/auth/login", data={
        "username": "test@example.com",
        "password": "securepassword123"
    })

    print(f"Login response status: {response.status_code}")
    print(f"Login response body: {response.json()}")

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "user" in data
    assert data["user"]["email"] == "test@example.com"

    # Test accessing protected endpoint with token
    token = data["access_token"]
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )

    print(f"Me response status: {response.status_code}")
    print(f"Me response body: {response.json()}")

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["name"] == "Test User"

@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    response = await client.post("/api/v1/auth/login", data={
        "username": "nonexistent@example.com",
        "password": "wrongpassword"
    })

    assert response.status_code == 401
    data = response.json()
    assert "detail" in data
    assert "Incorrect email or password" in data["detail"]

@pytest.mark.asyncio
async def test_duplicate_registration(client):
    # Register first user
    response = await client.post("/api/v1/auth/register", json={
        "user_in": {
            "name": "Test User 2",
            "email": "test2@example.com",
            "password": "securepassword123",
            "role": "VIEWER",
        },
        "org_in": {
            "name": "Test Org 2",
            "slug": "test-org-2",
            "industry": "Testing",
            "description": "Test organization for unit tests",
        },
    })

    assert response.status_code == 201

    # Try to register with same email
    response = await client.post("/api/v1/auth/register", json={
        "user_in": {
            "name": "Test User 3",
            "email": "test2@example.com",  # Same email
            "password": "differentpassword",
            "role": "ADMIN",
        },
        "org_in": {
            "name": "Test Org 3",
            "slug": "test-org-3",
            "industry": "Testing",
            "description": "Test organization for unit tests",
        },
    })

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Email already registered" in data["detail"]

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# --- Password hashing migrated from Passlib to the bcrypt library directly -------------

async def test_password_hashes_are_bcrypt_and_verify(client):
    """Stored format is unchanged ($2b$12$...), so existing user hashes keep working."""
    from app.core.security import hash_password, verify_password

    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$2b$12$")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


async def test_verify_password_is_total(client):
    """A malformed or foreign hash is a failed login, never an exception -> never a 500."""
    from app.core.security import verify_password

    assert not verify_password("anything", "not-a-bcrypt-hash")
    assert not verify_password("anything", "")
    assert not verify_password("", "")
    assert not verify_password("a" * 200, "$2b$12$" + "x" * 53)


async def test_overlong_password_is_rejected_not_truncated(client):
    """
    bcrypt only hashes the first 72 bytes. Truncating silently would let two different
    passwords authenticate each other, so registration rejects the input instead.
    """
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "user_in": {
                "name": "Long Password",
                "email": "longpw@example.com",
                "password": "a" * 100,
                "role": "VIEWER",
            },
            "org_in": {"name": "Long Org", "slug": "long-org"},
        },
    )
    assert res.status_code == 422, res.text


# --- Session behaviour -----------------------------------------------------------------

async def test_me_returns_the_authenticated_user(client, demo_org, auth_headers):
    res = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email"] == "admin@asterion.com"
    assert body["organization_id"] == demo_org.id
    assert body["role"] == "ADMIN"
    assert "password_hash" not in body  # never leak the hash


async def test_protected_route_requires_a_token(client, demo_org):
    for path in ("/api/v1/auth/me", "/api/v1/impact/", "/api/v1/reports/"):
        res = await client.get(path)
        assert res.status_code == 401, f"{path} -> {res.status_code}"


async def test_protected_route_rejects_a_bogus_token(client, demo_org):
    res = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert res.status_code == 401


async def test_inactive_user_cannot_log_in_or_use_an_existing_token(
    client, demo_org, auth_headers
):
    """Deactivation must take effect immediately, not when the token expires."""
    from sqlalchemy.future import select

    from app.db.database import AsyncSessionLocal
    from app.models.user import User

    # The token works while the user is active.
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 200

    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(User.email == "admin@asterion.com")
            )
        ).scalars().first()
        user.is_active = False
        await session.commit()

    # The already-issued token stops working...
    assert (await client.get("/api/v1/auth/me", headers=auth_headers)).status_code == 401
    # ...and a fresh login is refused.
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@asterion.com", "password": "admin123"},
    )
    assert login.status_code == 400
    assert login.json()["detail"] == "Inactive user"


async def test_seeded_demo_users_can_authenticate(client, demo_org):
    """The seed hashes passwords through the same code path; both demo users must work."""
    for email, password in (
        ("admin@asterion.com", "admin123"),
        ("analyst@asterion.com", "analyst123"),
    ):
        res = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": password}
        )
        assert res.status_code == 200, f"{email}: {res.text}"
        assert res.json()["user"]["email"] == email

        wrong = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": "wrong"}
        )
        assert wrong.status_code == 401
