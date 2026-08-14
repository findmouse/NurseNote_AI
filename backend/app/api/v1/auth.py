"""ログイン / ログイン中ユーザー取得"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_nurse
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models import AuditLog, Nurse
from app.schemas import LoginRequest, LoginResponse, NurseOut

router = APIRouter()


@router.post("/login", response_model=LoginResponse, summary="看護師ログイン")
async def login(
        payload: LoginRequest,
        request: Request,
        db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    nurse = await db.scalar(
        select(Nurse).where(Nurse.employee_no == payload.employee_no)
    )
    if nurse is None or not verify_password(payload.password, nurse.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="職員番号またはパスワードが正しくありません",
        )
    if not nurse.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="このアカウントは無効です"
        )

    token = create_access_token(
        subject=str(nurse.id),
        extra_claims={"employee_no": nurse.employee_no, "ward": nurse.ward,
                      "role": nurse.role},
    )

    db.add(
        AuditLog(
            actor_id=nurse.id,
            action="auth.login",
            target_type="nurse",
            target_id=nurse.id,
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()

    return LoginResponse(access_token=token, nurse=NurseOut.model_validate(nurse))


@router.get("/me", response_model=NurseOut, summary="ログイン中の看護師情報")
async def me(nurse: Nurse = Depends(get_current_nurse)) -> NurseOut:
    return NurseOut.model_validate(nurse)
