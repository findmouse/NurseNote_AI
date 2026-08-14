"""病棟・病室を patients から admissions へ移動

病棟は「患者の属性」ではなく「その入院の属性」である。
同一患者が入院ごとに異なる病棟に入ることも、入院中の転棟もあるため、
admissions 側に持たせるのが正しい。未入院の患者は病棟を持たない。

Revision ID: 0002_ward_to_admission
Revises: 0001_init
Create Date: 2026-08-11

"""
from typing import Sequence, Union, Optional

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ward_to_admission"
down_revision: Optional[str] = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) admissions に列を追加（既存行のためいったん NULL 許容）
    op.add_column("admissions", sa.Column("ward", sa.String(length=32), nullable=True))
    op.add_column("admissions", sa.Column("room", sa.String(length=16), nullable=True))

    # 2) 既存データを patients から移送
    op.execute(
        """
        UPDATE admissions AS a
        SET ward = p.ward, room = p.room
        FROM patients AS p
        WHERE a.patient_id = p.id
        """
    )

    # 3) 万一 NULL が残っていた場合の保険
    op.execute("UPDATE admissions SET ward = '未設定' WHERE ward IS NULL")

    # 4) NOT NULL 化 + インデックス
    op.alter_column("admissions", "ward", nullable=False)
    op.create_index("ix_admissions_ward", "admissions", ["ward"])
    op.create_index("ix_admissions_status", "admissions", ["status"])

    # 5) patients から削除
    op.drop_index("ix_patients_ward", table_name="patients")
    op.drop_column("patients", "ward")
    op.drop_column("patients", "room")


def downgrade() -> None:
    """⚠ この downgrade は非可逆（データが欠落する）

    patients は病棟を 1 つしか持てないため、入院中の入院からしか値を戻せない。
    退院済みの入院や、複数回入院した患者の過去分の病棟は '未設定' になる。
    スキーマ設計としてこちらが誤りであることの裏返しであり、
    downgrade は緊急時のロールバック用途に限る。
    """
    op.add_column("patients", sa.Column("ward", sa.String(length=32), nullable=True))
    op.add_column("patients", sa.Column("room", sa.String(length=16), nullable=True))
    op.execute(
        """
        UPDATE patients AS p
        SET ward = a.ward, room = a.room
        FROM admissions AS a
        WHERE a.patient_id = p.id AND a.status = 'active'
        """
    )
    op.execute("UPDATE patients SET ward = '未設定' WHERE ward IS NULL")
    op.alter_column("patients", "ward", nullable=False)
    op.create_index("ix_patients_ward", "patients", ["ward"])

    op.drop_index("ix_admissions_status", table_name="admissions")
    op.drop_index("ix_admissions_ward", table_name="admissions")
    op.drop_column("admissions", "room")
    op.drop_column("admissions", "ward")
