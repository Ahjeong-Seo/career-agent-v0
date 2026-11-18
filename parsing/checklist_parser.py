"""공고 TXT를 체크리스트 JSON으로 변환하는 명령행 파서다."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loop.call_llm import call_llm
from parsing.common import (
    CASE_ID_PATTERN,
    get_case_directory,
    read_input_text,
    sanitize_json_strings,
    write_json_document,
)


SCHEMA_PATH = ROOT / "schemas" / "parsing" / "checklist.json"
LLM_SCHEMA_PATH = ROOT / "schemas" / "parsing" / "checklist.llm.schema.json"
PROMPT_PATH = ROOT / "prompts" / "parsing_checklist_v3.md"
PROMPT_VERSION = "parsing_checklist_v3"

def parse_input_sections(input_text: str) -> tuple[str, str]:
    """회사정보와 공고가 적힌 문자열을 받아 두 구역의 내용을 돌려준다."""
    job_headings = {"공고", "채용공고"}
    headings = [
        line.strip()
        for line in input_text.splitlines()
        if line.strip() == "회사정보" or line.strip() in job_headings
    ]
    if not headings:
        raise ValueError("입력에 '채용공고' 제목이 없습니다.")
    first_heading_index = next(
        index
        for index, line in enumerate(input_text.splitlines())
        if line.strip() == "회사정보" or line.strip() in job_headings
    )
    if any(line.strip() for line in input_text.splitlines()[:first_heading_index]):
        raise ValueError("첫 번째 제목보다 앞에 있는 내용을 제거해주세요.")
    if headings.count("회사정보") > 1:
        raise ValueError("입력에는 '회사정보' 제목을 두 번 이상 쓸 수 없습니다.")
    if sum(heading in job_headings for heading in headings) != 1:
        raise ValueError("입력에는 '채용공고' 제목이 한 번 있어야 합니다.")
    normalized_headings = ["공고" if heading in job_headings else heading for heading in headings]
    if normalized_headings not in (["공고"], ["회사정보", "공고"]):
        raise ValueError("입력 제목은 '회사정보' 다음에 '채용공고' 순서여야 합니다.")

    sections: dict[str, list[str]] = {"회사정보": [], "공고": []}
    current_section: str | None = None

    for line in input_text.splitlines():
        heading = line.strip()
        if heading == "회사정보" or heading in job_headings:
            current_section = "공고" if heading in job_headings else heading
            continue
        if current_section is not None:
            sections[current_section].append(line)

    company_info = "\n".join(sections["회사정보"]).strip()
    job_posting = "\n".join(sections["공고"]).strip()
    if not job_posting:
        raise ValueError("'채용공고' 구역에 내용이 없습니다.")
    return company_info, job_posting


def build_prompt(input_text: str) -> str:
    """입력 문자열을 받아 버전이 지정된 기본 프롬프트와 결합해 돌려준다."""
    company_info, job_posting = parse_input_sections(input_text)
    base_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    return (
        f"{base_prompt}\n\n"
        "## 분석할 입력\n"
        "### 회사정보\n"
        f"{company_info or '(제공된 회사 정보 없음)'}\n\n"
        "### 공고\n"
        f"{job_posting}"
    )


def create_json(case_id: str) -> dict[str, Any]:
    """호출부가 정한 case_id를 받아 최종 체크리스트의 기본 JSON 객체를 돌려준다."""
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError("case_id는 'case-숫자' 형식이어야 합니다.")
    return {
        "case_id": case_id,
        "schema_version": 2,
        "job_title": None,
        "company_values": [],
        "items": [],
        "reviewed": False,
    }


def assign_item_ids(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """체크리스트 항목 목록을 받아 순서에 맞는 req ID를 붙인 목록을 돌려준다."""
    return [{**item, "id": f"req-{index}"} for index, item in enumerate(items, start=1)]


def merge_llm_result(
    checklist: dict[str, Any], parsed: dict[str, Any], company_info: str
) -> dict[str, Any]:
    """기본 체크리스트와 LLM 결과를 받아 코드 소유 필드를 유지한 병합 객체를 돌려준다."""
    if not isinstance(parsed.get("items"), list):
        raise ValueError("LLM 결과의 'items'는 배열이어야 합니다.")

    checklist["job_title"] = parsed["job_title"]
    checklist["company_values"] = parsed["company_values"] if company_info else []
    llm_items: list[dict[str, Any]] = []
    for index, item in enumerate(parsed["items"]):
        if not isinstance(item, dict):
            raise ValueError(f"LLM 결과의 items[{index}]는 객체여야 합니다.")
        clean_item = dict(item)
        if isinstance(clean_item.get("text"), str):
            clean_item["text"] = clean_item["text"].replace("\u200b", "")
        if clean_item.get("type") == "경력":
            keywords = clean_item.get("keywords", [])
            specific_keywords = [
                keyword
                for keyword in keywords
                if not _is_generic_career_keyword(keyword)
            ]
            if not specific_keywords:
                raise ValueError(
                    f"LLM 결과의 items[{index}].keywords에는 '경력', '년', '이상' "
                    "같은 일반어 대신 직무나 기술 키워드가 필요합니다."
                )
            clean_item["keywords"] = specific_keywords
        llm_items.append(clean_item)
    checklist["items"] = assign_item_ids(_deduplicate_items(llm_items))
    return checklist


def _deduplicate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """체크리스트 후보를 받아 중복 요구사항을 줄이고 대표 항목 목록을 반환한다."""
    unique_items: list[dict[str, Any]] = []
    for item in items:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(unique_items)
                if _are_duplicate_requirements(existing, item)
            ),
            None,
        )
        if duplicate_index is None:
            unique_items.append(item)
            continue
        if _requirement_detail_score(item) > _requirement_detail_score(
            unique_items[duplicate_index]
        ):
            unique_items[duplicate_index] = item
    return unique_items


def _are_duplicate_requirements(
    first: dict[str, Any], second: dict[str, Any]
) -> bool:
    """두 체크리스트 항목을 받아 동일하거나 한쪽이 구체화된 같은 요건인지 반환한다."""
    if any(
        first.get(field) != second.get(field)
        for field in ("type", "level", "years")
    ):
        return False

    first_text = _normalize_requirement_text(first.get("text"))
    second_text = _normalize_requirement_text(second.get("text"))
    if not first_text or not second_text:
        return False
    if first_text == second_text:
        return True

    first_keywords = {
        _normalize_requirement_text(keyword)
        for keyword in first.get("keywords", [])
        if isinstance(keyword, str) and keyword.strip()
    }
    second_keywords = {
        _normalize_requirement_text(keyword)
        for keyword in second.get("keywords", [])
        if isinstance(keyword, str) and keyword.strip()
    }
    if not first_keywords or not second_keywords:
        return False
    if not (first_keywords <= second_keywords or second_keywords <= first_keywords):
        return False
    shorter_text, longer_text = sorted((first_text, second_text), key=len)
    return shorter_text in longer_text


def _normalize_requirement_text(value: Any) -> str:
    """요건 문구나 키워드를 받아 문자·숫자만 남긴 비교용 문자열을 반환한다."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).casefold()


def _requirement_detail_score(item: dict[str, Any]) -> tuple[int, int]:
    """체크리스트 항목을 받아 키워드 수와 문구 길이로 구체성 점수를 반환한다."""
    keywords = {
        _normalize_requirement_text(keyword)
        for keyword in item.get("keywords", [])
        if isinstance(keyword, str) and keyword.strip()
    }
    text = item.get("text")
    text_length = len(text) if isinstance(text, str) else 0
    return len(keywords), text_length


def _is_generic_career_keyword(keyword: Any) -> bool:
    """경력 연수 항목의 키워드 값을 받아 일반적인 연수 표현인지 반환한다."""
    if not isinstance(keyword, str):
        return False
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "", keyword).casefold()
    normalized = re.sub(r"\d+", "", normalized)
    generic_keywords = {
        "경력",
        "경력년",
        "년경력",
        "경력연수",
        "연수",
        "연차",
        "년",
        "년이상",
        "이상",
        "근무기간",
        "재직기간",
        "year",
        "years",
        "experience",
        "workexperience",
    }
    return normalized in generic_keywords


def _record_prompt_version(case_id: str, result_path: Path) -> None:
    """케이스 ID와 결과 경로를 받아 프롬프트 버전을 호출 로그에 추가하고 None을 돌려준다."""
    cache_dir = ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "event": "checklist_parser",
        "prompt_version": PROMPT_VERSION,
        "case_id": case_id,
        "result_file": str(result_path.relative_to(ROOT)),
    }
    with (cache_dir / "calls.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_checklist(input_text: str, case_id: str) -> tuple[dict[str, Any], Path]:
    """공고 TXT 문자열과 호출부가 정한 case_id를 받아 검증된 체크리스트와 저장 경로를 돌려준다."""
    checklist = create_json(case_id)
    case_dir = get_case_directory(case_id)
    output_path = case_dir / "checklist.json"
    if output_path.exists():
        raise FileExistsError(f"결과 파일이 이미 있습니다: {output_path}")

    llm_schema = json.loads(LLM_SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = build_prompt(input_text)
    company_info, _ = parse_input_sections(input_text)
    for attempt in range(2):
        parsed = call_llm(prompt, llm_schema)
        if not isinstance(parsed, dict):
            raise ValueError("LLM 결과는 JSON 객체여야 합니다.")
        try:
            checklist = merge_llm_result(checklist, parsed, company_info)
            break
        except ValueError as error:
            if attempt == 1:
                raise
            prompt = (
                f"{prompt}\n\n"
                "## 재시도 지시\n"
                "직전 결과의 경력 항목 keywords에 일반적인 연수 표현만 있거나 "
                "형식 검증에 실패했습니다. 공고의 직무명·담당업무에서 직무 또는 "
                "기술을 나타내는 구체 키워드를 선택하고 오류를 고쳐 JSON만 반환하세요.\n"
                f"검증 오류: {error}"
            )

    checklist = sanitize_json_strings(checklist)
    write_json_document(
        output_path, checklist, SCHEMA_PATH, sanitize_strings=True
    )

    _record_prompt_version(checklist["case_id"], output_path)
    return checklist, output_path


def main(argv: Sequence[str] | None = None) -> None:
    """명령행 인자를 받아 TXT를 읽고 결과 JSON 파일을 저장한 뒤 경로를 출력한다."""
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="회사 정보와 공고 TXT에서 체크리스트 JSON을 생성합니다."
    )
    parser.add_argument("input_txt", help="회사정보와 공고가 포함된 TXT 파일 경로")
    parser.add_argument(
        "case_id",
        nargs="?",
        default="case-01",
        help="케이스 ID (기본값: case-01)",
    )
    args = parser.parse_args(argv)

    stage = "TXT 파일 읽기"
    try:
        input_text = read_input_text(args.input_txt)
        stage = "체크리스트 생성 및 JSON 저장"
        _, output_path = parse_checklist(input_text, args.case_id)
    except Exception as error:
        message = (
            f"오류: {stage} 중 실패했습니다.\n"
            f"원인: {type(error).__name__}: {error}\n"
        )

        print(message)
        time.sleep(5)
        parser.exit(status=1)

    print(output_path)


if __name__ == "__main__":
    main()
