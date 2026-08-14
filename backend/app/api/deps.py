"""共通の依存性（認証・権限チェック）"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Nurse

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_nurse(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Nurse:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証情報がありません",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if payload is None or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンが無効か、有効期限が切れています",
            headers={"WWW-Authenticate": "Bearer"},
        )

    nurse = await db.scalar(select(Nurse).where(Nurse.id == int(payload["sub"])))
    if nurse is None or not nurse.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="ユーザーが存在しません"
        )
    return nurse


def ensure_ward_access(nurse: Nurse, ward: str | None) -> None:
    """所属病棟以外へのアクセスを拒否する（admin は全病棟可）

    ward が None の場合（未入院の患者など）は病棟に紐づかないため許可する。
    入院登録の前段では、まだどの病棟の患者でもないため検索できる必要がある。
    """
    if nurse.role == "admin" or ward is None:
        return
    if ward != nurse.ward:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="担当病棟外の患者情報にはアクセスできません",
        )
