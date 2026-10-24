"""ORM モデル定義

M1 の時点で M4 までに必要なテーブルを一括で定義しておく。
AI 生成に関わるカラム（content_ai / evidence_spans / prompt_version など）は
M2 以降で埋まるが、スキーマ変更を減らすためここで用意しておく。
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# 二交代。1 日に日勤・夜勤の 2 件。三交代（準夜・深夜）は扱わない。
SHIFT_DAY = "日勤"
SHIFT_NIGHT = "夜勤"
SHIFTS = (SHIFT_DAY, SHIFT_NIGHT)

# ---------------------------------------------------------------- 看護師


class Nurse(Base):
    """看護師（ログインユーザー）"""

    __tablename__ = "nurses"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    name_kana: Mapped[str | None] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    ward: Mapped[str] = mapped_column(String(32), index=True)  # 所属病棟
    role: Mapped[str] = mapped_column(String(16), default="nurse")  # nurse / admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------- 患者


class Patient(Base):
    """患者マスタ

    カルテ番号は入院・外来を問わず、その病院で患者を識別する番号。
    入院レコードには持たせず、患者マスタに 1 人 1 つ置く。
    外来受診だけの患者も、まだ入院していない患者も、同じ番号を持つ。

    病棟・病室は「どの入院でどこにいたか」なので admissions 側に置く。
    未入院の患者は病棟を持たない。
    """

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    karte_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    name_kana: Mapped[str | None] = mapped_column(String(64), index=True)
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(8))  # 男性 / 女性 / その他
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    admissions: Mapped[list["Admission"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )


class Admission(Base):
    """入院（1 患者に複数回ありうる）"""

    __tablename__ = "admissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    admitted_at: Mapped[date] = mapped_column(Date)
    discharged_at: Mapped[date | None] = mapped_column(Date)
    ward: Mapped[str] = mapped_column(String(32), index=True)  # 入院先の病棟
    room: Mapped[str | None] = mapped_column(String(16))  # 病室
    diagnosis: Mapped[str | None] = mapped_column(String(255))  # 診断名
    attending_doctor: Mapped[str | None] = mapped_column(String(64))  # 主治医
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / discharged
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    patient: Mapped["Patient"] = relationship(back_populates="admissions")
    assessment: Mapped["AdmissionAssessment | None"] = relationship(
        back_populates="admission", cascade="all, delete-orphan", uselist=False
    )
    notes: Mapped[list["NursingNote"]] = relationship(
        back_populates="admission", cascade="all, delete-orphan"
    )


class AdmissionAssessment(Base):
    """入院時基礎情報（問診票 / アナムネ）— M4 で入力 UI を実装"""

    __tablename__ = "admission_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    admission_id: Mapped[int] = mapped_column(
        ForeignKey("admissions.id", ondelete="CASCADE"), unique=True, index=True
    )
    allergies: Mapped[list | None] = mapped_column(JSONB)  # ["ペニシリン", "卵"]
    chronic_diseases: Mapped[list | None] = mapped_column(JSONB)  # ["高血圧", "2型糖尿病"]
    diet_restrictions: Mapped[str | None] = mapped_column(Text)  # 食事禁忌
    past_history: Mapped[str | None] = mapped_column(Text)  # 既往歴
    present_illness: Mapped[str | None] = mapped_column(Text)  # 現病歴
    adl: Mapped[dict | None] = mapped_column(JSONB)  # {"移動": "歩行器", "食事": "自立"}
    remarks: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    admission: Mapped["Admission"] = relationship(back_populates="assessment")


# ---------------------------------------------------------------- 看護記録


class NursingNote(Base):
    """日々の看護記録

    二交代のため、同じ入院・同じ日でも日勤と夜勤で 1 件ずつ、計 2 件になる。
    input_* が看護師の入力、content_ai が AI 生成結果、content_final が
    看護師が確認・修正して確定した最終版。記録責任は看護師にあるため、
    status = confirmed になるまでは正式な記録として扱わない。
    """

    __tablename__ = "nursing_notes"
    __table_args__ = (
        UniqueConstraint(
            "admission_id", "record_date", "shift", name="uq_note_admission_date_shift"
        ),
        CheckConstraint(
            "shift IN ('日勤', '夜勤')", name="ck_nursing_notes_shift"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    admission_id: Mapped[int] = mapped_column(
        ForeignKey("admissions.id", ondelete="CASCADE"), index=True
    )
    record_date: Mapped[date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(8), default=SHIFT_DAY)
    format: Mapped[str] = mapped_column(String(16), default="SOAP")  # SOAP / FOCUS / NARRATIVE

    # --- 看護師の入力 ---
    vitals: Mapped[dict | None] = mapped_column(JSONB)  # {"bt":36.8,"bp":"128/76",...}
    input_structured: Mapped[dict | None] = mapped_column(JSONB)  # チェックボックス選択
    input_free: Mapped[str | None] = mapped_column(Text)  # 自由記述

    # --- AI 生成結果（M2 以降） ---
    content_ai: Mapped[str | None] = mapped_column(Text)
    content_final: Mapped[str | None] = mapped_column(Text)
    # 生成文の各記述と、その根拠の対応表（EvidenceItem の配列）。
    # 「根拠なし箇所」だけでなく、直接事実・歴史事実・臨床的解釈もすべて記録する。
    evidence_spans: Mapped[list | None] = mapped_column(JSONB)  # 生成器の申告（M2）
    verification: Mapped[list | None] = mapped_column(JSONB)  # 検証器の裁定（M3）

    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft / confirmed
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("nurses.id", ondelete="SET NULL"), index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- トレーサビリティ ---
    model_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    token_usage: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    admission: Mapped["Admission"] = relationship(back_populates="notes")
    author: Mapped["Nurse | None"] = relationship()


class DischargeSummary(Base):
    """退院サマリー — M4 で実装"""

    __tablename__ = "discharge_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    admission_id: Mapped[int] = mapped_column(
        ForeignKey("admissions.id", ondelete="CASCADE"), index=True
    )
    content_ai: Mapped[str | None] = mapped_column(Text)
    content_final: Mapped[str | None] = mapped_column(Text)
    sections: Mapped[dict | None] = mapped_column(JSONB)  # 構造化出力の生データ
    status: Mapped[str] = mapped_column(String(16), default="draft")
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("nurses.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------- 監査


class AuditLog(Base):
    """監査ログ（誰が・いつ・何をしたか）"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("nurses.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)  # login / note.generate ...
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
