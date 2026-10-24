"""看護記録の生成（SSE）と確定保存。

生成物は下書き。看護師が content_final を確認して確定するまで正式記録にしない。
"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.chain import run_chain
from app.ai.context import load_chain_input
from app.ai.llm import LLMConfigError, get_chat_model
from app.ai.schemas import EvidenceItem
from app.api.deps import ensure_ward_access, get_current_nurse
from app.db.session import AsyncSessionLocal, get_db
from app.models import Admission, AuditLog, Nurse, NursingNote
from app.schemas import NoteConfirmRequest, NoteGenerateRequest, NursingNoteOut

logger = logging.getLogger(__name__)
router = APIRouter()
JST = ZoneInfo("Asia/Tokyo")


def _today():
    return datetime.now(JST).date()


def _public_error(exc: Exception) -> str:
    text = str(exc).strip()
    name = type(exc).__name__
    if (
        name in {"ConnectError", "ConnectTimeout", "ConnectionError", "ReadTimeout"}
        or "Connection refused" in text
        or "All connection attempts failed" in text
    ):
        return (
            "LLM に接続できません。Ollama を起動するか、"
            "ALLOW_CLOUD_LLM=true と API キーを設定してください。"
        )
    if isinstance(exc, ValueError) and text:
        return text[:500]
    return "記録の生成に失敗しました"


def _sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def _active_admission(db: AsyncSession, patient_id: int) -> Admission:
    admission = await db.scalar(
        select(Admission).where(
            Admission.patient_id == patient_id,
            Admission.status == "active",
        )
    )
    if admission is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="この患者は現在入院していないため、看護記録の対象外です",
        )
    return admission


def _to_out(note: NursingNote, author_name: str | None) -> NursingNoteOut:
    out = NursingNoteOut.model_validate(note)
    out.author_name = author_name
    out.display_content = note.content_final or note.content_ai
    return out


@router.post("/generate", summary="看護記録の AI 生成（SSE）")
async def generate_note(
    payload: NoteGenerateRequest,
    request: Request,
    nurse: Nurse = Depends(get_current_nurse),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    admission = await _active_admission(db, payload.patient_id)
    ensure_ward_access(nurse, admission.ward)
    try:
        get_chat_model()
    except LLMConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    admission_id = admission.id
    nurse_id = nurse.id
    client_host = request.client.host if request.client else None

    async def events():
        async with AsyncSessionLocal() as session:
            try:
                yield _sse("status", {"phase": "retrieve"})
                current = await session.get(Admission, admission_id)
                if current is None:
                    yield _sse("error", {"detail": "入院が見つかりません"})
                    return
                ctx = await load_chain_input(
                    session,
                    current,
                    today=_today(),
                    shift=payload.shift,
                    note_format=payload.format,
                    vitals=payload.vitals,
                    checks=payload.checks,
                    free_text=payload.free_text,
                )
                yield _sse("status", {"phase": "generate"})
                generated = await run_chain(ctx)
                step = 40
                for index in range(0, len(generated.content), step):
                    yield _sse("delta", {"text": generated.content[index:index + step]})
                session.add(
                    AuditLog(
                        actor_id=nurse_id,
                        action="note.generate",
                        target_type="admission",
                        target_id=admission_id,
                        detail={
                            "shift": payload.shift,
                            "format": payload.format,
                            "model_name": generated.model_name,
                            "prompt_version": generated.prompt_version,
                        },
                        ip_address=client_host,
                    )
                )
                await session.commit()
                yield _sse(
                    "done",
                    {
                        "content": generated.content,
                        "evidence": generated.evidence,
                        "model_name": generated.model_name,
                        "prompt_version": generated.prompt_version,
                        "token_usage": generated.token_usage,
                    },
                )
            except LLMConfigError as exc:
                yield _sse("error", {"detail": str(exc)})
            except Exception as exc:  # noqa: BLE001
                logger.exception("note generation failed")
                yield _sse("error", {"detail": _public_error(exc)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_model=NursingNoteOut, summary="看護記録の確定保存")
async def confirm_note(
    payload: NoteConfirmRequest,
    request: Request,
    nurse: Nurse = Depends(get_current_nurse),
    db: AsyncSession = Depends(get_db),
) -> NursingNoteOut:
    admission = await _active_admission(db, payload.patient_id)
    ensure_ward_access(nurse, admission.ward)

    evidence: list[dict] = []
    for item in payload.evidence:
        try:
            evidence.append(EvidenceItem.model_validate(item).model_dump())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"根拠の形式が不正です: {exc}",
            ) from exc

    final = payload.content_final.strip()
    if not final:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="本文が空です"
        )

    today = _today()
    note = await db.scalar(
        select(NursingNote).where(
            NursingNote.admission_id == admission.id,
            NursingNote.record_date == today,
            NursingNote.shift == payload.shift,
        )
    )
    if note is None:
        note = NursingNote(
            admission_id=admission.id,
            record_date=today,
            shift=payload.shift,
        )
        db.add(note)

    note.format = payload.format
    note.vitals = payload.vitals
    note.input_structured = {"checks": payload.checks}
    note.input_free = (payload.free_text or "").strip() or None
    if payload.content_ai.strip():
        note.content_ai = payload.content_ai
    note.content_final = final
    note.evidence_spans = evidence
    note.status = "confirmed"
    note.author_id = nurse.id
    note.confirmed_at = datetime.now(JST)
    note.model_name = payload.model_name
    note.prompt_version = payload.prompt_version
    note.verification = None
    if payload.token_usage is not None:
        note.token_usage = payload.token_usage

    await db.flush()
    db.add(
        AuditLog(
            actor_id=nurse.id,
            action="note.confirm",
            target_type="nursing_note",
            target_id=note.id,
            detail={
                "admission_id": admission.id,
                "shift": payload.shift,
                "format": payload.format,
                "model_name": payload.model_name,
                "prompt_version": payload.prompt_version,
            },
            ip_address=request.client.host if request.client else None,
        )
    )
    await db.commit()
    await db.refresh(note)
    return _to_out(note, nurse.name)


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
    return _to_out(note, note.author.name if note.author else None)
