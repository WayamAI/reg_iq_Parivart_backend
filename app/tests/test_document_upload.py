"""
Document upload: storage, primary keys and deduplication.

These are regression tests for two independent faults that made
`POST /api/v1/regulatory/documents/upload` fail outright: `LocalStorage` imported
`os` inside `__init__` so every file operation raised `NameError`, and
`create_document_record` never passed `id` so every insert sent a NULL primary key.
Both only surfaced at runtime, which is why the suite was green while upload was dead.
"""

import io
import uuid

import pytest
from sqlalchemy.future import select

from app.db.database import AsyncSessionLocal
from app.models.document import DocumentProcessingStatus, RegulatoryDocument
from app.models.regulatory import (
    ConnectorType,
    RegulatoryAuthority,
    RegulatorySource,
    SourceType,
)
from app.services.document_service import (
    check_duplicate_sha256,
    compute_sha256,
    upload_and_create_document,
)
from app.storage.base import LocalStorage


# --- LocalStorage ----------------------------------------------------------------------


async def test_local_storage_round_trip(tmp_path):
    storage = LocalStorage(base_path=str(tmp_path))

    key = await storage.upload_file(io.BytesIO(b"regulatory text"), "notice.txt", "text/plain")

    assert key.endswith(".txt")
    handle = await storage.download_file(key)
    try:
        assert handle.read() == b"regulatory text"
    finally:
        handle.close()


async def test_local_storage_delete_is_idempotent(tmp_path):
    storage = LocalStorage(base_path=str(tmp_path))
    key = await storage.upload_file(io.BytesIO(b"x"), "a.txt", "text/plain")

    assert await storage.delete_file(key) is True
    assert await storage.delete_file(key) is False


async def test_local_storage_download_missing_key_raises(tmp_path):
    storage = LocalStorage(base_path=str(tmp_path))

    with pytest.raises(FileNotFoundError):
        await storage.download_file("nope.txt")


async def test_local_storage_keys_do_not_collide_on_filename(tmp_path):
    """Two uploads of the same filename must not overwrite each other."""
    storage = LocalStorage(base_path=str(tmp_path))

    first = await storage.upload_file(io.BytesIO(b"one"), "same.pdf", "application/pdf")
    second = await storage.upload_file(io.BytesIO(b"two"), "same.pdf", "application/pdf")

    assert first != second
    for key, expected in ((first, b"one"), (second, b"two")):
        handle = await storage.download_file(key)
        try:
            assert handle.read() == expected
        finally:
            handle.close()


# --- upload_and_create_document -------------------------------------------------------


async def _source(session) -> RegulatorySource:
    authority = RegulatoryAuthority(
        id=str(uuid.uuid4()),
        name="Upload Test Authority",
        short_name=f"UTA-{uuid.uuid4().hex[:6]}",
        jurisdiction="Testland",
        country="Testland",
        is_active=True,
    )
    session.add(authority)
    await session.flush()

    source = RegulatorySource(
        id=str(uuid.uuid4()),
        authority_id=authority.id,
        name=f"Upload Test Source {uuid.uuid4().hex[:6]}",
        jurisdiction=authority.jurisdiction,
        country=authority.country,
        source_type=SourceType.DOCUMENT,
        connector_type=ConnectorType.DOCUMENT,
        enabled=True,
    )
    session.add(source)
    await session.commit()
    return source


async def test_upload_assigns_a_primary_key(demo_org, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.document_service.storage", LocalStorage(base_path=str(tmp_path))
    )
    async with AsyncSessionLocal() as session:
        source = await _source(session)

        document, is_duplicate = await upload_and_create_document(
            db=session,
            organization_id=demo_org.id,
            authority_id=source.authority_id,
            source_id=source.id,
            file_data=io.BytesIO(b"An updated labelling requirement applies."),
            file_name="notice.txt",
            content_type="text/plain",
            title="Labelling Notice",
        )

        assert is_duplicate is False
        assert document.id  # NULL primary key was the original fault
        assert uuid.UUID(document.id)
        assert document.sha256
        assert document.file_size == len(b"An updated labelling requirement applies.")
        assert document.processing_status == DocumentProcessingStatus.DISCOVERED
        assert document.retrieved_at is not None

        # It is genuinely in the database under that id, not just in the session.
        stored = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.id == document.id)
            )
        ).scalars().first()
        assert stored is not None
        assert stored.organization_id == demo_org.id


async def test_uploaded_bytes_are_retrievable(demo_org, tmp_path, monkeypatch):
    storage = LocalStorage(base_path=str(tmp_path))
    monkeypatch.setattr("app.services.document_service.storage", storage)
    payload = b"Section 4.2 requires electronic labelling."

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        document, _ = await upload_and_create_document(
            db=session,
            organization_id=demo_org.id,
            authority_id=source.authority_id,
            source_id=source.id,
            file_data=io.BytesIO(payload),
            file_name="notice.txt",
            content_type="text/plain",
            title="Labelling Notice",
        )

    handle = await storage.download_file(document.storage_key)
    try:
        assert handle.read() == payload
    finally:
        handle.close()


async def test_identical_content_is_reported_as_a_duplicate(demo_org, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.document_service.storage", LocalStorage(base_path=str(tmp_path))
    )
    payload = b"An updated labelling requirement applies."

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        first, first_duplicate = await upload_and_create_document(
            db=session,
            organization_id=demo_org.id,
            authority_id=source.authority_id,
            source_id=source.id,
            file_data=io.BytesIO(payload),
            file_name="notice.txt",
            content_type="text/plain",
            title="Labelling Notice",
        )
        second, second_duplicate = await upload_and_create_document(
            db=session,
            organization_id=demo_org.id,
            authority_id=source.authority_id,
            source_id=source.id,
            file_data=io.BytesIO(payload),
            file_name="notice-again.txt",
            content_type="text/plain",
            title="Labelling Notice (resent)",
        )

        assert first_duplicate is False
        assert second_duplicate is True
        assert second.id == first.id
        assert second.title == "Labelling Notice"  # the original row, not a new one


async def test_compute_sha256_rewinds_the_stream():
    """The caller reads the same stream afterwards to upload it and to size it."""
    data = io.BytesIO(b"regulatory text")

    digest = await compute_sha256(data)

    assert len(digest) == 64
    assert data.tell() == 0
    assert data.read() == b"regulatory text"


async def test_check_duplicate_sha256_returns_none_when_absent(demo_org):
    async with AsyncSessionLocal() as session:
        assert await check_duplicate_sha256("0" * 64, session, demo_org.id) is None


# --- tenant isolation -------------------------------------------------------------------


async def test_identical_content_from_two_organizations_creates_two_documents(
    demo_org, tmp_path, monkeypatch
):
    """
    The same file content uploaded by two different organizations must produce two
    independent document records, not a cross-tenant "duplicate" pointing at the other
    organization's row. Regression test for a global (non-tenant-scoped) sha256 lookup
    that previously handed org B the id of org A's document.
    """
    from app.models.organization import Organization

    monkeypatch.setattr(
        "app.services.document_service.storage", LocalStorage(base_path=str(tmp_path))
    )
    payload = b"A shared public regulatory notice, identical for every reader."

    async with AsyncSessionLocal() as session:
        other_org = Organization(
            id=str(uuid.uuid4()), name="Other Org", slug=f"other-org-{uuid.uuid4().hex[:8]}"
        )
        session.add(other_org)
        await session.flush()

        source = await _source(session)

        first, first_duplicate = await upload_and_create_document(
            db=session,
            organization_id=demo_org.id,
            authority_id=source.authority_id,
            source_id=source.id,
            file_data=io.BytesIO(payload),
            file_name="shared-notice.txt",
            content_type="text/plain",
            title="Shared Notice (Org A copy)",
        )
        second, second_duplicate = await upload_and_create_document(
            db=session,
            organization_id=other_org.id,
            authority_id=source.authority_id,
            source_id=source.id,
            file_data=io.BytesIO(payload),
            file_name="shared-notice.txt",
            content_type="text/plain",
            title="Shared Notice (Org B copy)",
        )

        assert first_duplicate is False
        assert second_duplicate is False
        assert second.id != first.id
        assert second.organization_id == other_org.id
        assert first.organization_id == demo_org.id
        assert second.sha256 == first.sha256


async def test_cross_tenant_document_lookup_returns_404_not_the_record(
    client, demo_org, auth_headers, tmp_path, monkeypatch
):
    """
    A document id belonging to another organization must read as missing, not as
    forbidden and never as the record itself -- consistent with every other
    tenant-scoped lookup in this API (see app/api/routers/regulatory_documents.py).
    """
    from app.models.organization import Organization

    monkeypatch.setattr(
        "app.services.document_service.storage", LocalStorage(base_path=str(tmp_path))
    )

    async with AsyncSessionLocal() as session:
        other_org = Organization(
            id=str(uuid.uuid4()), name="Other Org", slug=f"other-org-{uuid.uuid4().hex[:8]}"
        )
        session.add(other_org)
        await session.flush()

        source = await _source(session)
        other_document, _ = await upload_and_create_document(
            db=session,
            organization_id=other_org.id,
            authority_id=source.authority_id,
            source_id=source.id,
            file_data=io.BytesIO(b"Another organization's private notice."),
            file_name="private.txt",
            content_type="text/plain",
            title="Private Notice",
        )

    response = await client.get(
        f"/api/v1/regulatory/documents/{other_document.id}", headers=auth_headers
    )

    assert response.status_code == 404
