"""新規入院登録・退院処理

入院していない患者は看護記録の対象にならない。
逆に、退院処理をしないと患者が担当一覧に残り続ける。
この 2 つは対になる操作なので同じルーターに置く。
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_ward_access, get_current_nurse
from app.db.session import get_db
from app.models import Admission, AuditLog, Nurse, Patient
from app.schemas import AdmissionCreate, AdmissionOut, DischargeRequest

router = APIRouter()


@router.post(
    "",
    response_model=AdmissionOut,
    status_code=status.HTTP_201_CREATED,
    summary="新規入院登録",
)
async def create_admission(
    payload: AdmissionCreate,
    request: Request,
    nurse: Nurse = Depends(get_current_nurse),
    db: AsyncSession = Depends(get_db),
) -> AdmissionOut:
    patient = await db.get(Patient, payload.patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="患者が見つかりません"
        )

    # 既に入院中なら二重入院になるので拒否する
    active = await db.scalar(
        select(Admission).where(
            Admission.patient_id == patient.id, Admission.status == "active"
        )
    )
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{patient.name} さんは既に入院中です"
                f"（{active.ward} / 入院日 {active.admitted_at}）"
            ),
        )

    ward = (payload.ward or nurse.ward).strip()
    # 自分の担当病棟以外への入院登録は認めない（admin は除く）
    ensure_ward_access(nurse, ward)

    admitted_at = payload.admitted_at or date.today()
    if admitted_at > date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="入院日に未来の日付は指定できません",
        )

    admission = Admission(
        patient_id=patient.id,
        admitted_at=admitted_at,
        ward=ward,
        room=(payload.room or "").strip() or None,
        diagnosis=(payload.diagnosis or "").strip() or None,
        attending_doctor=(payload.attending_doctor or "").strip() or None,
        status="active",
    )
    db.add(admission)
    await db.flush()

    db.add(
        AuditLog(
            actor_id=nurse.id,
            action="admission.create",
            target_type="admission",
            target_id=admission.id,
            detail={
                "patient_no": patient.patient_no,
                "patient_name": patient.name,
                "ward": ward,
                "admitted_at": admitted_at.isoformat(),
            },
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()
    await db.refresh(admission)

    return AdmissionOut.model_validate(admission)


@router.post(
    "/{admission_id}/discharge", response_model=AdmissionOut, summary="退院処理"
)
async def discharge(
    admission_id: int,
    payload: DischargeRequest,
    request: Request,
    nurse: Nurse = Depends(get_current_nurse),
    db: AsyncSession = Depends(get_db),
) -> AdmissionOut:
    admission = await db.get(Admission, admission_id)
    if admission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="入院情報が見つかりません"
        )

    ensure_ward_access(nurse, admission.ward)

    if admission.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"この入院は既に退院済みです（退院日 {admission.discharged_at}）",
        )

    discharged_at = payload.discharged_at or date.today()
    if discharged_at < admission.admitted_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="退院日は入院日より前にはできません",
        )

    admission.discharged_at = discharged_at
    admission.status = "discharged"

    db.add(
        AuditLog(
            actor_id=nurse.id,
            action="admission.discharge",
            target_type="admission",
            target_id=admission.id,
            detail={"discharged_at": discharged_at.isoformat()},
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()
    await db.refresh(admission)

    return AdmissionOut.model_validate(admission)
