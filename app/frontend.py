"""화면의 입력 준비와 체크리스트 확인을 위한 순수 함수."""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST_SCHEMA_PATH = ROOT / "schemas" / "parsing" / "checklist.json"


def prepare_job_text(company_info: str, job_posting: str) -> str:
    """회사정보·공고 문자열을 받아 고정 제목으로 구분한 TXT 내용을 반환한다."""
    if not job_posting.strip():
        raise ValueError("채용공고 내용을 입력해 주세요.")
    sections = []
    if company_info.strip():
        sections.append(f"회사정보\n{company_info}")
    sections.append(f"채용공고\n{job_posting}")
    return "\n\n".join(sections) + "\n"


def prepare_resume_text(resume: str) -> str:
    """이력서 문자열을 받아 빈 입력을 검사한 뒤 원문 그대로 반환한다."""
    if not resume.strip():
        raise ValueError("이력서 내용을 입력해 주세요.")
    return resume


@lru_cache(maxsize=1)
def load_checklist_schema() -> dict[str, Any]:
    """인수 없이 파싱팀의 체크리스트 스키마(schemas/parsing/checklist.json)를 읽어 돌려준다."""
    return json.loads(CHECKLIST_SCHEMA_PATH.read_text(encoding="utf-8"))


def allowed_values(field: str) -> list[str]:
    """항목 칸 이름("type" 또는 "level")을 받아 스키마에 적힌 허용값 목록을 돌려준다."""
    item_schema = load_checklist_schema()["properties"]["items"]["items"]
    return list(item_schema["properties"][field]["enum"])


def sample_draft_checklist(sample: dict[str, Any]) -> dict[str, Any]:
    """샘플 체크리스트를 받아 '사용자가 아직 확인하지 않은 파싱 결과'처럼 만든 복사본을 돌려준다.

    임시 함수다. 파싱팀 make_checklist가 화면에 연결되면 이 함수 대신 그 결과를 쓴다.
    - reviewed는 확인 전이므로 항상 False로 둔다 (샘플이 True여도).
    - 샘플이 아직 옛 모양이라 schema_version이 없으면 1로 채운다.
    """
    draft = deepcopy(sample)
    draft.setdefault("schema_version", 1)
    draft["reviewed"] = False
    return draft


def _item_label(checklist: Any, index: int) -> str:
    """체크리스트와 항목 위치(0부터)를 받아 '2번 항목 (req-2)' 같은 표시 이름을 돌려준다."""
    items = checklist.get("items") if isinstance(checklist, dict) else None
    item = items[index] if isinstance(items, list) and index < len(items) else None
    item_id = item.get("id") if isinstance(item, dict) else None
    if isinstance(item_id, str) and item_id.strip():
        return f"{index + 1}번 항목 ({item_id})"
    return f"{index + 1}번 항목"


def _schema_error_message(checklist: Any, error: Any) -> str:
    """체크리스트와 스키마 검사 오류 하나를 받아 어느 칸이 왜 틀렸는지 한국어 문장으로 돌려준다."""
    path = list(error.absolute_path)
    if len(path) >= 2 and path[0] == "items" and isinstance(path[1], int):
        label = _item_label(checklist, path[1])
        rest = path[2:]
    else:
        label = "체크리스트"
        rest = path
    field = str(rest[0]) if rest else ""
    target = f"{field} " if field else ""

    kind = error.validator
    if kind == "required":
        present = error.instance if isinstance(error.instance, dict) else {}
        missing = [name for name in error.validator_value if name not in present]
        return f"{label}: {', '.join(missing)} 칸이 없습니다."
    if kind == "minLength":
        if len(rest) == 2 and isinstance(rest[1], int):
            return f"{label}: {field} {rest[1] + 1}번째 값이 비어 있습니다."
        return f"{label}: {target}값이 비어 있습니다."
    if kind == "minItems":
        return f"{label}: {target}한 개 이상 필요합니다."
    if kind == "enum":
        return f"{label}: {target}값은 {', '.join(error.validator_value)} 중 하나여야 합니다."
    if kind == "type":
        return f"{label}: {target}형식이 맞지 않습니다."
    if kind == "minimum":
        return f"{label}: {target}값은 {error.validator_value} 이상이어야 합니다."
    return f"{label}: {target}{error.message}"


def validate_checklist(checklist: Any) -> list[str]:
    """체크리스트를 받아 틀린 곳을 한국어 오류 목록으로 돌려준다. 빈 목록이면 통과다.

    AGENTS.md대로 칸 누락·타입·허용값은 스키마로 검사하고, id 중복은 코드로 검사한다.
    """
    validator = Draft202012Validator(load_checklist_schema())
    errors = [
        _schema_error_message(checklist, error)
        for error in sorted(validator.iter_errors(checklist), key=lambda error: list(error.absolute_path))
    ]

    items = checklist.get("items") if isinstance(checklist, dict) else None
    id_rows: dict[str, list[int]] = {}
    for number, item in enumerate(items if isinstance(items, list) else [], start=1):
        item_id = item.get("id") if isinstance(item, dict) else None
        if isinstance(item_id, str) and item_id.strip():
            id_rows.setdefault(item_id, []).append(number)
    for item_id, numbers in id_rows.items():
        if len(numbers) > 1:
            for number in numbers:
                errors.append(f"{number}번 항목 ({item_id}): ID가 중복됩니다.")
    return errors


def checklist_rows(checklist: dict[str, Any]) -> list[dict[str, Any]]:
    """체크리스트를 받아 표에 표시할 기존 필드 다섯 개의 복사본을 반환한다."""
    return [
        {field: deepcopy(item.get(field)) for field in ("id", "text", "keywords", "type", "level")}
        for item in checklist["items"]
    ]


def _clean_text(value: Any) -> Any:
    """표에서 받은 값 하나를 받아 문자열이면 앞뒤 공백을 지워 돌려준다. 문자열이 아니면 그대로 둔다."""
    return value.strip() if isinstance(value, str) else value


def merge_checklist_edits(
    original: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """원본과 편집 행을 받아 요구사항·키워드·유형·필수/우대를 반영한 복사본을 돌려준다.

    항목 ID와 항목 수는 바꿀 수 없다. 바뀌었으면 ValueError로 멈춘다.
    앞뒤 공백만 지우고, 빈 값은 지우지 않고 남겨서 검사에서 사용자에게 보이게 한다.
    """
    if not isinstance(rows, list) or len(rows) != len(original["items"]):
        raise ValueError("항목의 추가·삭제는 지원하지 않습니다. 원래 항목 수를 유지해 주세요.")
    result = deepcopy(original)
    for number, (item, row) in enumerate(zip(result["items"], rows), start=1):
        if not isinstance(row, dict):
            raise ValueError(f"{number}번 항목: 편집 행의 형식이 올바르지 않습니다.")
        if row.get("id") != item.get("id"):
            raise ValueError(f"{number}번 항목: id는 변경할 수 없습니다.")
        keywords = row.get("keywords")
        item["text"] = _clean_text(row.get("text"))
        item["keywords"] = [_clean_text(keyword) for keyword in keywords] if isinstance(keywords, list) else []
        item["type"] = row.get("type")
        item["level"] = row.get("level")
    return result


def mark_reviewed(checklist: dict[str, Any]) -> dict[str, Any]:
    """사용자가 확인을 마친 체크리스트를 받아 reviewed를 True로 바꾼 복사본을 돌려준다."""
    reviewed = deepcopy(checklist)
    reviewed["reviewed"] = True
    return reviewed


def checklist_json(checklist: dict[str, Any]) -> str:
    """체크리스트를 받아 검증 후 한글을 보존한 다운로드용 JSON 문자열을 반환한다."""
    errors = validate_checklist(checklist)
    if errors:
        raise ValueError("\n".join(errors))
    return json.dumps(checklist, ensure_ascii=False, indent=2) + "\n"
