"""API のリクエスト / レスポンススキーマ"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- 認証


class LoginRequest(BaseModel):
    employee_no: str = Field(..., examples=["N001"])
    password: str = Field(..., examples=["nurse1234"])


class NurseOut(ORMBase):
    id: int
    employee_no: str
    name: str
    name_kana: str | None = None
    ward: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    nurse: NurseOut


# ---------------------------------------------------------------- 入院


class AdmissionOut(ORMBase):
    id: int
    admitted_at: date
    discharged_at: date | None = None
    ward: str
    room: str | None = None
    diagnosis: str | None = None
    attending_doctor: str | None = None
    status: str


class AdmissionCreate(BaseModel):
    """新規入院登録"""

    patient_id: int
    admitted_at: date | None = Field(None, description="省略時は本日")
    ward: str | None = Field(None, description="省略時はログイン看護師の所属病棟")
    room: str | None = Field(None, examples=["305"])
    diagnosis: str | None = Field(None, examples=["右大腿骨頸部骨折"])
    attending_doctor: str | None = Field(None, examples=["整形外科　大西 医師"])


class DischargeRequest(BaseModel):
    discharged_at: date | None = Field(None, description="省略時は本日")


# ---------------------------------------------------------------- 患者


class PatientCreate(BaseModel):
    """患者マスタへの新規登録（初診・新規入院時）"""

    name: str = Field(..., examples=["山口 一郎"])
    name_kana: str | None = Field(None, examples=["ヤマグチ イチロウ"])
    birth_date: date | None = None
    sex: str | None = Field(None, examples=["男性"])
    patient_no: str | None = Field(None, description="省略時は自動採番")


class AssessmentOut(ORMBase):
    allergies: list | None = None
    chronic_diseases: list | None = None
    diet_restrictions: str | None = None
    past_history: str | None = None
    present_illness: str | None = None
    adl: dict | None = None
    remarks: str | None = None


class PatientOut(ORMBase):
    id: int
    patient_no: str
    name: str
    name_kana: str | None = None
    birth_date: date | None = None
    age: int | None = None
    sex: str | None = None


class PatientListItem(PatientOut):
    # admitted = 入院中 / discharged = 退院済 / never = 入院歴なし
    admission_status: str = "never"
    current_admission: AdmissionOut | None = None


class PatientDetail(PatientListItem):
    assessment: AssessmentOut | None = None


# ---------------------------------------------------------------- 看護記録


class NursingNoteOut(ORMBase):
    id: int
    record_date: date
    shift: str
    format: str
    vitals: dict | None = None
    input_structured: dict | None = None
    input_free: str | None = None
    content_ai: str | None = None
    content_final: str | None = None
    status: str
    author_name: str | None = None
    confirmed_at: datetime | None = None
    # 画面表示用（content_final があればそれ、無ければ content_ai）
    display_content: str | None = None


class NoteListResponse(BaseModel):
    admission_id: int | None = None
    admission_status: str = "never"
    days: int
    items: list[NursingNoteOut]
