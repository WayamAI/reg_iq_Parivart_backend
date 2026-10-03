"""
Wire shapes for regulatory changes and the obligations they create.

These are the "what changed" and "what it requires" half of the product, and until
now nothing served them: the ingestion pipeline wrote them and an impact assessment
referenced a `regulatory_change_id` that no endpoint could resolve.

Both are read-only over HTTP. The document-processing pipeline owns these rows --
they are what it extracted from a source document, not user-entered data - so there
is no create, update or delete. Editing an extracted obligation by hand would break
the provenance that makes it worth anything.

`confidence` is `Numeric(3, 2)` in the database, which SQLAlchemy hands back as a
Decimal; it is declared as a float here so it serialises as a JSON number rather
than a string.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.intelligence import ChangeType, ObligationCategory


class RegulatoryChangeResponse(BaseModel):
    """
    One extracted change, with the provenance of the extraction.

    `previous_text` and `new_text` are the before and after as they appeared in the
    source, and `ai_model`/`prompt_version` say what produced the reading -- so a
    reviewer can weigh the interpretation rather than having to trust it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: Optional[str] = None
    version_id: Optional[str] = None
    section: Optional[str] = None
    change_type: ChangeType
    summary: str
    previous_text: Optional[str] = None
    new_text: Optional[str] = None
    source_reference: Optional[str] = None
    confidence: Optional[float] = None
    prompt_version: Optional[str] = None
    ai_model: Optional[str] = None
    created_at: Optional[datetime] = None


class RegulatoryObligationResponse(BaseModel):
    """
    One requirement arising from a change.

    `source_page` and `source_section` are what let a reader go back to the document
    and check the obligation against its origin.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    change_id: Optional[str] = None
    document_id: Optional[str] = None
    text: str
    category: ObligationCategory
    applicability: Optional[str] = None
    jurisdiction: Optional[str] = None
    effective_date: Optional[datetime] = None
    source_page: Optional[str] = None
    source_section: Optional[str] = None
    confidence: Optional[float] = None
    prompt_version: Optional[str] = None
    ai_model: Optional[str] = None
    created_at: Optional[datetime] = None
