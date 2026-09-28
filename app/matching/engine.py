"""
Impact Assessment engine.

    Regulatory Change -> Affected Obligations -> Portfolio Matching
        -> Products / Markets / Processes / Controls / Registrations
        -> Impact Items -> Impact Assessment

This path is entirely deterministic. It issues no AI/LLM call of any kind, so an assessment
is always produced even when every external provider is down. Optional AI enrichment lives
in `app/services/ai_enrichment.py` and runs after the fact, out of the request path.
"""

import json
import uuid
from typing import Dict, List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.matching import rules
from app.matching.rules import ENGINE_VERSION, EntityMatch, Evidence
from app.models.document import RegulatoryDocument
from app.models.impact import (
    AIEnrichmentStatus,
    EntityType,
    ImpactAssessment,
    ImpactAssessmentStatus,
    ImpactItem,
    MatchType,
)
from app.models.intelligence import RegulatoryChange, RegulatoryObligation
from app.models.portfolio import (
    Control,
    Market,
    Process,
    Product,
    ProductMarket,
    Registration,
)
from app.models.regulatory import RegulatoryAuthority

logger = structlog.get_logger()


class MatchingEngineService:
    @staticmethod
    async def analyze_change_impact(
        db: AsyncSession,
        organization_id: str,
        regulatory_change_id: str,
        force_reanalyze: bool = False,
    ) -> ImpactAssessment:
        """
        Run deterministic portfolio matching for a regulatory change and organization.

        Idempotent unless force_reanalyze is True: a second call returns the existing
        assessment instead of creating a duplicate.
        """
        existing = await MatchingEngineService._latest_assessment(
            db, organization_id, regulatory_change_id
        )
        if existing and not force_reanalyze:
            logger.info("reusing_existing_impact_assessment", assessment_id=existing.id)
            return existing

        change, document, authority = await MatchingEngineService._load_regulatory_context(
            db, organization_id, regulatory_change_id
        )
        obligations = await MatchingEngineService._load_obligations(db, change, document)
        portfolio = await MatchingEngineService._load_portfolio(db, organization_id)

        matches = MatchingEngineService._match(
            change=change,
            document=document,
            authority=authority,
            obligations=obligations,
            **portfolio,
        )

        return await MatchingEngineService._persist(
            db=db,
            organization_id=organization_id,
            change=change,
            matches=matches,
            obligation_count=len(obligations),
            previous=existing,
        )

    # ------------------------------------------------------------------ loading

    @staticmethod
    async def _latest_assessment(
        db: AsyncSession, organization_id: str, regulatory_change_id: str
    ) -> Optional[ImpactAssessment]:
        result = await db.execute(
            select(ImpactAssessment)
            .where(
                ImpactAssessment.organization_id == organization_id,
                ImpactAssessment.regulatory_change_id == regulatory_change_id,
            )
            .order_by(ImpactAssessment.analysis_version.desc())
        )
        return result.scalars().first()

    @staticmethod
    async def _load_regulatory_context(
        db: AsyncSession, organization_id: str, regulatory_change_id: str
    ):
        """
        Load the change, its document and the publishing authority.

        The change is only reachable through a document owned by the caller's organization.
        A change belonging to another tenant is indistinguishable from one that does not
        exist.
        """
        result = await db.execute(
            select(RegulatoryChange, RegulatoryDocument)
            .join(RegulatoryDocument, RegulatoryChange.document_id == RegulatoryDocument.id)
            .where(
                RegulatoryChange.id == regulatory_change_id,
                RegulatoryDocument.organization_id == organization_id,
            )
        )
        row = result.first()
        if row is None:
            raise ValueError(f"RegulatoryChange {regulatory_change_id} not found")
        change, document = row

        authority = None
        if document.authority_id:
            auth_result = await db.execute(
                select(RegulatoryAuthority).where(
                    RegulatoryAuthority.id == document.authority_id
                )
            )
            authority = auth_result.scalars().first()

        return change, document, authority

    @staticmethod
    async def _load_obligations(
        db: AsyncSession, change: RegulatoryChange, document: RegulatoryDocument
    ) -> List[RegulatoryObligation]:
        result = await db.execute(
            select(RegulatoryObligation).where(
                RegulatoryObligation.change_id == change.id
            )
        )
        obligations = list(result.scalars().all())
        if obligations or document is None:
            return obligations

        # Obligations extracted at document level, not yet attributed to a change.
        result = await db.execute(
            select(RegulatoryObligation).where(
                RegulatoryObligation.document_id == document.id
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def _load_portfolio(db: AsyncSession, organization_id: str) -> Dict[str, list]:
        """Load every portfolio entity for this organization, and nothing outside it."""
        products = (
            await db.execute(
                select(Product).where(
                    Product.organization_id == organization_id,
                    Product.status == "ACTIVE",
                )
            )
        ).scalars().all()

        markets = (
            await db.execute(
                select(Market).where(
                    Market.organization_id == organization_id,
                    Market.status == "ACTIVE",
                )
            )
        ).scalars().all()

        # Scoped through Product: ProductMarket carries no organization_id of its own.
        product_markets = (
            await db.execute(
                select(ProductMarket)
                .join(Product, ProductMarket.product_id == Product.id)
                .where(Product.organization_id == organization_id)
            )
        ).scalars().all()

        processes = (
            await db.execute(
                select(Process).where(Process.organization_id == organization_id)
            )
        ).scalars().all()

        controls = (
            await db.execute(
                select(Control).where(
                    Control.organization_id == organization_id,
                    Control.status == "ACTIVE",
                )
            )
        ).scalars().all()

        registrations = (
            await db.execute(
                select(Registration).where(
                    Registration.organization_id == organization_id
                )
            )
        ).scalars().all()

        return {
            "products": list(products),
            "markets": list(markets),
            "product_markets": list(product_markets),
            "processes": list(processes),
            "controls": list(controls),
            "registrations": list(registrations),
        }

    # ----------------------------------------------------------------- matching

    @staticmethod
    def _match(
        change,
        document,
        authority,
        obligations,
        products,
        markets,
        product_markets,
        processes,
        controls,
        registrations,
    ) -> List[EntityMatch]:
        matches: List[EntityMatch] = []

        # 1. Which of our markets does this authority/document actually reach?
        resolved_markets = rules.resolve_markets(markets, document, authority)
        market_by_id = {m.id: m for m in markets}
        for market_id, evidence in resolved_markets.items():
            market = market_by_id[market_id]
            match = EntityMatch(
                entity_type=EntityType.MARKET,
                entity_id=market_id,
                entity_label=f"Market '{market.name}'",
            )
            for item in evidence:
                match.add(item)
            matches.append(match)

        # 2. Products we actually sell into those markets, via ProductMarket.
        haystack = rules.build_regulatory_haystack(change, obligations)
        product_by_id = {p.id: p for p in products}
        product_market_links: Dict[str, List[str]] = {}
        for link in product_markets:
            if link.market_id in resolved_markets and link.product_id in product_by_id:
                product_market_links.setdefault(link.product_id, []).append(link.market_id)

        matched_product_ids = set()
        for product_id, market_ids in product_market_links.items():
            product = product_by_id[product_id]
            match = EntityMatch(
                entity_type=EntityType.PRODUCT,
                entity_id=product_id,
                entity_label=f"Product '{product.name}' ({product.product_code})",
            )
            for market_id in market_ids:
                match.add(
                    Evidence(
                        match_type=MatchType.JURISDICTION_MATCH,
                        axis=f"product_market:{market_id}",
                        regulatory_field="resolved market",
                        regulatory_value=market_by_id[market_id].name,
                        portfolio_field="product_market.market_id",
                        portfolio_value=market_id,
                    )
                )
            for item in rules.product_term_evidence(product, haystack):
                match.add(item)
            matches.append(match)
            matched_product_ids.add(product_id)

        # 3. Processes implicated by an obligation category that is actually present.
        matched_process_ids = set()
        for process in processes:
            evidence = rules.process_evidence(process, obligations)
            if not evidence:
                continue
            match = EntityMatch(
                entity_type=EntityType.PROCESS,
                entity_id=process.id,
                entity_label=f"Process '{process.name}'",
            )
            for item in evidence:
                match.add(item)
            matches.append(match)
            matched_process_ids.add(process.id)

        # 4. Controls mapped from obligation categories, or guarding a matched entity.
        for control in controls:
            evidence = rules.control_evidence(
                control, obligations, matched_product_ids, matched_process_ids
            )
            if not evidence:
                continue
            match = EntityMatch(
                entity_type=EntityType.CONTROL,
                entity_id=control.id,
                entity_label=f"Control '{control.name}'",
            )
            for item in evidence:
                match.add(item)
            matches.append(match)

        # 5. Registrations exposed via the publishing authority or a resolved market.
        for registration in registrations:
            evidence = rules.registration_evidence(
                registration, document, set(resolved_markets)
            )
            if not evidence:
                continue
            match = EntityMatch(
                entity_type=EntityType.REGISTRATION,
                entity_id=registration.id,
                entity_label=(
                    f"Registration '{registration.registration_number or registration.id}'"
                ),
            )
            for item in evidence:
                match.add(item)
            matches.append(match)

        return matches

    # --------------------------------------------------------------- persisting

    @staticmethod
    async def _persist(
        db: AsyncSession,
        organization_id: str,
        change: RegulatoryChange,
        matches: List[EntityMatch],
        obligation_count: int,
        previous: Optional[ImpactAssessment],
    ) -> ImpactAssessment:
        overall_level, overall_confidence = rules.aggregate_overall(matches)
        assessment_id = str(uuid.uuid4())

        if matches:
            summary = (
                f"Deterministic portfolio matching identified {len(matches)} affected "
                f"portfolio entities across {obligation_count} linked obligation(s) for "
                f"regulatory change: {change.summary}"
            )
        else:
            summary = (
                "Deterministic portfolio matching found no link between this regulatory "
                f"change and the organization's portfolio. {obligation_count} linked "
                "obligation(s) were considered."
            )

        assessment = ImpactAssessment(
            id=assessment_id,
            organization_id=organization_id,
            regulatory_change_id=change.id,
            status=ImpactAssessmentStatus.COMPLETED,
            overall_impact_level=overall_level,
            overall_confidence=overall_confidence,
            summary=summary,
            analysis_version=(previous.analysis_version + 1) if previous else 1,
            engine_version=ENGINE_VERSION,
            # No AI was consulted, so nothing is claimed about AI provenance.
            ai_model=None,
            prompt_version=None,
            ai_enrichment_status=AIEnrichmentStatus.DISABLED,
        )
        db.add(assessment)
        await db.flush()

        for match in matches:
            db.add(
                ImpactItem(
                    id=str(uuid.uuid4()),
                    impact_assessment_id=assessment_id,
                    obligation_id=match.obligation_id,
                    entity_type=match.entity_type,
                    entity_id=match.entity_id,
                    impact_level=match.impact_level,
                    confidence=match.confidence,
                    match_score=match.match_score,
                    reason=match.reason(),
                    match_types=",".join(mt.value for mt in match.match_types),
                    evidence=json.dumps(match.evidence_payload()),
                    status="ACTIVE",
                )
            )

        await db.commit()
        await db.refresh(assessment)
        logger.info(
            "impact_assessment_completed",
            assessment_id=assessment_id,
            items=len(matches),
            overall_impact_level=overall_level.value,
            engine_version=ENGINE_VERSION,
        )
        return assessment
