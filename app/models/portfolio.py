from sqlalchemy import Column, String, Text, DateTime, Enum, ForeignKey, func, Boolean, Integer
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base

class ProductStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"
    DRAFT = "DRAFT"

class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True)
    name = Column(String(255), nullable=False)
    product_code = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text)
    category = Column(String(100))
    sub_category = Column(String(100))
    status = Column(Enum(ProductStatus, native_enum=False), default=ProductStatus.ACTIVE)
    regulatory_class = Column(String(100))
    keywords = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="products")
    product_markets = relationship("ProductMarket", back_populates="product")
    controls = relationship("Control", back_populates="product")
    registrations = relationship("Registration", back_populates="product")

class MarketStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PLANNED = "PLANNED"

class Market(Base):
    __tablename__ = "markets"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True)
    name = Column(String(255), nullable=False)
    country = Column(String(100), nullable=False)
    region = Column(String(100))
    regulatory_jurisdiction = Column(String(100))
    status = Column(Enum(MarketStatus, native_enum=False), default=MarketStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="markets")
    product_markets = relationship("ProductMarket", back_populates="market")
    registrations = relationship("Registration", back_populates="market")

class ProductMarket(Base):
    __tablename__ = "product_markets"

    id = Column(String(36), primary_key=True, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), index=True)
    market_id = Column(String(36), ForeignKey("markets.id"), index=True)
    status = Column(Enum(MarketStatus, native_enum=False), default=MarketStatus.ACTIVE)
    launch_date = Column(DateTime(timezone=True))
    registration_status = Column(String(100))
    registration_reference = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="product_markets")
    market = relationship("Market", back_populates="product_markets")

class Process(Base):
    __tablename__ = "processes"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="processes")
    controls = relationship("Control", back_populates="process")

class ControlCategory(str, enum.Enum):
    QUALITY = "QUALITY"
    SAFETY = "SAFETY"
    REGULATORY = "REGULATORY"
    CYBERSECURITY = "CYBERSECURITY"
    DATA = "DATA"
    MANUFACTURING = "MANUFACTURING"
    LABELING = "LABELING"
    CLINICAL = "CLINICAL"
    RISK = "RISK"
    OTHER = "OTHER"

class ControlStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DRAFT = "DRAFT"

class Control(Base):
    __tablename__ = "controls"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True)
    product_id = Column(String(36), ForeignKey("products.id"), index=True)
    process_id = Column(String(36), ForeignKey("processes.id"), index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(Enum(ControlCategory, native_enum=False), default=ControlCategory.OTHER)
    owner = Column(String(255))
    status = Column(Enum(ControlStatus, native_enum=False), default=ControlStatus.ACTIVE)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="controls")
    product = relationship("Product", back_populates="controls")
    process = relationship("Process", back_populates="controls")

class RegistrationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"

class Registration(Base):
    __tablename__ = "registrations"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True)
    product_id = Column(String(36), ForeignKey("products.id"), index=True)
    market_id = Column(String(36), ForeignKey("markets.id"), index=True)
    authority_id = Column(String(36), ForeignKey("regulatory_authorities.id"), index=True)
    registration_number = Column(String(200))
    status = Column(Enum(RegistrationStatus, native_enum=False), default=RegistrationStatus.PENDING)
    valid_from = Column(DateTime(timezone=True))
    valid_until = Column(DateTime(timezone=True))
    registration_metadata = Column("metadata", Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="registrations")
    product = relationship("Product", back_populates="registrations")
    market = relationship("Market", back_populates="registrations")
    authority = relationship("RegulatoryAuthority")