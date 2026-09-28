"""
Deterministic portfolio-matching rules.

Every function here is pure: it reads attributes off already-loaded ORM instances and
returns evidence. There is no database I/O, no network I/O and no AI call anywhere in this
module, which is what lets the Impact Assessment engine run with the AI provider completely
unavailable.

A rule only fires on evidence that genuinely exists in the database. If nothing links a
portfolio entity to a regulatory change, no impact item is produced -- there is no
"assume everything is affected" fallback.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.models.impact import ImpactLevel, MatchType
from app.models.intelligence import ObligationCategory
from app.models.portfolio import ControlCategory

ENGINE_VERSION = "deterministic-v2"

# Weight contributed by each signal towards an entity's match score. Scores are the sum of
# the weights of the signals that actually fired, clamped to [0, 1]. These are the only
# numbers in the engine that are chosen rather than derived, and they exist so that the
# ordering of results is reviewable and stable.
SIGNAL_WEIGHTS: Dict[MatchType, float] = {
    MatchType.JURISDICTION_MATCH: 0.40,
    MatchType.MARKET_MATCH: 0.40,
    MatchType.PRODUCT_CATEGORY_MATCH: 0.30,
    MatchType.PRODUCT_KEYWORD_MATCH: 0.20,
    MatchType.PROCESS_MATCH: 0.45,
    MatchType.CONTROL_MATCH: 0.35,
    MatchType.REGISTRATION_MATCH: 0.50,
}

# Confidence expresses *evidence strength*: how many mutually independent pieces of
# evidence support the match, not how strong the impact is.
CONFIDENCE_BY_EVIDENCE_COUNT: Dict[int, float] = {0: 0.0, 1: 0.50, 2: 0.75}
CONFIDENCE_MAX = 0.90

# Documented thresholds over match_score.
IMPACT_LEVEL_THRESHOLDS: Sequence[tuple] = (
    (0.80, ImpactLevel.HIGH),
    (0.55, ImpactLevel.MEDIUM),
    (0.30, ImpactLevel.LOW),
)

# An obligation category implicates an internal process only through this explicit table.
# Absent an obligation in a mapped category, no process is reported as affected.
OBLIGATION_CATEGORY_TO_PROCESS_NAMES: Dict[ObligationCategory, tuple] = {
    ObligationCategory.LABELING: ("Labeling",),
    ObligationCategory.PACKAGING: ("Packaging",),
    ObligationCategory.MANUFACTURING: ("Manufacturing",),
    ObligationCategory.QUALITY: ("Quality Assurance",),
    ObligationCategory.SAFETY: ("Risk Management", "Post-Market Surveillance"),
    ObligationCategory.POST_MARKET: ("Post-Market Surveillance",),
    ObligationCategory.REGISTRATION: ("Regulatory Submission",),
    ObligationCategory.SUBMISSION: ("Regulatory Submission",),
    ObligationCategory.CLINICAL: ("Clinical Evaluation",),
    ObligationCategory.REPORTING: ("Post-Market Surveillance",),
}

# An obligation category implicates a control only through this explicit table.
OBLIGATION_CATEGORY_TO_CONTROL_CATEGORIES: Dict[ObligationCategory, tuple] = {
    ObligationCategory.LABELING: (ControlCategory.LABELING,),
    ObligationCategory.MANUFACTURING: (ControlCategory.MANUFACTURING,),
    ObligationCategory.QUALITY: (ControlCategory.QUALITY,),
    ObligationCategory.SAFETY: (ControlCategory.SAFETY, ControlCategory.RISK),
    ObligationCategory.CYBERSECURITY: (ControlCategory.CYBERSECURITY,),
    ObligationCategory.DATA: (ControlCategory.DATA,),
    ObligationCategory.CLINICAL: (ControlCategory.CLINICAL,),
    ObligationCategory.REGISTRATION: (ControlCategory.REGULATORY,),
    ObligationCategory.SUBMISSION: (ControlCategory.REGULATORY,),
    ObligationCategory.RECORDKEEPING: (ControlCategory.DATA,),
}

# Keyword tokens shorter than this are ignored: two- and three-letter fragments produce
# coincidental hits rather than evidence.
MIN_KEYWORD_LENGTH = 4


def norm(value: Any) -> Optional[str]:
    """Case-fold and trim a value for comparison. NULL-safe by design."""
    if value is None:
        return None
    text = str(getattr(value, "value", value)).strip()
    return text.lower() or None


@dataclass
class Evidence:
    """One concrete, citable reason an entity is considered affected."""

    match_type: MatchType
    axis: str
    regulatory_field: str
    regulatory_value: str
    portfolio_field: str
    portfolio_value: str
    obligation_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "match_type": self.match_type.value,
            "axis": self.axis,
            "regulatory_field": self.regulatory_field,
            "regulatory_value": self.regulatory_value,
            "portfolio_field": self.portfolio_field,
            "portfolio_value": self.portfolio_value,
            "obligation_id": self.obligation_id,
        }


@dataclass
class EntityMatch:
    """Accumulated evidence for a single portfolio entity."""

    entity_type: Any
    entity_id: str
    entity_label: str
    evidence: List[Evidence] = field(default_factory=list)

    def add(self, item: Evidence) -> None:
        self.evidence.append(item)

    @property
    def match_types(self) -> List[MatchType]:
        seen: List[MatchType] = []
        for item in self.evidence:
            if item.match_type not in seen:
                seen.append(item.match_type)
        return seen

    @property
    def match_score(self) -> float:
        total = sum(SIGNAL_WEIGHTS.get(mt, 0.0) for mt in self.match_types)
        return round(min(total, 1.0), 2)

    @property
    def confidence(self) -> float:
        """Derived from the number of independent evidence axes that fired."""
        axes = {item.axis for item in self.evidence}
        return CONFIDENCE_BY_EVIDENCE_COUNT.get(len(axes), CONFIDENCE_MAX)

    @property
    def impact_level(self) -> ImpactLevel:
        score = self.match_score
        for threshold, level in IMPACT_LEVEL_THRESHOLDS:
            if score >= threshold:
                return level
        # Something matched, but only weakly. Say so rather than asserting a level.
        return ImpactLevel.POTENTIALLY_AFFECTED

    @property
    def obligation_id(self) -> Optional[str]:
        """The specific obligation that produced this match, if any did."""
        for item in self.evidence:
            if item.obligation_id:
                return item.obligation_id
        return None

    def reason(self) -> str:
        parts = [
            f"{e.regulatory_field}='{e.regulatory_value}' matches "
            f"{e.portfolio_field}='{e.portfolio_value}'"
            for e in self.evidence
        ]
        return f"{self.entity_label} is affected because " + "; ".join(parts) + "."

    def evidence_payload(self) -> Dict[str, Any]:
        return {
            "entity_label": self.entity_label,
            "match_types": [mt.value for mt in self.match_types],
            "match_score": self.match_score,
            "confidence": self.confidence,
            "signals": [e.as_dict() for e in self.evidence],
        }


def resolve_markets(markets, document, authority) -> Dict[str, List[Evidence]]:
    """
    Link the publishing authority / document to the organization's own markets.

    Three mutually independent axes are checked, all of which are structured fields
    already stored in PARIVART:

      authority.short_name              <-> market.regulatory_jurisdiction
      authority/document .jurisdiction  <-> market.name, market.regulatory_jurisdiction
      authority/document .country       <-> market.country

    Returns {market_id: [Evidence, ...]} containing only markets with at least one axis.
    """
    axes = []
    if authority is not None and norm(authority.short_name):
        axes.append(
            (
                "authority_short_name",
                "authority.short_name",
                authority.short_name,
                (("market.regulatory_jurisdiction", "regulatory_jurisdiction"),),
            )
        )
    for src_obj, src_name in ((document, "document"), (authority, "authority")):
        if src_obj is None:
            continue
        if norm(getattr(src_obj, "jurisdiction", None)):
            axes.append(
                (
                    "jurisdiction",
                    f"{src_name}.jurisdiction",
                    src_obj.jurisdiction,
                    (
                        ("market.name", "name"),
                        ("market.regulatory_jurisdiction", "regulatory_jurisdiction"),
                    ),
                )
            )
        if norm(getattr(src_obj, "country", None)):
            axes.append(
                (
                    "country",
                    f"{src_name}.country",
                    src_obj.country,
                    (("market.country", "country"),),
                )
            )

    resolved: Dict[str, List[Evidence]] = {}
    for market in markets:
        for axis, reg_field, reg_value, targets in axes:
            reg_norm = norm(reg_value)
            for portfolio_field, attr in targets:
                portfolio_value = getattr(market, attr, None)
                if norm(portfolio_value) != reg_norm:
                    continue
                found = resolved.setdefault(market.id, [])
                if any(e.axis == axis for e in found):
                    break  # one axis counts once
                found.append(
                    Evidence(
                        match_type=MatchType.MARKET_MATCH,
                        axis=axis,
                        regulatory_field=reg_field,
                        regulatory_value=str(reg_value),
                        portfolio_field=portfolio_field,
                        portfolio_value=str(portfolio_value),
                    )
                )
                break
    return resolved


def build_regulatory_haystack(change, obligations) -> str:
    """Concatenate the regulatory text that keyword matching is allowed to search."""
    chunks = [change.summary, change.new_text, change.previous_text, change.section]
    chunks += [o.text for o in obligations]
    chunks += [o.applicability for o in obligations]
    return " ".join(norm(c) or "" for c in chunks)


def product_term_evidence(product, haystack: str) -> List[Evidence]:
    """
    Category and keyword signals for a product, drawn only from fields the organization
    itself populated (category, sub_category, keywords) appearing in the regulatory text.
    """
    found: List[Evidence] = []
    for match_type, portfolio_field, raw in (
        (MatchType.PRODUCT_CATEGORY_MATCH, "product.category", product.category),
        (MatchType.PRODUCT_CATEGORY_MATCH, "product.sub_category", product.sub_category),
    ):
        term = norm(raw)
        if term and len(term) >= MIN_KEYWORD_LENGTH and term in haystack:
            found.append(
                Evidence(
                    match_type=match_type,
                    axis=f"term:{term}",
                    regulatory_field="change/obligation text",
                    regulatory_value=term,
                    portfolio_field=portfolio_field,
                    portfolio_value=str(raw),
                )
            )

    for keyword in (product.keywords or "").split(","):
        term = norm(keyword)
        if not term or len(term) < MIN_KEYWORD_LENGTH or term not in haystack:
            continue
        if any(e.axis == f"term:{term}" for e in found):
            continue
        found.append(
            Evidence(
                match_type=MatchType.PRODUCT_KEYWORD_MATCH,
                axis=f"term:{term}",
                regulatory_field="change/obligation text",
                regulatory_value=term,
                portfolio_field="product.keywords",
                portfolio_value=keyword.strip(),
            )
        )
    return found


def process_evidence(process, obligations) -> List[Evidence]:
    """A process is affected only when a mapped obligation category is actually present."""
    found: List[Evidence] = []
    process_name = norm(process.name)
    for obligation in obligations:
        try:
            category = ObligationCategory(getattr(obligation.category, "value", obligation.category))
        except ValueError:
            continue
        for mapped in OBLIGATION_CATEGORY_TO_PROCESS_NAMES.get(category, ()):
            if norm(mapped) != process_name:
                continue
            found.append(
                Evidence(
                    match_type=MatchType.PROCESS_MATCH,
                    axis=f"obligation_category:{category.value}",
                    regulatory_field="obligation.category",
                    regulatory_value=category.value,
                    portfolio_field="process.name",
                    portfolio_value=str(process.name),
                    obligation_id=obligation.id,
                )
            )
    return found


def control_evidence(control, obligations, matched_product_ids, matched_process_ids) -> List[Evidence]:
    """
    A control is affected either because its category is mapped from a present obligation
    category, or because it guards a product/process that already matched.
    """
    found: List[Evidence] = []
    control_category = norm(control.category)
    for obligation in obligations:
        try:
            category = ObligationCategory(getattr(obligation.category, "value", obligation.category))
        except ValueError:
            continue
        for mapped in OBLIGATION_CATEGORY_TO_CONTROL_CATEGORIES.get(category, ()):
            if norm(mapped) != control_category:
                continue
            found.append(
                Evidence(
                    match_type=MatchType.CONTROL_MATCH,
                    axis=f"obligation_category:{category.value}",
                    regulatory_field="obligation.category",
                    regulatory_value=category.value,
                    portfolio_field="control.category",
                    portfolio_value=str(getattr(control.category, "value", control.category)),
                    obligation_id=obligation.id,
                )
            )

    if control.product_id and control.product_id in matched_product_ids:
        found.append(
            Evidence(
                match_type=MatchType.CONTROL_MATCH,
                axis="control_guards_matched_product",
                regulatory_field="impact_item.entity_id (PRODUCT)",
                regulatory_value=control.product_id,
                portfolio_field="control.product_id",
                portfolio_value=control.product_id,
            )
        )
    if control.process_id and control.process_id in matched_process_ids:
        found.append(
            Evidence(
                match_type=MatchType.CONTROL_MATCH,
                axis="control_guards_matched_process",
                regulatory_field="impact_item.entity_id (PROCESS)",
                regulatory_value=control.process_id,
                portfolio_field="control.process_id",
                portfolio_value=control.process_id,
            )
        )
    return found


def registration_evidence(registration, document, resolved_market_ids) -> List[Evidence]:
    """A registration is exposed if it was granted by the publishing authority, or sits in
    a market the change reaches."""
    found: List[Evidence] = []
    authority_id = getattr(document, "authority_id", None) if document is not None else None
    if authority_id and registration.authority_id == authority_id:
        found.append(
            Evidence(
                match_type=MatchType.REGISTRATION_MATCH,
                axis="authority_id",
                regulatory_field="document.authority_id",
                regulatory_value=str(authority_id),
                portfolio_field="registration.authority_id",
                portfolio_value=str(registration.authority_id),
            )
        )
    if registration.market_id and registration.market_id in resolved_market_ids:
        found.append(
            Evidence(
                match_type=MatchType.REGISTRATION_MATCH,
                axis="market_id",
                regulatory_field="resolved market",
                regulatory_value=str(registration.market_id),
                portfolio_field="registration.market_id",
                portfolio_value=str(registration.market_id),
            )
        )
    return found


def aggregate_overall(matches: Sequence[EntityMatch]) -> tuple:
    """
    Roll item-level results up to the assessment. Returns (impact_level, confidence).

    With no matches the portfolio was still fully scanned, so the result is a confident
    NO_MATCH rather than a low-confidence guess.
    """
    if not matches:
        return ImpactLevel.NO_MATCH, CONFIDENCE_MAX

    order = [
        ImpactLevel.NO_MATCH,
        ImpactLevel.POTENTIALLY_AFFECTED,
        ImpactLevel.LOW,
        ImpactLevel.MEDIUM,
        ImpactLevel.HIGH,
    ]
    highest = max(matches, key=lambda m: order.index(m.impact_level)).impact_level
    mean_confidence = sum(m.confidence for m in matches) / len(matches)
    return highest, round(mean_confidence, 2)
