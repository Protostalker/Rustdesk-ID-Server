from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Company, Device, DeviceCompanyAssignment
from ..schemas import DeviceCompanyOut, DeviceCreate, DeviceOut, DeviceUpdate

router = APIRouter(prefix="/devices", tags=["devices"])


def _to_out(device: Device) -> DeviceOut:
    companies = [
        DeviceCompanyOut(id=a.company.id, name=a.company.name)
        for a in device.assignments
        if a.company is not None
    ]
    return DeviceOut(
        id=device.id,
        rustdesk_id=device.rustdesk_id,
        nickname=device.nickname,
        hostname=device.hostname,
        alias_from_rustdesk=device.alias_from_rustdesk,
        notes=device.notes,
        last_seen_at=device.last_seen_at,
        online_status=device.online_status,
        source_type=device.source_type,
        rustdesk_raw_payload_json=device.rustdesk_raw_payload_json,
        created_at=device.created_at,
        updated_at=device.updated_at,
        companies=companies,
    )


@router.get("", response_model=list[DeviceOut])
def list_devices(
    q: Optional[str] = Query(None, description="Search nickname, rustdesk_id, hostname, notes"),
    company_id: Optional[int] = Query(None),
    source: Optional[str] = Query(None, pattern="^(imported|manual)$"),
    online: Optional[str] = Query(None, pattern="^(online|offline|unknown)$"),
    db: Session = Depends(get_db),
):
    stmt = select(Device).options(
        selectinload(Device.assignments).selectinload(DeviceCompanyAssignment.company)
    )
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Device.nickname.ilike(needle),
                Device.rustdesk_id.ilike(needle),
                Device.hostname.ilike(needle),
                Device.alias_from_rustdesk.ilike(needle),
                Device.notes.ilike(needle),
            )
        )
    if source:
        stmt = stmt.where(Device.source_type == source)
    if online == "online":
        stmt = stmt.where(Device.online_status == "online")
    elif online == "offline":
        stmt = stmt.where(Device.online_status == "offline")
    elif online == "unknown":
        stmt = stmt.where(Device.online_status.is_(None))
    if company_id is not None:
        stmt = stmt.join(
            DeviceCompanyAssignment, DeviceCompanyAssignment.device_id == Device.id
        ).where(DeviceCompanyAssignment.company_id == company_id)
    stmt = stmt.order_by(
        Device.nickname.asc().nullslast(), Device.rustdesk_id.asc().nullslast()
    )
    devices = db.execute(stmt).unique().scalars().all()
    return [_to_out(d) for d in devices]


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
def create_device(payload: DeviceCreate, db: Session = Depends(get_db)):
    rid = payload.rustdesk_id.strip() if payload.rustdesk_id else None
    if rid:
        existing = db.execute(
            select(Device).where(Device.rustdesk_id == rid)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409,
                detail="A device with this RustDesk ID already exists",
            )
    device = Device(
        rustdesk_id=rid,
        nickname=payload.nickname,
        hostname=payload.hostname,
        notes=payload.notes,
        source_type="manual",
    )
    db.add(device)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A device with this RustDesk ID already exists",
        )
    db.refresh(device)
    return _to_out(device)


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: int, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return _to_out(device)


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if payload.nickname is not None:
        device.nickname = payload.nickname
    if payload.hostname is not None:
        device.hostname = payload.hostname
    if payload.notes is not None:
        device.notes = payload.notes
    if payload.rustdesk_id is not None:
        rid = payload.rustdesk_id.strip() or None
        # Imported devices cannot have their rustdesk_id changed; the next
        # sync would re-create them. Only allow edits for manual devices.
        if device.source_type == "imported" and rid != device.rustdesk_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot change the RustDesk ID of an imported device",
            )
        device.rustdesk_id = rid
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A device with this RustDesk ID already exists",
        )
    db.refresh(device)
    return _to_out(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return None
