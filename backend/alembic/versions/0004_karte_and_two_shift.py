"""カルテ番号への改名と、看護記録の二交代制約

patient_no は診察券番号という呼び方だったが、入院でも外来でも付く
病院内の患者識別番号なので karte_no（カルテ番号）に改名する。

看護記録は二交代（日勤 / 夜勤）。同じ日に勤務帯ごとに 1 件、計 2 件。
shift をその 2 値に制限する。

Revision ID: 0004_karte_and_two_shift
Revises: 0003_evidence_spans
Create Date: 2026-10-24

"""
from typing import Sequence, Union, Optional

from alembic import op

revision: str = "0004_karte_and_two_shift"
down_revision: Optional[str] = "0003_evidence_spans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("patients", "patient_no", new_column_name="karte_no")
    op.execute("ALTER INDEX ix_patients_patient_no RENAME TO ix_patients_karte_no")
    op.create_check_constraint(
        "ck_nursing_notes_shift",
        "nursing_notes",
        "shift IN ('日勤', '夜勤')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_nursing_notes_shift", "nursing_notes", type_="check")
    op.execute("ALTER INDEX ix_patients_karte_no RENAME TO ix_patients_patient_no")
    op.alter_column("patients", "karte_no", new_column_name="patient_no")
