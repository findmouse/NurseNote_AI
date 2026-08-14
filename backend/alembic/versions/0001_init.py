"""初期スキーマ

Revision ID: 0001_init
Revises:
Create Date: 2026-08-11

"""
from typing import Sequence, Union, Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_init"
down_revision: Optional[str] = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # M3 以降のベクトル検索（記録事例の few-shot 検索・用語集 RAG）で使う
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---------------------------------------------------------- nurses
    op.create_table(
        "nurses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_no", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("name_kana", sa.String(length=64), nullable=True),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("ward", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nurses_employee_no", "nurses", ["employee_no"], unique=True)
    op.create_index("ix_nurses_ward", "nurses", ["ward"])

    # ---------------------------------------------------------- patients
    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_no", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("name_kana", sa.String(length=64), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.String(length=8), nullable=True),
        sa.Column("ward", sa.String(length=32), nullable=False),
        sa.Column("room", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_patients_patient_no", "patients", ["patient_no"], unique=True)
    op.create_index("ix_patients_name", "patients", ["name"])
    op.create_index("ix_patients_name_kana", "patients", ["name_kana"])
    op.create_index("ix_patients_ward", "patients", ["ward"])

    # ---------------------------------------------------------- admissions
    op.create_table(
        "admissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("admitted_at", sa.Date(), nullable=False),
        sa.Column("discharged_at", sa.Date(), nullable=True),
        sa.Column("diagnosis", sa.String(length=255), nullable=True),
        sa.Column("attending_doctor", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admissions_patient_id", "admissions", ["patient_id"])

    # ------------------------------------------------ admission_assessments
    op.create_table(
        "admission_assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admission_id", sa.Integer(), nullable=False),
        sa.Column("allergies", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "chronic_diseases", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("diet_restrictions", sa.Text(), nullable=True),
        sa.Column("past_history", sa.Text(), nullable=True),
        sa.Column("present_illness", sa.Text(), nullable=True),
        sa.Column("adl", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["admission_id"], ["admissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admission_assessments_admission_id",
        "admission_assessments",
        ["admission_id"],
        unique=True,
    )

    # ---------------------------------------------------------- nursing_notes
    op.create_table(
        "nursing_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admission_id", sa.Integer(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("shift", sa.String(length=8), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("vitals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "input_structured", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("input_free", sa.Text(), nullable=True),
        sa.Column("content_ai", sa.Text(), nullable=True),
        sa.Column("content_final", sa.Text(), nullable=True),
        sa.Column(
            "unsupported_spans", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["admission_id"], ["admissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["nurses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "admission_id", "record_date", "shift", name="uq_note_admission_date_shift"
        ),
    )
    op.create_index("ix_nursing_notes_admission_id", "nursing_notes", ["admission_id"])
    op.create_index("ix_nursing_notes_record_date", "nursing_notes", ["record_date"])
    op.create_index("ix_nursing_notes_author_id", "nursing_notes", ["author_id"])

    # ------------------------------------------------------ discharge_summaries
    op.create_table(
        "discharge_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admission_id", sa.Integer(), nullable=False),
        sa.Column("content_ai", sa.Text(), nullable=True),
        sa.Column("content_final", sa.Text(), nullable=True),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["admission_id"], ["admissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["nurses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discharge_summaries_admission_id", "discharge_summaries", ["admission_id"]
    )

    # ---------------------------------------------------------- audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["nurses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("discharge_summaries")
    op.drop_table("nursing_notes")
    op.drop_table("admission_assessments")
    op.drop_table("admissions")
    op.drop_table("patients")
    op.drop_table("nurses")
