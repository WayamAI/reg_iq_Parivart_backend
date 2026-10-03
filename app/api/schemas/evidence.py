"""
Wire shapes for evidence.

Evidence attaches to an **action** and to nothing else. The table carries only
`action_id`, with no generic `entity_type`/`entity_id` pair, so evidence reaches the
rest of the chain through the action it belongs to: evidence -> action -> impact item
-> assessment -> regulatory change -> document. A client should present that real
graph rather than a generic one the data does not support.

`storage_key` is deliberately absent from every response. It is an internal
filesystem path, and a client has no legitimate use for it: retrieval goes through
the download endpoint, which resolves the key server-side after checking the tenant.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EvidenceResponse(BaseModel):
    """
    One attached file.

    `sha256` is the integrity anchor: it is what lets someone assert months later
    that the file they are looking at is the file that was filed.
    """

    id: str
    action_id: Optional[str] = None
    uploaded_by_id: Optional[str] = None
    uploaded_by_name: Optional[str] = None
    uploaded_by_email: Optional[str] = None
    filename: Optional[str] = None
    sha256: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class EvidenceUploadForm(BaseModel):
    """
    The non-file half of an upload, documented here for the contract's sake.

    The endpoint itself takes multipart/form-data, so these arrive as form fields
    beside the file rather than as a JSON body.
    """

    action_id: str = Field(min_length=1)
    description: Optional[str] = Field(default=None, max_length=10_000)
