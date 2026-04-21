from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Company, DeviceCompanyAssignment
from ..schemas import CompanyCreate, CompanyOut, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


def _to_out(company: Company, device_count: int) -> CompanyOut:
    return CompanyOut(
        id=company.id,
        name=company.name,
        description=company.description,
        created_at=company.created_at,
        updated_at=company.updated_at,
        device_count=device_count,
    )


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    stmt = (
        select(Company, func.count(DeviceCompanyAssignment.id))
        .outerjoin(
            DeviceCompanyAssignment,
            DeviceCompanyAssignment.company_id == Company.id,
        )
        .group_by(Company.id)
        .order_by(Company.name.asc())
    )
    results = db.execute(stmt).all()
    return [_to_out(c, int(count or 0)) for c, count in results]


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    company = Company(name=payload.name.strip(), description=payload.description)
    db.add(company)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Company name already exists")
    db.refresh(company)
    return _to_out(company, 0)


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    count = db.scalar(
        select(func.count(DeviceCompanyAssignment.id)).where(
            DeviceCompanyAssignment.company_id == company_id
        )
    )
    return _to_out(company, int(count or 0))


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int, payload: CompanyUpdate, db: Session = Depends(get_db)
):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if payload.name is not None:
        company.name = payload.name.strip()
    if payload.description is not None:
        company.description = payload.description
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Company name already exists")
    db.refresh(company)
    count = db.scalar(
        select(func.count(DeviceCompanyAssignment.id)).where(
            DeviceCompanyAssignment.company_id == company_id
        )
    )
    return _to_out(company, int(count or 0))


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    db.delete(company)
    db.commit()
    return None
