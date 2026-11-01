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

from loop.data_contracts import validate_document
from loop.call_llm import call_llm


SCHEMA_PATH = ROOT / "schemas" / "parsing" / "checklist.json"
LLM_SCHEMA_PATH = ROOT / "schemas" / "parsing" / "checklist.llm.schema.json"
PROMPT_PATH = ROOT / "prompts" / "parsing_checklist_v1.md"
PROMPT_VERSION = "parsing_checklist_v1"
CASES_DIR = ROOT / "data" / "cases"
CASE_ID_PATTERN = re.compile(r"^case-\d+$")

def parse_input_sections(input_text: str) -> tuple[str, str]:
    """회사정보와 공고가 적힌 문자열을 받아 두 구역의 내용을 돌려준다."""
    headings = [
        line.strip()
        for line in input_text.splitlines()
        if line.strip() in {"회사정보", "공고"}
    ]
    if not headings:
        raise ValueError("입력에 '공고' 제목이 없습니다.")
    first_heading_index = next(
        index
        for index, line in enumerate(input_text.splitlines())
        if line.strip() in {"회사정보", "공고"}
    )
    if any(line.strip() for line in input_text.splitlines()[:first_heading_index]):
        raise ValueError("첫 번째 제목보다 앞에 있는 내용을 제거해주세요.")
    if headings.count("회사정보") > 1:
        raise ValueError("입력에는 '회사정보' 제목을 두 번 이상 쓸 수 없습니다.")
    if headings.count("공고") != 1:
        raise ValueError("입력에는 '공고' 제목이 한 번 있어야 합니다.")
    if headings not in (["공고"], ["회사정보", "공고"]):
        raise ValueError("입력 제목은 '회사정보' 다음에 '공고' 순서여야 합니다.")

    sections: dict[str, list[str]] = {"회사정보": [], "공고": []}
    current_section: str | None = None

    for line in input_text.splitlines():
        heading = line.strip()
        if heading in sections:
            current_section = heading
            continue
        if current_section is not None:
            sections[current_section].append(line)

    company_info = "\n".join(sections["회사정보"]).strip()
    job_posting = "\n".join(sections["공고"]).strip()
    if not job_posting:
        raise ValueError("'공고' 구역에 내용이 없습니다.")
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
        llm_items.append(item)
    checklist["items"] = assign_item_ids(llm_items)
    return checklist


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
    case_dir = CASES_DIR / case_id
    output_path = case_dir / "checklist.json"
    if output_path.exists():
        raise FileExistsError(f"결과 파일이 이미 있습니다: {output_path}")

    llm_schema = json.loads(LLM_SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = build_prompt(input_text)
    parsed = call_llm(prompt, llm_schema)

    if not isinstance(parsed, dict):
        raise ValueError("LLM 결과는 JSON 객체여야 합니다.")
    company_info, _ = parse_input_sections(input_text)
    checklist = merge_llm_result(checklist, parsed, company_info)

    case_dir.mkdir(parents=True, exist_ok=True)
    validate_document(output_path, checklist, SCHEMA_PATH)
    with output_path.open("x", encoding="utf-8") as output_file:
        json.dump(checklist, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")

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
        input_path = Path(args.input_txt)
        try:
            input_text = input_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError(f"{input_path}: UTF-8 TXT 파일이 아닙니다.") from error
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
