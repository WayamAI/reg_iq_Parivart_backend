"""
Evidence: the files that substantiate an action (Phase 8).

Evidence is what turns "we said we fixed it" into "here is what we did". It hangs
off an Action and nothing else -- the table has an `action_id` and no generic
entity pair -- so its place in the chain is: evidence -> action -> impact item ->
assessment -> regulatory change -> document.

Two properties, the same ones the rest of this layer keeps:

  * Every query is scoped to an organization, and an action belonging to another
    tenant is not a valid attachment point. Ownership is checked before the file
    is stored, so one tenant cannot even write a byte against another's action.
  * A recorded attachment and its audit event are one unit of work.

Unlike a regulatory document, evidence is **not** deduplicated by sha256. The same
file can legitimately be filed against two different actions, and refusing the
second would lose the fact that it was offered as evidence for both. The hash is
recorded as an integrity anchor, not as a uniqueness constraint.
"""

import uuid
from typing import BinaryIO, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.governance import Action, Evidence
from app.models.user import User
from app.services.audit_service import (
    ENTITY_ACTION,
    EVENT_EVIDENCE_ATTACHED,
    AuditService,
)
from app.services.document_service import compute_sha256, storage


class EvidenceService:
    """Organization-scoped operations over Evidence."""

    @staticmethod
    async def _resolve_action(
        session: AsyncSession, organization_id: str, action_id: str
    ) -> Action:
        """
        An action this organization owns, or ValueError.

        Checked before the file is stored, so a caller pointing at another tenant's
        action never causes a write of any kind.
        """
        action = (
            (
                await session.execute(
                    select(Action).where(
                        Action.id == action_id,
                        Action.organization_id == organization_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if action is None:
            raise ValueError(f"Action {action_id} not found")
        return action

    @staticmethod
    async def attach(
        session: AsyncSession,
        *,
        organization_id: str,
        action_id: str,
        file_data: BinaryIO,
        file_name: str,
        content_type: str,
        description: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> Evidence:
        """
        Store a file and record it as evidence for an action.

        Raises ValueError when the action is not visible to this organization.
        """
        await EvidenceService._resolve_action(session, organization_id, action_id)

        sha256 = await compute_sha256(file_data)
        storage_key = await storage.upload_file(file_data, file_name, content_type)

        evidence = Evidence(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            action_id=action_id,
            uploaded_by_id=actor_id,
            filename=file_name,
            storage_key=storage_key,
            sha256=sha256,
            description=description,
        )
        session.add(evidence)
        # Recorded against the ACTION, not the evidence row: the trail is read as the
        # history of the work, and "a file was attached" is an event in that history.
        AuditService.record(
            session,
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=EVENT_EVIDENCE_ATTACHED,
            entity_type=ENTITY_ACTION,
            entity_id=action_id,
            payload={
                "evidence_id": evidence.id,
                "filename": file_name,
                "sha256": sha256,
            },
        )
        await session.commit()
        await session.refresh(evidence)
        return evidence

    @staticmethod
    async def get(
        session: AsyncSession, *, organization_id: str, evidence_id: str
    ) -> Optional[Evidence]:
        return (
            (
                await session.execute(
                    select(Evidence)
                    .where(
                        Evidence.id == evidence_id,
                        Evidence.organization_id == organization_id,
                    )
                    .options(selectinload(Evidence.uploaded_by))
                )
            )
            .scalars()
            .first()
        )

    @staticmethod
    async def list_evidence(
        session: AsyncSession,
        *,
        organization_id: str,
        action_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Evidence]:
        """
        This organization's evidence, newest first.

        The uploader is eager-loaded for the same reason the audit trail loads its
        actor: a page of rows each resolving its own user would be a query per row,
        and "who filed this" is half the point of the record.
        """
        query = (
            select(Evidence)
            .where(Evidence.organization_id == organization_id)
            .options(selectinload(Evidence.uploaded_by))
        )
        if action_id is not None:
            query = query.where(Evidence.action_id == action_id)

        result = await session.execute(
            query.order_by(Evidence.created_at.desc(), Evidence.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def open_file(evidence: Evidence) -> BinaryIO:
        """
        Open the stored file for streaming.

        Takes an already-authorised Evidence row rather than an id, so the storage
        key is only ever resolved for a record the caller has been shown to own.
        """
        return await storage.download_file(evidence.storage_key)
