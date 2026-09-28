from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from app.models.user import UserRole

class OrganizationBase(BaseModel):
    name: str
    slug: str
    industry: Optional[str] = None
    description: Optional[str] = None

class OrganizationCreate(OrganizationBase):
    pass

class OrganizationResponse(OrganizationBase):
    id: str

    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    # bcrypt hashes at most 72 bytes. Constraining the field here rejects longer input as
    # a 422 with a clear message instead of failing inside hash_password(). Multi-byte
    # passwords that fit in 72 characters but exceed 72 bytes are caught by the
    # PasswordTooLongError handler in app/main.py.
    password: str = Field(min_length=8, max_length=72)
    role: UserRole = UserRole.VIEWER

class UserResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    email: EmailStr
    role: UserRole
    is_active: bool

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
