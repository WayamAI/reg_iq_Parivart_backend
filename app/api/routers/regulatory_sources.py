from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, func
from typing import List, Optional
import uuid
from datetime import datetime

from app.db.database import get_db
from app.ingestion.api_adapter import run_api_ingestion
from app.ingestion.html_adapter import run_html_ingestion
from app.ingestion.rss_ingestion import run_rss_ingestion
from app.models.regulatory import (
    RegulatoryAuthority,
    RegulatorySource,
    IngestionRun,
    IngestionStatus,
    SourceType,
)
from app.models.document import RegulatoryDocument
from app.api.schemas.regulatory import (
    SourceCreate,
    SourceUpdate,
    SourceResponse,
    IngestionRunCreate,
    IngestionRunResponse,
)
from app.api.dependencies.auth import get_current_user
from app.api.dependencies.permissions import require_configure

router = APIRouter(prefix="/sources", tags=["Regulatory Sources"])

@router.post("/", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    source_in: SourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_configure)
):
    # Verify the authority exists
    result = await db.execute(select(RegulatoryAuthority).where(RegulatoryAuthority.id == source_in.authority_id))
    authority = result.scalars().first()
    if not authority:
        raise HTTPException(status_code=400, detail="Authority not found")

    # id is a String(36) primary key with no column default, so an omitted id inserts
    # NULL and the insert fails -- the same bug class already fixed for documents
    # (f4b6853) and regulatory authorities (this session).
    #
    # source_in.url is a pydantic HttpUrl, not a str, and the url column is a plain
    # String(1000); passing the HttpUrl object straight through makes the insert fail
    # at the driver level ("type 'HttpUrl' is not supported" on SQLite; untested but
    # not guaranteed safe on every backend either) -- so every source create with a url
    # was broken. Stringify explicitly.
    source_data = source_in.dict()
    if source_data.get("url") is not None:
        source_data["url"] = str(source_data["url"])
    source = RegulatorySource(id=str(uuid.uuid4()), **source_data)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source

@router.get("/", response_model=List[SourceResponse])
async def list_sources(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    authority_id: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    query = select(RegulatorySource)
    if authority_id:
        query = query.where(RegulatorySource.authority_id == authority_id)
    if enabled is not None:
        query = query.where(RegulatorySource.enabled == enabled)
    result = await db.execute(query.offset(skip).limit(limit))
    sources = result.scalars().all()
    return sources

@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    result = await db.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source

@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: str,
    source_in: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_configure)
):
    result = await db.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    update_data = source_in.dict(exclude_unset=True)
    if update_data.get("url") is not None:
        update_data["url"] = str(update_data["url"])  # see create_source for why
    for field, value in update_data.items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return source

@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_configure)
):
    result = await db.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    await db.commit()
    return None

@router.post("/{source_id}/run", response_model=IngestionRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_source(
    source_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_configure)
):
    result = await db.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if not source.enabled:
        raise HTTPException(status_code=400, detail="Source is disabled")

    run_id = str(uuid.uuid4())

    # Each adapter shares the same (status, error, counters) contract (see
    # app/ingestion/rss_ingestion.py and app/ingestion/html_adapter.py) so the run
    # record is built identically regardless of which one ran.
    adapters = {
        SourceType.RSS: run_rss_ingestion,
        SourceType.HTML: run_html_ingestion,
        SourceType.API: run_api_ingestion,
        SourceType.WEB_SERVICE: run_api_ingestion,
    }
    adapter = adapters.get(source.source_type)

    if adapter is not None:
        # Run synchronously within the request (bounded by the adapter's own entry
        # limits/timeouts) so the response already carries the real outcome, rather
        # than the client needing to poll a background task for a small, bounded
        # piece of work. See docs/ingestion/INGESTION_RUN_STATUS.md.
        ingestion_status, error, counters = await adapter(
            db,
            source=source,
            organization_id=current_user.organization_id,
            actor_id=current_user.id,
        )
        run = IngestionRun(
            id=run_id,
            source_id=source_id,
            status=IngestionStatus[ingestion_status],
            completed_at=datetime.utcnow(),
            error=error,
            **counters,
        )
        source.last_run_at = datetime.utcnow()
        if ingestion_status in ("COMPLETED", "PARTIAL"):
            source.last_success_at = datetime.utcnow()
        if error:
            source.last_error = error
    else:
        # No adapter implemented for this source_type yet -- see
        # docs/ingestion/INGESTION_RUN_STATUS.md. The run is marked FAILED
        # immediately, with an explicit reason, rather than left at QUEUED: the
        # frontend's own TERMINAL_INGESTION_STATES (src/services/api/types.ts in the
        # frontend repo) already treats QUEUED as non-terminal and polls
        # GET /sources/{id}/runs waiting for it to settle. A run that can never leave
        # QUEUED is indistinguishable, from the frontend's point of view, from one
        # still legitimately in progress.
        run = IngestionRun(
            id=run_id,
            source_id=source_id,
            status=IngestionStatus.FAILED,
            completed_at=datetime.utcnow(),
            error=(
                f"No ingestion adapter is implemented for source_type={source.source_type.value}. "
                "This source's run was recorded but could not be executed."
            ),
        )
        source.last_run_at = datetime.utcnow()
        source.last_error = run.error

    db.add(run)
    await db.commit()
    await db.refresh(run)

    return run

@router.get("/{source_id}/runs", response_model=List[IngestionRunResponse])
async def list_source_runs(
    source_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # Verify the source exists
    result = await db.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    result = await db.execute(
        select(IngestionRun)
        .where(IngestionRun.source_id == source_id)
        .order_by(IngestionRun.started_at.desc())
        .offset(skip)
        .limit(limit)
    )
    runs = result.scalars().all()
    return runs

@router.get("/runs/{run_id}", response_model=IngestionRunResponse)
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    result = await db.execute(select(IngestionRun).where(IngestionRun.id == run_id))
    run = result.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run