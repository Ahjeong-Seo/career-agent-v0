"""화면의 입력 준비와 체크리스트 편집을 위한 순수 함수."""

from copy import deepcopy
import json
from typing import Any


def prepare_job_text(company_info: str, job_posting: str) -> str:
    """회사정보·공고 문자열을 받아 고정 제목으로 구분한 TXT 내용을 반환한다."""
    if not job_posting.strip():
        raise ValueError("채용공고 내용을 입력해 주세요.")
    return f"회사정보\n{company_info}\n\n공고\n{job_posting}\n"


def prepare_resume_text(resume: str) -> str:
    """이력서 문자열을 받아 빈 입력을 검사한 뒤 원문 그대로 반환한다."""
    if not resume.strip():
        raise ValueError("이력서 내용을 입력해 주세요.")
    return resume


def validate_checklist(checklist: Any) -> list[str]:
    """체크리스트 데이터를 받아 누락·형식·중복 ID 오류를 항목별로 반환한다."""
    errors = []
    if not isinstance(checklist, dict):
        return ["체크리스트는 JSON 객체여야 합니다."]
    case_id = checklist.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        errors.append("체크리스트: case_id 값이 필요합니다.")
    job_title = checklist.get("job_title")
    if job_title is not None and not isinstance(job_title, str):
        errors.append("체크리스트: job_title은 문자열 또는 null이어야 합니다.")
    values = checklist.get("company_values", [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        errors.append("체크리스트: company_values는 빈 문자열이 없는 문자열 목록이어야 합니다.")
    items = checklist.get("items")
    if not isinstance(items, list) or not items:
        return errors + ["체크리스트: items에 항목이 한 개 이상 필요합니다."]

    id_rows: dict[str, list[int]] = {}
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"{number}번 항목: 항목은 JSON 객체여야 합니다.")
            continue
        item_id = item.get("id")
        label = f"{number}번 항목 ({item_id})" if isinstance(item_id, str) else f"{number}번 항목"
        for field in ("id", "text", "type", "level"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{label}: {field} 값이 필요합니다.")
        if item.get("type") not in ("기술", "경력", "경험", "기타"):
            errors.append(f"{label}: type은 기술·경력·경험·기타 중 하나여야 합니다.")
        if item.get("level") not in ("필수", "우대"):
            errors.append(f"{label}: level은 필수·우대 중 하나여야 합니다.")
        if isinstance(item_id, str) and item_id.strip():
            id_rows.setdefault(item_id, []).append(number)
        keywords = item.get("keywords")
        if not isinstance(keywords, list) or not keywords or any(
            not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
        ):
            errors.append(f"{label}: keywords에 비어 있지 않은 키워드를 한 개 이상 입력해 주세요.")
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


def merge_checklist_edits(
    original: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """원본과 편집 행을 받아 메타데이터를 보존한 결과를 반환하며 ID 변경은 거부한다."""
    if not isinstance(rows, list) or len(rows) != len(original["items"]):
        raise ValueError("항목의 추가·삭제는 지원하지 않습니다. 원래 항목 수를 유지해 주세요.")
    result = deepcopy(original)
    for number, (item, row) in enumerate(zip(result["items"], rows), start=1):
        if not isinstance(row, dict):
            raise ValueError(f"{number}번 항목: 편집 행의 형식이 올바르지 않습니다.")
        for field in ("id", "type", "level"):
            if row.get(field) != item.get(field):
                raise ValueError(f"{number}번 항목: {field}는 변경할 수 없습니다.")
        item["text"] = deepcopy(row.get("text"))
        item["keywords"] = deepcopy(row.get("keywords"))
    return result


def checklist_json(checklist: dict[str, Any]) -> str:
    """체크리스트를 받아 검증 후 한글을 보존한 다운로드용 JSON 문자열을 반환한다."""
    errors = validate_checklist(checklist)
    if errors:
        raise ValueError("\n".join(errors))
    return json.dumps(checklist, ensure_ascii=False, indent=2) + "\n"
