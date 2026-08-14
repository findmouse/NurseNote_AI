"""根拠情報のカラムを unsupported_spans から evidence_spans / verification へ

当初は「根拠のない記述」だけを記録する設計だったが、
生成文の各記述を次の 4 種類に分類する設計に変更したため、
「不支持のもの」だけを入れる名前では実態と合わなくなった。

  ① today_input        直接事実（本日の入力）
  ② historical_note    歴史事実（過去の記録）
  ②' patient_profile   患者背景（入院時基礎情報）
  ③ clinical_inference 臨床的解釈（①②から導いた推論）

さらに「生成器が申告した根拠（evidence_spans）」と
「検証器が下した裁定（verification）」は別物なので、カラムを分ける。

Revision ID: 0003_evidence_spans
Revises: 0002_ward_to_admission
Create Date: 2026-08-11

"""
from typing import Sequence, Union, Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_evidence_spans"
down_revision: Optional[str] = "0002_ward_to_admission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 生成器の申告（M2 で埋まる）
    op.alter_column(
        "nursing_notes", "unsupported_spans", new_column_name="evidence_spans"
    )
    # 検証器の裁定（M3 で埋まる）
    op.add_column(
        "nursing_notes",
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nursing_notes", "verification")
    op.alter_column(
        "nursing_notes", "evidence_spans", new_column_name="unsupported_spans"
    )
