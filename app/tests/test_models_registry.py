"""
Model registry integrity.

Phase 6 broke SQLAlchemy mapper configuration outright: `Organization` and `User` declared
relationships to models that did not exist, `RegulatoryChange.impact_assessments` pointed at
a `back_populates` name `ImpactAssessment` did not use, and `ImpactItem.obligation` pointed
at an attribute `RegulatoryObligation` did not have. Mapper configuration is lazy, so none
of that surfaced until the first ORM query -- by which time every endpoint was already dead.

These tests force configuration eagerly and assert the relationship graph is coherent, so a
future mis-declared relationship fails here rather than at runtime in a router.
"""

import importlib
import pkgutil
import warnings

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import configure_mappers

import app.models as models_package
from app.db.base import Base

# Every model the platform is expected to map, per the Phase 1-6 design documents.
EXPECTED_MODELS = {
    # Phase 1
    "Organization",
    "User",
    # Phase 2
    "RegulatoryAuthority",
    "RegulatorySource",
    "IngestionRun",
    # Phase 3
    "RegulatoryDocument",
    "RegulatoryVersion",
    # Phase 4
    "RegulatoryChange",
    "RegulatoryObligation",
    # Phase 5
    "Product",
    "Market",
    "ProductMarket",
    "Process",
    "Control",
    "Registration",
    # Phase 6
    "ImpactAssessment",
    "ImpactItem",
    "ImpactReport",
    # Declared by Phase 1 relationships, implemented ahead of Phase 7
    "Action",
    "Evidence",
    "AuditEvent",
    "ImpactReview",
}


def _import_every_model_module():
    """Import all of app.models.*, not just what __init__ re-exports."""
    for module in pkgutil.iter_modules(models_package.__path__):
        importlib.import_module(f"app.models.{module.name}")


def _mapped_classes():
    return {
        cls.__name__: cls
        for cls in Base.registry._class_registry.values()
        if hasattr(cls, "__tablename__")
    }


def test_all_mappers_configure_without_error_or_warning():
    """The regression guard: eager configuration must be clean, not merely non-fatal."""
    _import_every_model_module()
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        configure_mappers()


def test_every_expected_model_is_mapped():
    _import_every_model_module()
    configure_mappers()
    assert EXPECTED_MODELS <= set(_mapped_classes())


def test_every_mapped_model_is_exported_from_app_models():
    """A model missing from __init__ is invisible to create_all and to Alembic autogenerate."""
    _import_every_model_module()
    assert set(_mapped_classes()) <= set(models_package.__all__)


def test_every_table_is_registered_in_metadata():
    _import_every_model_module()
    configure_mappers()
    tables = set(Base.metadata.tables)
    for name, cls in _mapped_classes().items():
        assert cls.__tablename__ in tables, name


@pytest.mark.parametrize(
    "model_name, relationship_name, target_name",
    [
        # The three relationships that were actually broken.
        ("Organization", "actions", "Action"),
        ("Organization", "evidence", "Evidence"),
        ("Organization", "audit_events", "AuditEvent"),
        ("User", "actions", "Action"),
        ("User", "reviews", "ImpactReview"),
        ("User", "audit_events", "AuditEvent"),
        ("RegulatoryChange", "impact_assessments", "ImpactAssessment"),
        ("RegulatoryObligation", "impact_items", "ImpactItem"),
        ("ImpactItem", "obligation", "RegulatoryObligation"),
        ("ImpactAssessment", "items", "ImpactItem"),
        ("ImpactAssessment", "reports", "ImpactReport"),
        ("ImpactAssessment", "reviews", "ImpactReview"),
        ("ImpactAssessment", "regulatory_change", "RegulatoryChange"),
    ],
)
def test_relationship_resolves_to_its_target(model_name, relationship_name, target_name):
    _import_every_model_module()
    configure_mappers()
    model = _mapped_classes()[model_name]
    relationships = inspect(model).relationships
    assert relationship_name in relationships, f"{model_name}.{relationship_name} missing"
    assert relationships[relationship_name].mapper.class_.__name__ == target_name


def test_back_populates_pairs_are_symmetric():
    """
    Every back_populates must name an attribute that exists on the target and points home.
    An asymmetric pair is exactly what took the mapper down.
    """
    _import_every_model_module()
    configure_mappers()
    for name, cls in _mapped_classes().items():
        for rel in inspect(cls).relationships:
            partner_name = rel.back_populates
            if not partner_name:
                continue
            target = rel.mapper.class_
            partner = inspect(target).relationships.get(partner_name)
            assert partner is not None, (
                f"{name}.{rel.key} back_populates '{partner_name}', "
                f"which does not exist on {target.__name__}"
            )
            assert partner.mapper.class_ is cls, (
                f"{name}.{rel.key} <-> {target.__name__}.{partner_name} is asymmetric"
            )
