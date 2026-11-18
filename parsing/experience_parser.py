"""확인된 체크리스트와 이력서에서 요구사항별 경험 초안을 생성한다."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loop.call_llm import call_llm
from loop.data_contracts import load_checklist, read_json, validate_document
from parsing.common import get_case_directory, sanitize_json_strings, write_json_document


DRAFT_SCHEMA_PATH = ROOT / "schemas" / "parsing" / "experience_draft.json"
LLM_SCHEMA_PATH = ROOT / "schemas" / "parsing" / "experience_draft.llm.schema.json"
PROMPT_PATH = ROOT / "prompts" / "parsing_experience_draft_v1.md"
PROMPT_VERSION = "parsing_experience_draft_v1"
EXPERIENCE_DRAFT_SCHEMA_VERSION = 1


def parse_experience(job_text: str, resume_text: str, checklist: dict) -> dict[str, Any]:
    """JD·이력서 문자열과 확인된 checklist를 받아 검증된 경험 초안을 반환한다."""
    if not isinstance(job_text, str) or not job_text.strip():
        raise ValueError("jd.txt 내용이 비어 있거나 문자열이 아닙니다.")
    if not isinstance(resume_text, str) or not resume_text.strip():
        raise ValueError("resume.txt 내용이 비어 있거나 문자열이 아닙니다.")
    if not isinstance(checklist, dict) or not isinstance(checklist.get("items"), list):
        raise ValueError("checklist.items는 목록이어야 합니다.")

    case_id = checklist.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("checklist.case_id가 비어 있거나 문자열이 아닙니다.")
    validate_document(
        Path("checklist.json"),
        checklist,
        ROOT / "schemas/parsing/checklist.json",
    )

    llm_schema = json.loads(LLM_SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = _build_prompt(job_text, resume_text, checklist)
    for attempt in range(2):
        try:
            llm_result = call_llm(prompt, llm_schema)
            experience = _validate_llm_result(llm_result, resume_text, checklist)
            experience = _review_career_year_experiences(
                job_text, resume_text, checklist, experience, llm_schema
            )
            experience = _review_unmatched_experiences(
                job_text, resume_text, checklist, experience, llm_schema
            )
            experience = sanitize_json_strings(experience)
            validate_document(
                Path("experience_draft.json"), experience, DRAFT_SCHEMA_PATH
            )
            return experience
        except (KeyError, TypeError, ValueError) as error:
            if attempt == 1:
                raise ValueError(
                    f"경험 초안 응답 검증이 두 번 실패했습니다: {error}"
                ) from error
            prompt = (
                f"{prompt}\n\n"
                "## 재시도 지시\n"
                "직전 응답은 코드 검증을 통과하지 못했습니다. 아래 오류를 고쳐서 "
                "같은 입력 자료와 출력 스키마에 맞는 JSON만 다시 반환하세요.\n"
                f"검증 오류: {error}"
            )
    raise RuntimeError("경험 초안 생성이 완료되지 않았습니다.")


def _review_career_year_experiences(
    job_text: str,
    resume_text: str,
    checklist: dict[str, Any],
    experience: dict[str, Any],
    llm_schema: dict[str, Any],
) -> dict[str, Any]:
    """경력 연수 요건과 이력서 경력 구역을 받아 후보를 재검토해 반환한다."""
    career_items = [
        item
        for item in checklist["items"]
        if _is_explicit_career_duration_requirement(item)
    ]
    if not career_items:
        return experience

    career_text = _extract_career_section_text(resume_text)
    if not career_text:
        career_text = resume_text
    review_checklist = {**checklist, "items": career_items}
    review_prompt = _build_prompt(job_text, career_text, review_checklist)
    review_prompt += (
        "\n\n## 경력 연수 항목 재검토\n"
        "각 항목에 대해 checklist의 직무 키워드와 명시적 정수 연수가 함께 적힌 "
        "이력서 원문을 찾으세요. 직무 키워드만 포함된 업무 문장, 프로젝트 문장, "
        "다른 직무의 연수는 근거가 아닙니다. 같은 직무와 연수가 함께 명시된 원문이 "
        "없으면 text=null, evidence=[]로 반환하세요. 반환하는 text와 evidence는 입력된 "
        "이력서에서 연속된 원문 그대로 복사하세요. 이 재검토 결과에는 전달된 경력 "
        "연수 항목만 포함하세요."
    )
    review_schema = copy.deepcopy(llm_schema)
    expected_ids = [item["id"] for item in career_items]
    experience_schema = review_schema["properties"]["experiences"]
    experience_schema["minItems"] = len(expected_ids)
    experience_schema["maxItems"] = len(expected_ids)
    experience_schema["items"]["properties"]["item_id"]["enum"] = expected_ids
    review_result = call_llm(review_prompt, review_schema)
    id_order = {item_id: index for index, item_id in enumerate(expected_ids)}
    review_result["experiences"].sort(
        key=lambda row: id_order.get(row.get("item_id"), len(id_order))
    )
    reviewed = _validate_llm_result(review_result, resume_text, review_checklist)
    reviewed_by_id = {row["item_id"]: row for row in reviewed["experiences"]}
    merged_rows = [
        reviewed_by_id.get(row["item_id"], row)
        for row in experience["experiences"]
    ]
    return {**experience, "experiences": merged_rows}


def _review_unmatched_experiences(
    job_text: str,
    resume_text: str,
    checklist: dict[str, Any],
    experience: dict[str, Any],
    llm_schema: dict[str, Any],
) -> dict[str, Any]:
    """첫 결과의 미매칭 항목을 받아 부분 경험을 재검토한 결과를 반환한다."""
    rows_by_id = {row["item_id"]: row for row in experience["experiences"]}
    unmatched_items = [
        item
        for item in checklist["items"]
        if not (
            _is_explicit_career_duration_requirement(item)
        )
        and rows_by_id[item["id"]]["text"] is None
    ]
    if not unmatched_items:
        return experience

    review_checklist = {**checklist, "items": unmatched_items}
    review_prompt = _build_prompt(job_text, resume_text, review_checklist)
    review_prompt += (
        "\n\n## 미매칭 항목 재검토\n"
        "아래 항목은 첫 검토에서 경험을 찾지 못했습니다. 각 요구사항을 핵심 업무·역량과 "
        "기술·수단·세부 조건으로 나누어 다시 검토하세요. 이력서 원문이 핵심 업무나 "
        "역량을 실질적으로 뒷받침하면, 특정 기술이나 세부 조건이 원문에 없더라도 "
        "그 원문을 부분 경험으로 선택하세요. 선택한 원문만으로 확인되지 않는 기술, "
        "범위, 성과는 주장하지 마세요. 단어가 일반적으로 겹치는 것만으로 선택하지 말고, "
        "요구사항과의 실질적인 관련성을 확인하세요. 관련 원문이 없을 때만 null을 반환하세요.\n"
        "이 재검토 결과에서는 전달된 미매칭 항목만 반환하세요."
    )
    review_schema = copy.deepcopy(llm_schema)
    expected_ids = [item["id"] for item in unmatched_items]
    experience_schema = review_schema["properties"]["experiences"]
    experience_schema["minItems"] = len(expected_ids)
    experience_schema["maxItems"] = len(expected_ids)
    experience_schema["items"]["properties"]["item_id"]["enum"] = expected_ids
    review_result = call_llm(review_prompt, review_schema)
    id_order = {item_id: index for index, item_id in enumerate(expected_ids)}
    review_result["experiences"].sort(
        key=lambda row: id_order.get(row.get("item_id"), len(id_order))
    )
    reviewed = _validate_llm_result(review_result, resume_text, review_checklist)
    reviewed_by_id = {row["item_id"]: row for row in reviewed["experiences"]}

    merged_rows = []
    for row in experience["experiences"]:
        reviewed_row = reviewed_by_id.get(row["item_id"])
        if row["text"] is None and reviewed_row and reviewed_row["text"] is not None:
            merged_rows.append(reviewed_row)
        else:
            merged_rows.append(row)
    return {**experience, "experiences": merged_rows}


def _build_prompt(job_text: str, resume_text: str, checklist: dict[str, Any]) -> str:
    """JD·이력서·확인된 checklist를 받아 경험 초안 생성용 프롬프트를 반환한다."""
    instructions = PROMPT_PATH.read_text(encoding="utf-8").strip()
    inputs = {
        "jd.txt": job_text,
        "checklist.json": checklist,
        "resume.txt": resume_text,
    }
    return (
        f"{instructions}\n\n"
        "아래 세 파일만 근거로 사용하세요. JSON 형식은 입력 자료입니다.\n"
        "## 입력 자료\n"
        f"{json.dumps(inputs, ensure_ascii=False, indent=2)}"
    )


def _validate_llm_result(
    result: dict[str, Any], resume_text: str, checklist: dict[str, Any]
) -> dict[str, Any]:
    """LLM 응답·이력서·checklist를 받아 근거와 ID를 확인한 저장 객체를 반환한다."""
    case_id = checklist["case_id"]
    if result.get("case_id") != case_id:
        raise ValueError("LLM 응답의 case_id가 checklist.case_id와 다릅니다.")

    rows = result.get("experiences")
    checklist_items = checklist["items"]
    expected_ids = [item["id"] for item in checklist_items]
    if not isinstance(rows, list):
        raise ValueError("LLM 응답의 experiences는 목록이어야 합니다.")
    actual_ids = [
        row.get("item_id") if isinstance(row, dict) else None for row in rows
    ]
    if actual_ids != expected_ids:
        raise ValueError("LLM 응답의 item_id와 checklist 항목 ID·순서가 다릅니다.")

    experience_resume = _exclude_application_fields(resume_text)
    normalized_experience_resume = _normalize_text(experience_resume)
    final_rows = []
    for index, (row, item) in enumerate(zip(rows, checklist_items, strict=True)):
        text = row["text"]
        evidence = row["evidence"]
        if item.get("type") == "기술" and isinstance(text, str):
            full_skill_line = _expand_to_full_skill_list_line(text, resume_text)
            if full_skill_line != text:
                text = full_skill_line
                evidence = [text, *[quote for quote in evidence if quote != text]][:3]
        match_basis = row["match_basis"]
        keywords = [
            _normalize_text(keyword)
            for keyword in item["keywords"]
            if isinstance(keyword, str) and keyword.strip()
        ]
        career_summary = _find_explicit_career_summary(resume_text, item)
        if career_summary is not None:
            text = career_summary
            evidence = [text, *[quote for quote in evidence if quote != text]][:3]
        if _is_explicit_career_duration_requirement(item) and not _has_role_and_years_in_text(
            text, item
        ):
            text = None
            evidence = []
            match_basis = "none"
        if _is_project_only_career_evidence(text, resume_text, item):
            text = None
            evidence = []
            match_basis = "none"
        evidence = [text] if isinstance(text, str) and text else []
        normalized_evidence = _normalize_text("\n".join(evidence))
        if match_basis != "none":
            match_basis = (
                "keywords"
                if any(keyword in normalized_evidence for keyword in keywords)
                else "requirement_text"
            )
        if match_basis == "none":
            if text is not None or evidence:
                raise ValueError(
                    f"experiences[{index}]: 근거 없음은 text=null, evidence=[]이어야 합니다."
                )
        else:
            if not isinstance(text, str) or not text.strip() or not evidence:
                raise ValueError(
                    f"experiences[{index}]: 매칭된 초안에는 text와 evidence가 필요합니다."
                )
            if (
                _is_title_only_evidence(text, resume_text)
                and not _requires_title_or_seniority(item.get("text", ""))
            ):
                raise ValueError(
                    f"experiences[{index}].text는 직책·직급만 포함하지만 "
                    "checklist 요구사항은 특정 직책·직급을 요구하지 않습니다. "
                    "직무와 관련된 실제 업무 원문을 찾거나 text=null을 반환하세요."
                )
            if _is_section_heading_only(text, resume_text):
                raise ValueError(
                    f"experiences[{index}].text는 이력서 구역 제목만 포함합니다. "
                    "구역 안의 구체적인 업무 원문을 찾거나 text=null을 반환하세요."
                )
            if text not in resume_text:
                raise ValueError(
                    f"experiences[{index}].text가 resume.txt 원문 그대로가 아닙니다."
                )
            if _normalize_text(text) not in normalized_experience_resume:
                raise ValueError(
                    f"experiences[{index}].text가 지원분야·포지션 필드를 제외한 "
                    "resume.txt 경험 원문에 없습니다."
                )
            for evidence_index, quote in enumerate(evidence):
                if _normalize_text(quote) not in normalized_experience_resume:
                    raise ValueError(
                        f"experiences[{index}].evidence[{evidence_index}]가 "
                        "지원분야·포지션 필드를 제외한 resume.txt에 없습니다."
                    )
            evidence_numbers = _extract_numbers("\n".join(evidence))
            draft_numbers = _extract_numbers(text)
            if not draft_numbers.issubset(evidence_numbers):
                raise ValueError(
                    f"experiences[{index}].text에 resume 근거에 없는 숫자가 있습니다."
                )

        final_rows.append(
            {
                "item_id": row["item_id"],
                "text": text,
                "years": _extract_experience_years(text, item.get("years")),
            }
        )

    return {
        "case_id": case_id,
        "schema_version": EXPERIENCE_DRAFT_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "experiences": final_rows,
    }


def _extract_numbers(text: str) -> set[str]:
    """문장에서 쉼표를 제외한 숫자 덩어리 집합을 반환한다."""
    return {value.replace(",", "") for value in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def _normalize_text(text: str) -> str:
    """문자열을 받아 공백과 영문 대소문자를 정규화해 반환한다."""
    return re.sub(r"\s+", "", text).casefold()


def _extract_experience_years(
    text: str | None, required_years: int | None
) -> int | None:
    """경험 원문과 checklist 요구 연수를 받아 정수 연수를 반환하고 조건에 따라 null을 돌려준다."""
    if not isinstance(required_years, int) or required_years < 1:
        return None
    if text is None:
        return None
    if not isinstance(text, str) or not text.strip():
        return 0
    if re.search(r"(?<!\d)\d{1,2}\s*[~–—-]\s*\d{1,2}\s*년", text):
        return None
    matches = re.findall(r"(?<!\d)(\d{1,2})\s*년", text)
    distinct_years = {int(value) for value in matches}
    if len(distinct_years) > 1:
        return None
    if not distinct_years:
        return 0
    years = distinct_years.pop()
    return years if 0 <= years <= 100 else None


def _find_explicit_career_summary(
    resume_text: str, checklist_item: dict[str, Any]
) -> str | None:
    """이력서와 경력 요구사항을 받아 직무·연수가 함께 적힌 요약 원문을 반환한다."""
    required_years = checklist_item.get("years")
    if checklist_item.get("type") != "경력" or not isinstance(required_years, int) or required_years < 1:
        return None
    keywords = [
        _normalize_text(keyword)
        for keyword in checklist_item.get("keywords", [])
        if isinstance(keyword, str) and keyword.strip()
    ]
    if not keywords:
        return None

    tenure_pattern = re.compile(r"(?<!\d)\d{1,2}\s*년\s*(?:차|경력|이상|정도)?")
    candidates = []
    for line in _exclude_application_fields(resume_text).splitlines():
        candidate = line.strip()
        normalized_candidate = _normalize_text(candidate)
        if tenure_pattern.search(candidate) and any(
            keyword in normalized_candidate for keyword in keywords
        ):
            candidates.append(candidate)
    unique_candidates = list(dict.fromkeys(candidates))
    return unique_candidates[0] if len(unique_candidates) == 1 else None


def _is_project_only_career_evidence(
    text: str | None, resume_text: str, checklist_item: dict[str, Any]
) -> bool:
    """경력 연수 요건·명시적 무경력·프로젝트 구역 원문이면 참을 반환한다."""
    if not _is_explicit_career_duration_requirement(checklist_item) or not isinstance(
        text, str
    ):
        return False
    if not _has_explicit_no_work_history(resume_text):
        return False

    project_lines: list[str] = []
    in_project_section = False
    for line in resume_text.splitlines():
        section = _resume_section_kind(line)
        if section is not None:
            in_project_section = section == "project"
        elif in_project_section:
            project_lines.append(line)
    return _normalize_text(text) in _normalize_text("\n".join(project_lines))


def _is_explicit_career_duration_requirement(
    checklist_item: dict[str, Any]
) -> bool:
    """checklist 항목 문구가 직무 경력 연수를 명시적으로 요구하는지 반환한다."""
    required_years = checklist_item.get("years")
    requirement_text = checklist_item.get("text", "")
    return (
        checklist_item.get("type") == "경력"
        and isinstance(required_years, int)
        and required_years >= 1
        and isinstance(requirement_text, str)
        and bool(re.search(r"(?:경력|career|employment|tenure)", requirement_text, re.I))
    )


def _has_role_and_years_in_text(
    text: str | None, checklist_item: dict[str, Any]
) -> bool:
    """선택 원문에 checklist 직무 키워드와 명시적 연수가 함께 있는지 반환한다."""
    if not isinstance(text, str) or not re.search(r"(?<!\d)\d{1,2}\s*년", text):
        return False
    normalized_text = _normalize_text(text)
    keywords = [
        _normalize_text(keyword)
        for keyword in checklist_item.get("keywords", [])
        if isinstance(keyword, str) and keyword.strip()
    ]
    return bool(keywords) and any(keyword in normalized_text for keyword in keywords)


def _has_explicit_no_work_history(resume_text: str) -> bool:
    """이력서 경력 구역에 경력 부재가 명시되었는지 반환한다."""
    lines = resume_text.splitlines()
    no_experience = re.compile(r"^(?:없음|해당없음|무경력|경력없음|신입|noexperience)$", re.I)
    career_heading = re.compile(
        r"^(?:경력(?:사항|이력)?|career(?:history)?|workexperience|employmenthistory)$",
        re.I,
    )
    for index, line in enumerate(lines):
        cleaned = re.sub(r"^[#\s•·▪◆\-]+", "", line).strip()
        normalized = _normalize_text(cleaned)
        inline_match = re.fullmatch(
            r"(?:경력(?:사항|이력)?|career(?:history)?|workexperience|employmenthistory)[:：](.+)",
            normalized,
            re.I,
        )
        if inline_match and no_experience.fullmatch(inline_match.group(1)):
            return True
        if not career_heading.fullmatch(normalized):
            continue
        for following_line in lines[index + 1 :]:
            value = re.sub(r"^[#\s•·▪◆\-]+", "", following_line).strip()
            value = re.sub(r"^[─━\-_=]+$", "", value).strip()
            if not value:
                continue
            if no_experience.fullmatch(_normalize_text(value)):
                return True
            break
    return False


def _resume_section_kind(line: str) -> str | None:
    """이력서의 구역 제목 행을 받아 경력·프로젝트 등 구역 종류를 반환한다."""
    cleaned = re.sub(r"^[#\s•·▪◆\-]+", "", line).strip()
    cleaned = re.sub(r"^\d+[.)、]\s*", "", cleaned)
    normalized = _normalize_text(cleaned.strip(" :："))
    if re.fullmatch(r"(?:프로젝트(?:경험|이력|사항)?|projects?(?:experience)?)", normalized, re.I):
        return "project"
    if re.fullmatch(
        r"(?:경력(?:사항|이력|경험|요약)?|career(?:history|experience)?|workexperience|employmenthistory)",
        normalized,
        re.I,
    ):
        return "career"
    if re.fullmatch(
        r"(?:교육|학력|기타|skills?|languages?|어학|자격증?|수상|요약|소개|experience)",
        normalized,
        re.I,
    ):
        return "other"
    return None


def _extract_career_section_text(resume_text: str) -> str:
    """이력서에서 경력 구역의 원문을 모아 문자열로 반환한다."""
    career_lines: list[str] = []
    in_career_section = False
    found_career_section = False
    for line in resume_text.splitlines():
        section = _resume_section_kind(line)
        if section is not None:
            in_career_section = section == "career"
            found_career_section = found_career_section or in_career_section
        elif in_career_section:
            career_lines.append(line)
    return "\n".join(career_lines).strip() if found_career_section else ""


def _expand_to_full_skill_list_line(text: str, resume_text: str) -> str:
    """선택된 기술명과 이력서를 받아 목록 행의 일부면 원문 행 전체를 반환한다."""
    normalized_text = _normalize_text(text.strip())
    if not normalized_text:
        return text
    for line in resume_text.splitlines():
        stripped_line = line.strip()
        if "," not in stripped_line:
            continue
        segments = stripped_line.split(",")
        first_segment = segments[0].rsplit(":", 1)[-1]
        segments[0] = first_segment
        if any(
            _normalize_text(segment.strip()) == normalized_text
            for segment in segments
        ):
            return stripped_line
    return text


def _requires_title_or_seniority(requirement_text: str) -> bool:
    """체크리스트 요구 문구를 받아 특정 직책·직급을 명시적으로 요구하는지 반환한다."""
    title_pattern = re.compile(
        r"(?:파트장|팀장|실장|본부장|센터장|수석|책임|선임|대리|과장|차장|부장|임원|"
        r"리더|시니어|senior|lead|manager|director)"
        r"\s*(?:급|이상|경력|경험|역할|직책|직급)"
        r"|(?:직책|직급|직위)\s*[:：]",
        re.IGNORECASE,
    )
    return bool(title_pattern.search(requirement_text))


def _is_title_only_evidence(text: str, resume_text: str) -> bool:
    """초안 문구와 이력서를 받아 문구가 직책·직급 표시란만 복사했는지 반환한다."""
    label_pattern = re.compile(
        r"^\s*(?:[•·▪◆\-]\s*)?(?:최종)?(?:직급|직책|직위|담당직무)\s*[:：]\s*(?P<value>.+?)\s*$",
        re.IGNORECASE,
    )
    normalized_text = _normalize_text(text.strip())
    for line in resume_text.splitlines():
        match = label_pattern.match(line)
        if not match:
            continue
        normalized_line = _normalize_text(line.strip())
        normalized_value = _normalize_text(match.group("value").strip())
        if normalized_text in {normalized_line, normalized_value}:
            return True
    return False


def _is_section_heading_only(text: str, resume_text: str) -> bool:
    """초안 문구와 이력서를 받아 문구가 괄호로 표시된 구역 제목뿐인지 반환한다."""
    normalized_text = _normalize_text(text.strip())
    for line in resume_text.splitlines():
        stripped_line = line.strip()
        if len(stripped_line) < 3:
            continue
        if (stripped_line[0], stripped_line[-1]) in {("[", "]"), ("【", "】")}:
            heading = stripped_line[1:-1].strip()
            if normalized_text in {
                _normalize_text(heading),
                _normalize_text(stripped_line),
            }:
                return True
    return False


def _exclude_application_fields(resume_text: str) -> str:
    """이력서 원문에서 지원분야·포지션 메타데이터 행을 제외해 반환한다."""
    application_labels = {
        "지원",
        "지원분야",
        "지원직무",
        "지원직무명",
        "지원포지션",
        "희망",
        "희망분야",
        "희망직무",
        "희망포지션",
        "포지션",
        "position",
        "targetrole",
        "targetposition",
        "분야",
    }
    lines = resume_text.splitlines()
    retained_lines = []
    skip_field_value = False
    for line in lines:
        if skip_field_value:
            if not line.strip():
                retained_lines.append(line)
                continue
            skip_field_value = False
            continue
        compact_line = re.sub(r"\s+", "", line).casefold()
        compact_line = re.sub(r"^[•·▪◆\-]+", "", compact_line)
        separator = (
            ":"
            if ":" in compact_line
            else "："
            if "：" in compact_line
            else ""
        )
        label = compact_line.split(separator, 1)[0] if separator else compact_line
        if label in application_labels:
            skip_field_value = not separator
            continue
        retained_lines.append(line)
    return "\n".join(retained_lines)


def generate_experience_draft(
    case_id: str, *, overwrite: bool = False
) -> tuple[dict[str, Any], Path]:
    """case ID를 받아 세 입력 파일로 초안을 생성·저장하고 객체와 경로를 반환한다."""
    case_dir = get_case_directory(case_id)
    jd_path = case_dir / "jd.txt"
    resume_path = case_dir / "resume.txt"
    checklist_path = case_dir / "checklist.json"
    for path in (jd_path, resume_path, checklist_path):
        if not path.is_file():
            raise FileNotFoundError(f"경험 초안 생성에 필요한 파일이 없습니다: {path}")

    checklist = load_checklist(checklist_path)
    if checklist["case_id"] != case_id:
        raise ValueError("checklist.case_id와 case 폴더 ID가 다릅니다.")
    output_path = case_dir / "experience_draft.json"
    if output_path.exists() and not overwrite:
        existing = read_json(output_path)
        sanitized_existing = sanitize_json_strings(existing)
        validate_document(output_path, existing, DRAFT_SCHEMA_PATH)
        _validate_experience_ids(sanitized_existing, checklist)
        requirement_years = {
            item["id"]: item.get("years") for item in checklist["items"]
        }
        for row in sanitized_existing["experiences"]:
            row["years"] = (
                _extract_experience_years(
                    row.get("text"), requirement_years[row["item_id"]]
                )
            )
        if sanitized_existing != existing:
            write_json_document(
                output_path,
                sanitized_existing,
                DRAFT_SCHEMA_PATH,
                overwrite=True,
                sanitize_strings=True,
            )
        return sanitized_existing, output_path

    experience = parse_experience(
        jd_path.read_text(encoding="utf-8-sig"),
        resume_path.read_text(encoding="utf-8-sig"),
        checklist,
    )
    write_json_document(
        output_path,
        experience,
        DRAFT_SCHEMA_PATH,
        overwrite=overwrite,
        sanitize_strings=True,
    )
    _record_prompt_version(case_id, output_path)
    return experience, output_path


def _validate_experience_ids(experience: dict[str, Any], checklist: dict[str, Any]) -> None:
    """기존 experience와 checklist를 받아 ID 일치 여부를 확인하고 다르면 오류를 낸다."""
    expected_ids = [item["id"] for item in checklist["items"]]
    actual_ids = [
        row.get("item_id") if isinstance(row, dict) else None
        for row in experience.get("experiences", [])
    ]
    if experience.get("case_id") != checklist["case_id"] or actual_ids != expected_ids:
        raise ValueError(
            "기존 experience_draft.json의 case_id 또는 item_id가 checklist와 다릅니다."
        )


def _record_prompt_version(case_id: str, result_path: Path) -> None:
    """case ID와 결과 경로를 받아 사용한 프롬프트 버전을 기록한다."""
    cache_dir = ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "event": "experience_draft",
        "prompt_version": PROMPT_VERSION,
        "case_id": case_id,
        "result_file": str(result_path.relative_to(ROOT)),
    }
    with (cache_dir / "calls.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> None:
    """case ID를 받아 저장된 입력으로 경험 초안을 생성하고 경로를 출력한다."""
    parser = argparse.ArgumentParser(
        description="확인된 checklist에서 경험 초안을 생성합니다."
    )
    parser.add_argument("case_id", help="JD·resume·확인된 checklist가 저장된 case ID")
    args = parser.parse_args(argv)
    try:
        _, output_path = generate_experience_draft(args.case_id)
    except Exception as error:
        parser.exit(status=1, message=f"오류: {type(error).__name__}: {error}\n")
    print(output_path)


if __name__ == "__main__":
    main()
