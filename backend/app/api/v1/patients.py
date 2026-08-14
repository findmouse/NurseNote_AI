"""患者検索・患者詳細・過去の看護記録一覧・患者マスタ登録

検索は 2 種類ある。用途がまったく違うので scope で切り替える。

  scope=admitted （既定）… 担当病棟に「現在入院中」の患者だけ。日々の看護記録の対象。
  scope=all            … 患者マスタ全体（未入院・退院済を含む）。新規入院登録の前段で、
                          「まだどの病棟にも属していない患者」を探すために使う。
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ensure_ward_access, get_current_nurse
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    Admission,
    AdmissionAssessment,
    AuditLog,
    Nurse,
    NursingNote,
    Patient,
)
from app.schemas import (
    AdmissionOut,
    AssessmentOut,
    NoteListResponse,
    NursingNoteOut,
    PatientCreate,
    PatientDetail,
    PatientListItem,
)
from app.utils import calc_age

router = APIRouter()


# --------------------------------------------------------------------------- 補助


async def _latest_admission(db: AsyncSession, patient_id: int) -> Admission | None:
    """入院中のものを優先し、無ければ直近の入院を返す。入院歴が無ければ None。"""
    return await db.scalar(
        select(Admission)
        .where(Admission.patient_id == patient_id)
        .order_by(
            (Admission.status == "active").desc(),
            Admission.admitted_at.desc(),
            Admission.id.desc(),
        )
        .limit(1)
    )


def _admission_status(adm: Admission | None) -> str:
    if adm is None:
        return "never"
    return "admitted" if adm.status == "active" else "discharged"


async def _get_patient_or_404(db: AsyncSession, patient_id: int) -> Patient:
    patient = await db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="患者が見つかりません"
        )
    return patient


def _to_list_item(patient: Patient, adm: Admission | None) -> PatientListItem:
    item = PatientListItem.model_validate(patient)
    item.age = calc_age(patient.birth_date)
    item.admission_status = _admission_status(adm)
    item.current_admission = AdmissionOut.model_validate(adm) if adm else None
    return item


async def _next_patient_no(db: AsyncSession) -> str:
    """P00001 形式の連番を採番する（デモ用の簡易実装）"""
    last = await db.scalar(
        select(Patient.patient_no)
        .where(Patient.patient_no.op("~")("^P[0-9]+$"))
        .order_by(Patient.id.desc())
        .limit(1)
    )
    seq = int(last[1:]) + 1 if last else 1
    while True:
        candidate = f"P{seq:05d}"
        exists = await db.scalar(
            select(Patient.id).where(Patient.patient_no == candidate)
        )
        if exists is None:
            return candidate
        seq += 1


# --------------------------------------------------------------------------- 検索


@router.get("", response_model=list[PatientListItem], summary="患者検索")
async def search_patients(
        q: str | None = Query(None, description="氏名・カナ・患者番号の部分一致"),
        scope: str = Query(
            "admitted",
            pattern="^(admitted|all)$",
            description="admitted=担当病棟の入院中のみ / all=患者マスタ全体（入院登録用）",
        ),
        limit: int = Query(50, ge=1, le=200),
        nurse: Nurse = Depends(get_current_nurse),
        db: AsyncSession = Depends(get_db),
) -> list[PatientListItem]:
    keyword = (q or "").strip()
    like = f"%{keyword}%"
    name_filter = or_(
        Patient.name.ilike(like),
        Patient.name_kana.ilike(like),
        Patient.patient_no.ilike(like),
    )

    # ---- 入院中のみ（主画面）----
    if scope == "admitted":
        stmt = (
            select(Patient, Admission)
            .join(Admission, Admission.patient_id == Patient.id)
            .where(Admission.status == "active")
        )
        if nurse.role != "admin":
            stmt = stmt.where(Admission.ward == nurse.ward)
        if keyword:
            stmt = stmt.where(name_filter)
        stmt = stmt.order_by(Admission.ward, Admission.room, Patient.id).limit(limit)

        rows = (await db.execute(stmt)).all()
        return [_to_list_item(patient, adm) for patient, adm in rows]

    # ---- 患者マスタ全体（入院登録用）----
    # 全件返すと患者マスタの一覧表示になってしまうため、検索語を必須にする
    if not keyword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="患者マスタ検索では検索語（氏名・カナ・患者番号）が必要です",
        )

    patients = (
        await db.scalars(
            select(Patient).where(name_filter).order_by(Patient.id).limit(limit)
        )
    ).all()

    result: list[PatientListItem] = []
    for p in patients:
        adm = await _latest_admission(db, p.id)
        result.append(_to_list_item(p, adm))
    return result


# --------------------------------------------------------------------------- 登録


@router.post(
    "",
    response_model=PatientListItem,
    status_code=status.HTTP_201_CREATED,
    summary="患者マスタへの新規登録",
)
async def create_patient(
        payload: PatientCreate,
        request: Request,
        nurse: Nurse = Depends(get_current_nurse),
        db: AsyncSession = Depends(get_db),
) -> PatientListItem:
    patient_no = (payload.patient_no or "").strip() or await _next_patient_no(db)

    duplicate = await db.scalar(
        select(Patient.id).where(Patient.patient_no == patient_no)
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"患者番号 {patient_no} は既に登録されています",
        )

    patient = Patient(
        patient_no=patient_no,
        name=payload.name.strip(),
        name_kana=(payload.name_kana or "").strip() or None,
        birth_date=payload.birth_date,
        sex=payload.sex,
    )
    db.add(patient)
    await db.flush()

    db.add(
        AuditLog(
            actor_id=nurse.id,
            action="patient.create",
            target_type="patient",
            target_id=patient.id,
            detail={"patient_no": patient_no, "name": patient.name},
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()
    await db.refresh(patient)

    return _to_list_item(patient, None)


# --------------------------------------------------------------------------- 詳細


@router.get("/{patient_id}", response_model=PatientDetail, summary="患者詳細")
async def get_patient(
        patient_id: int,
        nurse: Nurse = Depends(get_current_nurse),
        db: AsyncSession = Depends(get_db),
) -> PatientDetail:
    patient = await _get_patient_or_404(db, patient_id)

    adm = await _latest_admission(db, patient.id)
    # 未入院（adm is None）の患者は病棟に紐づかないため、入院登録のために参照を許可する
    ensure_ward_access(nurse, adm.ward if adm else None)

    assessment = None
    if adm is not None:
        assessment = await db.scalar(
            select(AdmissionAssessment).where(
                AdmissionAssessment.admission_id == adm.id
            )
        )

    detail = PatientDetail.model_validate(patient)
    detail.age = calc_age(patient.birth_date)
    detail.admission_status = _admission_status(adm)
    detail.current_admission = AdmissionOut.model_validate(adm) if adm else None
    detail.assessment = AssessmentOut.model_validate(assessment) if assessment else None
    return detail


# --------------------------------------------------------------------------- 記録


@router.get(
    "/{patient_id}/notes",
    response_model=NoteListResponse,
    summary="直近 N 日分の看護記録",
)
async def list_patient_notes(
        patient_id: int,
        days: int = Query(settings.default_recent_days, ge=1, le=90),
        nurse: Nurse = Depends(get_current_nurse),
        db: AsyncSession = Depends(get_db),
) -> NoteListResponse:
    patient = await _get_patient_or_404(db, patient_id)

    adm = await _latest_admission(db, patient.id)
    ensure_ward_access(nurse, adm.ward if adm else None)

    if adm is None:
        return NoteListResponse(
            admission_id=None, admission_status="never", days=days, items=[]
        )

    adm_status = _admission_status(adm)

    # 「今日から N 日前まで」ではなく「記録が存在する最新日から N 日分」を返す。
    # 休日やデモデータで記録が飛んでいても直近の記録が確実に表示されるため。
    latest_date = await db.scalar(
        select(NursingNote.record_date)
        .where(NursingNote.admission_id == adm.id)
        .order_by(NursingNote.record_date.desc())
        .limit(1)
    )
    if latest_date is None:
        return NoteListResponse(
            admission_id=adm.id, admission_status=adm_status, days=days, items=[]
        )

    since: date = latest_date - timedelta(days=days - 1)

    notes = (
        await db.scalars(
            select(NursingNote)
            .options(selectinload(NursingNote.author))
            .where(
                NursingNote.admission_id == adm.id,
                NursingNote.record_date >= since,
            )
            .order_by(NursingNote.record_date.desc(), NursingNote.id.desc())
        )
    ).all()

    items = []
    for n in notes:
        out = NursingNoteOut.model_validate(n)
        out.author_name = n.author.name if n.author else None
        out.display_content = n.content_final or n.content_ai
        items.append(out)

    return NoteListResponse(
        admission_id=adm.id, admission_status=adm_status, days=days, items=items
    )
