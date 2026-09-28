from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Optional, List
from app.models.portfolio import (
    ProductStatus,
    MarketStatus,
    ControlCategory,
    ControlStatus,
    RegistrationStatus,
)
from datetime import datetime

# Product Schemas
class ProductBase(BaseModel):
    name: str
    product_code: str
    description: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    status: ProductStatus = ProductStatus.ACTIVE
    regulatory_class: Optional[str] = None
    keywords: Optional[str] = None

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    product_code: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    status: Optional[ProductStatus] = None
    regulatory_class: Optional[str] = None
    keywords: Optional[str] = None

class ProductResponse(ProductBase):
    id: str
    organization_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Market Schemas
class MarketBase(BaseModel):
    name: str
    country: str
    region: Optional[str] = None
    regulatory_jurisdiction: Optional[str] = None
    status: MarketStatus = MarketStatus.ACTIVE

class MarketCreate(MarketBase):
    pass

class MarketUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    regulatory_jurisdiction: Optional[str] = None
    status: Optional[MarketStatus] = None

class MarketResponse(MarketBase):
    id: str
    organization_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# ProductMarket Schemas (for the association)
class ProductMarketBase(BaseModel):
    product_id: str
    market_id: str
    status: MarketStatus = MarketStatus.ACTIVE
    launch_date: Optional[datetime] = None
    registration_status: Optional[str] = None
    registration_reference: Optional[str] = None

class ProductMarketCreate(ProductMarketBase):
    pass

class ProductMarketUpdate(BaseModel):
    status: Optional[MarketStatus] = None
    launch_date: Optional[datetime] = None
    registration_status: Optional[str] = None
    registration_reference: Optional[str] = None

class ProductMarketResponse(ProductMarketBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Process Schemas
class ProcessBase(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None

class ProcessCreate(ProcessBase):
    pass

class ProcessUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None

class ProcessResponse(ProcessBase):
    id: str
    organization_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Control Schemas
class ControlBase(BaseModel):
    product_id: Optional[str] = None
    process_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    category: ControlCategory = ControlCategory.OTHER
    owner: Optional[str] = None
    status: ControlStatus = ControlStatus.ACTIVE

class ControlCreate(ControlBase):
    pass

class ControlUpdate(BaseModel):
    product_id: Optional[str] = None
    process_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[ControlCategory] = None
    owner: Optional[str] = None
    status: Optional[ControlStatus] = None

class ControlResponse(ControlBase):
    id: str
    organization_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Registration Schemas
class RegistrationBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    product_id: str
    market_id: str
    authority_id: str
    registration_number: Optional[str] = None
    status: RegistrationStatus = RegistrationStatus.PENDING
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    registration_metadata: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("registration_metadata", "metadata"),
        serialization_alias="metadata",
    )

class RegistrationCreate(RegistrationBase):
    pass

class RegistrationUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    product_id: Optional[str] = None
    market_id: Optional[str] = None
    authority_id: Optional[str] = None
    registration_number: Optional[str] = None
    status: Optional[RegistrationStatus] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    registration_metadata: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("registration_metadata", "metadata"),
        serialization_alias="metadata",
    )

class RegistrationResponse(RegistrationBase):
    model_config = ConfigDict(
        populate_by_name=True, serialize_by_alias=True, from_attributes=True
    )

    id: str
    organization_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None