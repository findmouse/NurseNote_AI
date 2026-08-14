"""看護記録の単票取得

生成 (POST /notes/generate) と確定保存 (POST /notes) は M2 で実装する。
M1 ではフロントの導線確認用にスタブだけ用意しておく。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ensure_ward_access, get_current_nurse
from app.db.session import get_db
from app.models import Admission, NursingNote, Nurse
from app.schemas import NursingNoteOut

router = APIRouter()


@router.get("/{note_id}", response_model=NursingNoteOut, summary="看護記録の単票取得")
async def get_note(
    note_id: int,
    nurse: Nurse = Depends(get_current_nurse),
    db: AsyncSession = Depends(get_db),
) -> NursingNoteOut:
    note = await db.scalar(
        select(NursingNote)
        .options(selectinload(NursingNote.author))
        .where(NursingNote.id == note_id)
    )
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="記録が見つかりません"
        )

    admission = await db.get(Admission, note.admission_id)
    ensure_ward_access(nurse, admission.ward if admission else None)

    out = NursingNoteOut.model_validate(note)
    out.author_name = note.author.name if note.author else None
    out.display_content = note.content_final or note.content_ai
    return out


@router.post(
    "/generate",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="看護記録の AI 生成（M2 で実装）",
)
async def generate_note(nurse: Nurse = Depends(get_current_nurse)) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="記録生成は M2 で実装予定です（LangChain LCEL + ストリーミング）",
    )
