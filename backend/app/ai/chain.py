"""Chain A。直近記録は SQL。ベクトル検索（事例・用語集）は M3 まで空。"""
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.ai.context import ChainInput, vital_evidence
from app.ai.llm import get_chat_model, resolved_model_name
from app.ai.schemas import EvidenceItem, FocusNote, NarrativeNote, SOAPNote

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent / "prompts" / "v1"
_FORMAT_FILE = {"SOAP": "soap.yaml", "FOCUS": "focus.yaml", "NARRATIVE": "narrative.yaml"}
_SCHEMA = {"SOAP": SOAPNote, "FOCUS": FocusNote, "NARRATIVE": NarrativeNote}
_VITAL_SECTION = {"SOAP": "O", "FOCUS": "Data", "NARRATIVE": "N"}
_ATTEMPTS = 2


@dataclass
class Generation:
    content: str
    evidence: list[dict]
    model_name: str
    prompt_version: str
    token_usage: dict | None


def _load_prompt(note_format: str) -> tuple[str, str, str]:
    path = PROMPT_DIR / _FORMAT_FILE[note_format]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return str(data["version"]), str(data["system"]).strip(), str(data["human"]).strip()


def _format_notes(ctx: ChainInput) -> str:
    if not ctx.recent_notes:
        return "（直近の記録なし）"
    blocks = []
    for note in ctx.recent_notes:
        blocks.append(f"- {note.ref}（{note.when}）\n{note.text}")
    return "\n\n".join(blocks)


def _human_text(template: str, ctx: ChainInput) -> str:
    patient = ctx.patient.model_dump(exclude_none=True)
    today = ctx.today.model_dump()
    return template.format(
        patient=yaml.safe_dump(patient, allow_unicode=True, sort_keys=False).strip(),
        recent_notes=_format_notes(ctx),
        today=yaml.safe_dump(today, allow_unicode=True, sort_keys=False).strip(),
        vital_line=ctx.vital_line or "（なし）",
    )


def _usage(raw) -> dict | None:
    meta = getattr(raw, "usage_metadata", None)
    if not meta and hasattr(raw, "response_metadata"):
        meta = (raw.response_metadata or {}).get("token_usage")
    if meta is None:
        return None
    if hasattr(meta, "model_dump"):
        meta = meta.model_dump()
    if isinstance(meta, dict):
        return {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, type(None)))}
    return None


def _render(note_format: str, note: SOAPNote | FocusNote | NarrativeNote, vital_line: str) -> str:
    if isinstance(note, SOAPNote):
        objective = _prepend(note.objective, vital_line)
        return (
            f"S）{note.subjective.strip()}\n"
            f"O）{objective}\n"
            f"A）{note.assessment.strip()}\n"
            f"P）{note.plan.strip()}"
        )
    if isinstance(note, FocusNote):
        data = _prepend(note.data, vital_line)
        return (
            f"D）{data}\n"
            f"A）{note.action.strip()}\n"
            f"R）{note.response.strip()}"
        )
    return _prepend(note.body, vital_line)


def _prepend(body: str, vital_line: str) -> str:
    body = (body or "").strip()
    if not vital_line:
        return body
    if vital_line in body:
        return body
    return f"{vital_line}\n{body}".strip() if body else vital_line


def _evidence_payload(note, vital_line: str, section: str) -> list[dict]:
    items: list[EvidenceItem] = list(note.evidence)
    vital = vital_evidence(vital_line, section)
    if vital is not None and all(item.text != vital.text for item in items):
        items.insert(0, vital)
    return [item.model_dump() for item in items]


async def run_chain(ctx: ChainInput) -> Generation:
    version, system, human_t = _load_prompt(ctx.format)
    schema = _SCHEMA[ctx.format]
    llm = get_chat_model().with_structured_output(schema, include_raw=True)
    human = _human_text(human_t, ctx)
    messages = [SystemMessage(system), HumanMessage(human)]
    last_error: Exception | None = None

    for attempt in range(1, _ATTEMPTS + 1):
        try:
            result = await llm.ainvoke(messages)
            parsed = result["parsed"] if isinstance(result, dict) else result
            raw = result.get("raw") if isinstance(result, dict) else None
            parsing_error = result.get("parsing_error") if isinstance(result, dict) else None
            if parsed is None:
                raise ValueError(str(parsing_error or "構造化出力を解釈できません"))
            content = _render(ctx.format, parsed, ctx.vital_line)
            evidence = _evidence_payload(parsed, ctx.vital_line, _VITAL_SECTION[ctx.format])
            return Generation(
                content=content,
                evidence=evidence,
                model_name=resolved_model_name(),
                prompt_version=version,
                token_usage=_usage(raw),
            )
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.info("chain A rejected attempt %s: %s", attempt, exc)
            if attempt >= _ATTEMPTS:
                break
            messages = [
                SystemMessage(system),
                HumanMessage(human),
                HumanMessage(
                    "前回の出力は記録の型に合わないため却下した。同じ誤りをせず、"
                    f"スキーマを満たす JSON だけを返すこと。理由: {exc}"
                ),
            ]

    raise ValueError(
        "生成結果が記録の型制約を満たしませんでした。入力を変えて再実行してください。"
        f"（{last_error}）"
    )
