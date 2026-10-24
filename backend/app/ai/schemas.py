"""生成文の型。事実と解釈を欄ごとに分ける。

S / O（および FOCUS の Data / Action）に clinical_inference は置けない。
clinical_inference には derived_from が必須。検証そのものは M3。
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SourceType = Literal[
    "today_input",
    "historical_note",
    "patient_profile",
    "clinical_inference",
]

# 事実だけを書いてよい欄。解釈は A / P / Response / 経時記録本文。
_FACT_ONLY = {"today_input", "historical_note", "patient_profile"}
_WITH_INFERENCE = _FACT_ONLY | {"clinical_inference"}

SECTION_ALLOWED: dict[str, set[str]] = {
    "S": {"today_input"},
    "O": set(_FACT_ONLY),
    "A": set(_WITH_INFERENCE),
    "P": set(_WITH_INFERENCE),
    "Data": set(_FACT_ONLY),
    "Action": set(_FACT_ONLY),
    "Response": set(_WITH_INFERENCE),
    "N": set(_WITH_INFERENCE),
}

Section = Literal["S", "O", "A", "P", "Data", "Action", "Response", "N"]


class EvidenceItem(BaseModel):
    """生成文の一文と、生成器が申告した由来。"""

    text: str = Field(..., min_length=1)
    section: Section
    source_type: SourceType
    source_ref: str | None = None
    derived_from: list[str] = []

    @model_validator(mode="after")
    def check_section_rules(self) -> "EvidenceItem":
        allowed = SECTION_ALLOWED[self.section]
        if self.source_type not in allowed:
            raise ValueError(
                f"{self.section} 欄に {self.source_type} は書けません"
            )
        if self.source_type == "clinical_inference":
            if not self.derived_from:
                raise ValueError("臨床的解釈には derived_from が必要です")
        elif self.derived_from:
            raise ValueError("derived_from は臨床的解釈だけに付けます")
        return self


def _require_coverage(bodies: dict[str, str], evidence: list[EvidenceItem], sections: set[str]) -> None:
    """各根拠が宣言した欄の本文に含まれ、解釈が事実欄に混ざっていないこと。"""
    if any(bodies.values()) and not evidence:
        raise ValueError("本文があるのに根拠が空です")
    for item in evidence:
        if item.section not in sections:
            raise ValueError(f"この様式では欄 {item.section} は使えません")
        body = bodies.get(item.section) or ""
        if item.text not in body:
            raise ValueError(f"根拠の文が {item.section} 欄に見つかりません: {item.text}")
        if item.source_type == "clinical_inference":
            for fact_section, fact_body in bodies.items():
                if fact_section in ("S", "O", "Data", "Action") and item.text in (fact_body or ""):
                    raise ValueError(f"臨床的解釈が {fact_section} 欄に含まれています")


class SOAPNote(BaseModel):
    # 既定値を付けると JSON Schema 上は任意になり、ローカルモデルが本文を省く。
    subjective: str
    objective: str
    assessment: str
    plan: str
    evidence: list[EvidenceItem]

    @model_validator(mode="after")
    def evidence_matches_fields(self) -> "SOAPNote":
        _require_coverage(
            {
                "S": self.subjective,
                "O": self.objective,
                "A": self.assessment,
                "P": self.plan,
            },
            self.evidence,
            {"S", "O", "A", "P"},
        )
        return self


class FocusNote(BaseModel):
    data: str
    action: str
    response: str
    evidence: list[EvidenceItem]

    @model_validator(mode="after")
    def evidence_matches_fields(self) -> "FocusNote":
        _require_coverage(
            {"Data": self.data, "Action": self.action, "Response": self.response},
            self.evidence,
            {"Data", "Action", "Response"},
        )
        return self


class NarrativeNote(BaseModel):
    body: str
    evidence: list[EvidenceItem]

    @model_validator(mode="after")
    def evidence_matches_fields(self) -> "NarrativeNote":
        _require_coverage({"N": self.body}, self.evidence, {"N"})
        return self
