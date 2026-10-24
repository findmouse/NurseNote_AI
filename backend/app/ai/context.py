"""外部 LLM に渡してよい情報だけを組み立てる。

許可リスト方式。ここに無い項目（氏名、カルテ番号、生年月日、病棟、暦の日付、
記載者名）はプロンプトに入れない。自由記述の固有表現検出は M3。
"""
from datetime import date, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.schemas import EvidenceItem
from app.models import Admission, NursingNote
from app.utils import calc_age

RECENT_DAYS = 7


class LLMPatientContext(BaseModel):
    """外部 LLM へ渡してよい患者背景。フィールド追加はレビュー対象。"""

    age_band: str
    sex: str | None = None
    diagnosis: str | None = None
    hospital_day: int
    post_op_day: int | None = None
    allergies: list[str] = []
    chronic_diseases: list[str] = []
    diet_restrictions: str | None = None


class LLMRecentNote(BaseModel):
    ref: str
    when: str
    text: str


class LLMToday(BaseModel):
    shift: str
    checks: list[str] = []
    free_text: str = ""


class ChainInput(BaseModel):
    patient: LLMPatientContext
    recent_notes: list[LLMRecentNote]
    today: LLMToday
    vital_line: str
    format: str


def age_band(birth: date | None, on: date) -> str:
    age = calc_age(birth, on)
    if age is None:
        return "不明"
    if age < 10:
        return "10歳未満"
    return f"{(age // 10) * 10}代"


def relative_when(note_date: date, today: date, shift: str) -> str:
    delta = (today - note_date).days
    if delta <= 0:
        day = "当日"
    elif delta == 1:
        day = "1日前"
    else:
        day = f"{delta}日前"
    return f"{day}・{shift}"


def build_vital_line(vitals: dict | None) -> str:
    """バイタルは LLM に作らせず、入力値をそのまま文にする。"""
    if not vitals:
        return ""
    labels = (
        ("bt", "体温", "℃"),
        ("bp", "血圧", "mmHg"),
        ("hr", "脈拍", "回/分"),
        ("spo2", "SpO2 ", "%"),
        ("rr", "呼吸数", "回/分"),
    )
    parts: list[str] = []
    for key, label, unit in labels:
        raw = vitals.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        parts.append(f"{label}{text}{unit}")
    if not parts:
        return ""
    return "、".join(parts) + "。"


def vital_evidence(vital_line: str, section: str) -> EvidenceItem | None:
    if not vital_line:
        return None
    return EvidenceItem(
        text=vital_line,
        section=section,  # type: ignore[arg-type]
        source_type="today_input",
        source_ref="vitals",
    )


async def load_chain_input(
    db: AsyncSession,
    admission: Admission,
    *,
    today: date,
    shift: str,
    note_format: str,
    vitals: dict | None,
    checks: list[str],
    free_text: str | None,
) -> ChainInput:
    admission = await db.scalar(
        select(Admission)
        .options(
            selectinload(Admission.patient),
            selectinload(Admission.assessment),
        )
        .where(Admission.id == admission.id)
    )
    if admission is None:
        raise ValueError("入院が見つかりません")

    patient = admission.patient
    assessment = admission.assessment
    since = today - timedelta(days=RECENT_DAYS - 1)
    notes = (
        await db.scalars(
            select(NursingNote)
            .where(
                NursingNote.admission_id == admission.id,
                NursingNote.record_date >= since,
                NursingNote.record_date <= today,
            )
            .order_by(NursingNote.record_date.asc(), NursingNote.id.asc())
        )
    ).all()

    recent: list[LLMRecentNote] = []
    for note in notes:
        # いま書いている勤務帯の下書きは参照元にしない
        if note.record_date == today and note.shift == shift and note.status != "confirmed":
            continue
        text = (note.content_final or note.content_ai or "").strip()
        if not text:
            continue
        recent.append(
            LLMRecentNote(
                ref=f"note:{note.id}",
                when=relative_when(note.record_date, today, note.shift),
                text=text,
            )
        )

    allergies = list(assessment.allergies or []) if assessment else []
    chronic = list(assessment.chronic_diseases or []) if assessment else []
    diet = assessment.diet_restrictions if assessment else None

    return ChainInput(
        patient=LLMPatientContext(
            age_band=age_band(patient.birth_date, today),
            sex=patient.sex,
            diagnosis=admission.diagnosis,
            hospital_day=(today - admission.admitted_at).days + 1,
            allergies=allergies,
            chronic_diseases=chronic,
            diet_restrictions=diet,
        ),
        recent_notes=recent,
        today=LLMToday(
            shift=shift,
            checks=checks,
            free_text=(free_text or "").strip(),
        ),
        vital_line=build_vital_line(vitals),
        format=note_format,
    )
