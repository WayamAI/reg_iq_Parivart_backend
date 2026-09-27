from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, func
from typing import List, Optional
import uuid

from app.db.database import get_db
from app.models.portfolio import Product, ProductStatus
from app.api.schemas.portfolio import (
    ProductCreate,
    ProductUpdate,
    ProductResponse,
)
from app.api.dependencies.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/products", tags=["Portfolio - Products"])

@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_in: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Ensure the product_code is unique within the organization
    result = await db.execute(
        select(Product).where(
            Product.organization_id == current_user.organization_id,
            Product.product_code == product_in.product_code
        )
    )
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product with code '{product_in.product_code}' already exists in this organization"
        )

    product = Product(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        **product_in.dict()
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product

@router.get("/", response_model=List[ProductResponse])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[ProductStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Product).where(Product.organization_id == current_user.organization_id)
    if status:
        query = query.where(Product.status == status)
    result = await db.execute(query.offset(skip).limit(limit))
    products = result.scalars().all()
    return products

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == current_user.organization_id
        )
    )
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    product_in: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == current_user.organization_id
        )
    )
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = product_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    await db.commit()
    await db.refresh(product)
    return product

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == current_user.organization_id
        )
    )
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    await db.delete(product)
    await db.commit()
    return None