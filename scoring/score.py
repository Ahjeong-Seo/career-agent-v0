"""규칙 기반 score_case 공개 진입점과 결과 검증을 제공한다."""

import re
from pathlib import Path
from typing import Any


def score_case(
    checklist: dict[str, Any], experience: dict[str, Any], rewrite: dict[str, Any]
) -> dict[str, Any]:
    """확정 checklist, 경험 응답, 한 스타일 rewrite를 받아 규칙 채점 결과를 반환한다."""
    if checklist.get("reviewed") is not True:
        raise ValueError("체크리스트를 검토하고 확정해야 채점할 수 있습니다.")
    case_id = checklist.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("checklist.case_id가 필요합니다.")
    experience_version = experience.get("schema_version")
    if isinstance(experience_version, bool) or not isinstance(experience_version, int) or experience_version < 1:
        raise ValueError("experience.schema_version은 1 이상의 정수여야 합니다.")
    if case_id != experience.get("case_id") or case_id != rewrite.get("case_id"):
        raise ValueError("checklist, experience, rewrite의 case_id가 서로 다릅니다.")
    if not isinstance(checklist.get("items"), list) or not checklist["items"]:
        raise ValueError("checklist.items에 채점 항목이 한 개 이상 필요합니다.")

    checklist_items = _records_by_item_id(checklist.get("items"), "checklist.items", "id")
    experiences = _records_by_item_id(experience.get("experiences"), "experience.experiences", "item_id")
    sentences = _records_by_item_id(rewrite.get("sentences"), "rewrite.sentences", "item_id")

    unknown_experiences = sorted(set(experiences) - set(checklist_items))
    if unknown_experiences:
        raise ValueError(f"checklist에 없는 경험 item_id입니다: {', '.join(unknown_experiences)}")
    unknown_sentences = sorted(set(sentences) - set(checklist_items))
    if unknown_sentences:
        raise ValueError(f"checklist에 없는 rewrite item_id입니다: {', '.join(unknown_sentences)}")

    style_id = _style_id(rewrite)
    attempt = rewrite.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("rewrite.attempt는 1 이상의 정수여야 합니다.")
    attempt_id = rewrite.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("rewrite.attempt_id는 비어 있지 않은 문자열이어야 합니다.")
    generic_phrases = _generic_phrases()

    results = []
    issues = []
    for item_id, item in checklist_items.items():
        max_points = _max_item_points(item)
        response = experiences.get(item_id)
        if response is None:
            has_rewrite = item_id in sentences and bool(
                isinstance(sentences[item_id].get("text"), str)
                and sentences[item_id]["text"].strip()
            )
            if has_rewrite:
                issues.append({
                    "item_id": item_id,
                    "code": "TEXT_WITHOUT_EXPERIENCE",
                    "value": sentences[item_id]["text"],
                    "reason": "경험 없는 항목의 문장을 삭제해 주세요.",
                })
            results.append({
                "item_id": item_id,
                "status": "경험 없음",
                "reason": (
                    "경험 없음으로 선택했지만 결과 문장이 있습니다. 문장을 삭제해 주세요."
                    if has_rewrite
                    else "확정한 경험 입력에 이 항목이 없습니다."
                ),
                "score": {"earned": 0, "max": max_points},
                "matched_keywords": [],
                "missing_keywords": list(item["keywords"]),
                "checks": [{
                    "code": "NUMERIC_EVIDENCE_PRESENT",
                    "result": "not_applicable",
                    "reason": "경험 없음으로 선택해 수치 근거를 확인하지 않습니다.",
                }],
            })
            continue
        if not isinstance(response.get("text"), str) or not response["text"].strip():
            raise ValueError(f"experience.experiences[{item_id}].text는 비어 있지 않은 문자열이어야 합니다.")

        sentence = sentences.get(item_id)
        numeric_check = _numeric_evidence_check(response["text"])
        if sentence is None or not isinstance(sentence.get("text"), str) or not sentence["text"].strip():
            reason = _career_note("첨삭 문장이 없습니다.", item.get("type") == "경력")
            results.append({
                "item_id": item_id,
                "status": "미충족",
                "reason": reason,
                "score": {"earned": 0, "max": max_points},
                "matched_keywords": [],
                "missing_keywords": list(item["keywords"]),
                "checks": [numeric_check],
            })
            continue
        if sentence.get("source") != response["text"]:
            raise ValueError(f"rewrite.sentences[{item_id}].source가 experience.text와 다릅니다.")
        text = sentence["text"]
        source = response["text"]
        is_career = item.get("type") == "경력"
        source_numbers = {
            _normalize_number(number)
            for number in _number_tokens(source, ignore_career_years=is_career)
        }
        for number in _number_tokens(text, ignore_career_years=is_career):
            if _normalize_number(number) not in source_numbers:
                issues.append({
                    "item_id": item_id,
                    "code": "UNGROUNDED_NUMBER",
                    "value": number,
                    "reason": "경험 원문에 없는 숫자입니다.",
                })
        keywords = item["keywords"]
        for phrase in generic_phrases:
            if phrase in text and phrase not in keywords:
                issues.append({
                    "item_id": item_id,
                    "code": "GENERIC_PHRASE",
                    "value": phrase,
                    "reason": "등록된 정형 표현과 일치합니다.",
                })
        matched = next(
            (keyword for keyword in keywords if keyword.casefold() in text.casefold()),
            None,
        )
        status = "충족" if matched else "미충족"
        results.append({
            "item_id": item_id,
            "status": status,
            "reason": _item_reason(matched, is_career),
            "score": {"earned": max_points if matched else 0, "max": max_points},
            "matched_keywords": [keyword for keyword in keywords if keyword.casefold() in text.casefold()],
            "missing_keywords": [keyword for keyword in keywords if keyword.casefold() not in text.casefold()],
            "checks": [numeric_check],
        })

    feedback = _build_feedback(results, issues)
    result = {
        "schema_version": 2,
        "case_id": case_id,
        "style_id": style_id,
        "attempt": attempt,
        "items": results,
        "issues": issues,
        "feedback": feedback,
        "needs_revision": bool(issues) or any(item["status"] != "충족" for item in results),
    }
    result["attempt_id"] = attempt_id
    return result


def _records_by_item_id(records: Any, label: str, id_field: str) -> dict[str, dict[str, Any]]:
    """항목 레코드 목록을 받아 유효한 고유 item_id 기준 사전으로 반환한다."""
    if not isinstance(records, list):
        raise ValueError(f"{label}은 목록이어야 합니다.")
    result = {}
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"{label}[{position}]은 객체여야 합니다.")
        item_id = record.get(id_field)
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError(f"{label}[{position}].{id_field}가 필요합니다.")
        if item_id in result:
            raise ValueError(f"{label}에 중복 item_id가 있습니다: {item_id}")
        result[item_id] = record
    return result


def _number_tokens(text: str, *, ignore_career_years: bool = False) -> list[str]:
    """문장에서 쉼표를 포함한 연속 숫자 덩어리를 찾아 목록으로 반환한다."""
    result = []
    for match in re.finditer(r"\d+(?:,\d+)*(?:%)?", text):
        if ignore_career_years and re.match(r"\s*년(?:\s*(?:이상|이하|간))?", text[match.end():]):
            continue
        result.append(match.group())
    return result


def _normalize_number(number: str) -> str:
    """표시 숫자를 받아 쉼표와 퍼센트 기호를 제거한 비교값을 반환한다."""
    return number.replace(",", "").replace("%", "")


def _generic_phrases() -> list[str]:
    """AI 표현 목록 파일을 읽어 빈 줄과 주석을 뺀 문구 목록을 반환한다."""
    path = Path(__file__).with_name("ai_phrases.txt")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _style_id(rewrite: dict[str, Any]) -> str:
    """rewrite의 한글 스타일 또는 style_id를 받아 합의된 식별자를 반환한다."""
    styles = {
        "성과 강조형": "achievement",
        "키워드 맞춤형": "keyword",
        "간결형": "concise",
    }
    value = rewrite.get("style_id", rewrite.get("style"))
    if not isinstance(value, str):
        raise ValueError("rewrite.style_id는 achievement, keyword, concise 중 하나여야 합니다.")
    result = styles.get(value, value)
    if result not in {"achievement", "keyword", "concise"}:
        raise ValueError("rewrite.style_id는 achievement, keyword, concise 중 하나여야 합니다.")
    return result


def _item_reason(matched_keyword: str | None, is_career: bool) -> str:
    """키워드 판정과 연수 항목 여부를 받아 고정된 사용자용 이유를 반환한다."""
    reason = (
        f"'{matched_keyword}' 키워드가 결과 문안에 있습니다."
        if matched_keyword
        else "결과 문안에 체크리스트 키워드가 없습니다."
    )
    return _career_note(reason, is_career)


def _career_note(reason: str, is_career: bool) -> str:
    """기본 판정 이유와 경력 여부를 받아 필요한 연수 미확인 문구를 반환한다."""
    return f"{reason} 연수 미확인." if is_career else reason


def _max_item_points(item: dict[str, Any]) -> int:
    """체크리스트 항목을 받아 필수 10점 또는 우대 5점을 반환한다."""
    level = item.get("level")
    if level == "필수":
        return 10
    if level == "우대":
        return 5
    raise ValueError(f"checklist.items[{item.get('id')}].level은 필수 또는 우대여야 합니다.")


def _numeric_evidence_check(source: str) -> dict[str, str]:
    """경험 원문을 받아 수치 근거 유무와 화면 표시 이유를 반환한다."""
    has_numeric_evidence = bool(_number_tokens(source))
    return {
        "code": "NUMERIC_EVIDENCE_PRESENT",
        "result": "pass" if has_numeric_evidence else "fail",
        "reason": (
            "경험 원문에 수치 근거가 있습니다."
            if has_numeric_evidence
            else "경험 원문에 수치 근거가 없습니다. 점수에는 반영하지 않습니다."
        ),
    }


def _build_feedback(items: list[dict[str, Any]], issues: list[dict[str, str]]) -> str:
    """채점 항목과 품질 경고를 받아 rewrite loop에 전달할 고정 피드백을 반환한다."""
    messages = [
        f"{item['item_id']}: {item['reason']}"
        for item in items
        if item["status"] != "충족"
    ]
    messages.extend(
        f"{issue['item_id']}: {issue['value']} — {issue['reason']}"
        for issue in issues
    )
    return "\n".join(messages)
