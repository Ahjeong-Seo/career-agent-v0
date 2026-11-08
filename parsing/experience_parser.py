"""사용자 경험 텍스트를 샘플 JSON 구조로 변환한다."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsing.common import (
    get_case_directory,
    read_input_text,
    write_json_document,
)


SCHEMA_PATH = ROOT / "schemas" / "parsing" / "experience.json"


_ITEM_ID = re.compile(r"\A(req-\d+)\s*[:：]", re.IGNORECASE)
_NUMBERED_SECTION = re.compile(r"(?m)^\s*(\d+(?:\.\d+)*\.?)\s+([^\n]+)$")
_EXPERIENCE_TITLE = re.compile(
    r"(?i)(experience|career|employment|project|경력|경험|프로젝트|업무|활동)"
)
_SECTION_TITLE = re.compile(
    r"(?im)^\s*(?:work\s+|side\s+|other\s+)?(?:experiences?|career|employment|"
    r"projects?|경력(?:\s*사항)?|경험(?:\s*사항)?|프로젝트|주요\s*업무)\.?\s*$"
)
_ROLE_DATE = re.compile(
    r"(?im)^\s*[^\n/]+/[^\n]*(?:(?:19|20)\d{2}[./-]|\bCEO\s*$)"
)
_TIMELINE_MARKER = re.compile(r"(?m)^\s*[🔹◆▪️]\s*[^\n]*(?:19|20)\d{2}[^\n]*$")


def parse_experience(text: str, case_id: str = "case-01") -> dict:
    """이력서 원문과 케이스 ID를 받아 경험 경계별 원문 목록을 반환한다."""
    experiences = _parse_numbered_sections(text)
    if not experiences:
        experiences = _parse_role_section(text)
    if not experiences:
        experiences = _parse_timeline_sections(text)
    if not experiences:
        experiences = _parse_fallback_section(text)

    experiences = _remove_heading_only_items(experiences)
    experiences = _assign_item_ids(experiences)
    return {"case_id": case_id, "schema_version": 2, "experiences": experiences}


def _parse_numbered_sections(text: str) -> list[dict[str, str]]:
    """원문을 받아 번호가 붙은 경험 절의 표 행 목록을 반환한다."""
    experiences: list[dict[str, str]] = []
    numbered_sections = list(_NUMBERED_SECTION.finditer(text))
    relevant_numbered_sections = [
        (index, heading)
        for index, heading in enumerate(numbered_sections)
        if _EXPERIENCE_TITLE.search(heading.group(2))
    ]
    for index, heading in relevant_numbered_sections:
        end = (
            numbered_sections[index + 1].start()
            if index + 1 < len(numbered_sections)
            else len(text)
        )
        for line in text[heading.end():end].splitlines():
            row = line.strip()
            if "\t" not in row:
                continue
            columns = [part.strip() for part in row.split("\t") if part.strip()]
            if len(columns) < 2 or columns[0].casefold() in {"company", "project"}:
                continue
            experiences.append(
                {"item_id": f"req-{len(experiences) + 1}", "text": " | ".join(columns)}
            )
    return experiences


def _parse_role_section(text: str) -> list[dict[str, str]]:
    """경력 구역이 있는 원문을 받아 역할별 또는 회사별 경험 항목을 반환한다."""
    section_match = _SECTION_TITLE.search(text)
    if not section_match:
        return []

    tail = text[section_match.end():]
    next_heading = re.search(
        r"(?im)^\s*(?:other\s+experience|skills?|education|소개|학력|수상)\.?\s*$",
        tail,
    )
    section = tail[:next_heading.start()] if next_heading else tail
    starts = list(_ROLE_DATE.finditer(section))
    experiences = _parse_company_role_groups(section, starts)
    if not experiences:
        experiences = _split_role_entries(section, starts)

    other_experience = _parse_other_experience(tail, next_heading)
    if other_experience:
        experiences.append(
            {"item_id": f"req-{len(experiences) + 1}", "text": other_experience}
        )
    return experiences


def _split_role_entries(
    section: str, starts: list[re.Match[str]]
) -> list[dict[str, str]]:
    """경력 구역과 역할 시작점을 받아 원문을 역할별 항목으로 반환한다."""
    experiences = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(section)
        content_start = 0 if index == 0 else start.start()
        content = section[content_start:end].strip()
        if content:
            experiences.append(
                {"item_id": f"req-{len(experiences) + 1}", "text": content}
            )
    return experiences


def _parse_other_experience(
    tail: str, heading: re.Match[str] | None
) -> str | None:
    """경력 구역 뒤의 Other Experience 구간을 받아 제목을 포함한 문자열을 반환한다."""
    if not heading or not re.fullmatch(
        r"(?i)other\s+experience\.?", heading.group().strip()
    ):
        return None

    other_tail = tail[heading.end():]
    end_heading = re.search(
        r"(?im)^\s*(?:skills?|education|학력|기술스택)\.?\s*$",
        other_tail,
    )
    other_text = other_tail[:end_heading.start()] if end_heading else other_tail
    other_text = other_text.strip()
    return f"Other Experience.\n{other_text}" if other_text else None


def _parse_timeline_sections(text: str) -> list[dict[str, str]]:
    """연도별 글머리표가 있는 원문을 받아 타임라인과 보조 구간을 반환한다."""
    markers = list(_TIMELINE_MARKER.finditer(text))
    experiences = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        content = text[marker.start():end].strip()
        experiences.extend(_split_timeline_content(content))
    return experiences


def _split_timeline_content(content: str) -> list[dict[str, str]]:
    """타임라인 내용 한 구간을 받아 본문·성과 요약·상시 운영 항목으로 나눈다."""
    if not content:
        return []

    summary_match = re.search(r"(?m)^\s*📊 누적 성과 요약[^\n]*\n", content)
    operations_match = re.search(r"(?m)^\s*🗂 상시 운영 영역[^\n]*\n", content)
    section_starts = [
        match.start()
        for match in (summary_match, operations_match)
        if match is not None
    ]
    main_end = min(section_starts, default=len(content))

    sections = [content[:main_end].strip()]
    if summary_match:
        summary_end = (
            operations_match.start()
            if operations_match and operations_match.start() > summary_match.start()
            else len(content)
        )
        sections.append(content[summary_match.start():summary_end].strip())
    if operations_match:
        sections.append(content[operations_match.start():].strip())

    return [
        {"item_id": f"req-{index}", "text": section}
        for index, section in enumerate((part for part in sections if part), start=1)
    ]


def _parse_fallback_section(text: str) -> list[dict[str, str]]:
    """경험 제목을 찾고 빈 줄로 나눈 원문 블록을 경험 목록으로 반환한다."""
    lines = text.splitlines()
    section_start = next(
        (index for index, line in enumerate(lines) if _SECTION_TITLE.match(line)),
        None,
    )
    if section_start is None:
        return []

    section_end = len(lines)
    for index in range(section_start + 1, len(lines)):
        line = lines[index].strip()
        if line and re.match(r"(?i)^(skills?|education|awards?|학력|수상|기술스택)\.?$", line):
            section_end = index
            break

    section_text = "\n".join(lines[section_start + 1:section_end])
    experiences = []
    for block in re.split(r"\n\s*\n", section_text):
        content = block.strip()
        if content:
            experiences.append(
                {"item_id": f"req-{len(experiences) + 1}", "text": content}
            )
    return experiences


def _remove_heading_only_items(
    experiences: list[dict[str, str]],
) -> list[dict[str, str]]:
    """경험 목록에서 제목만 있는 구분 항목을 제외한 목록을 반환한다."""
    return [
        item for item in experiences
        if not _SECTION_TITLE.fullmatch(item["text"].strip())
    ]


def _assign_item_ids(experiences: list[dict[str, str]]) -> list[dict[str, str]]:
    """경험 목록을 받아 순서대로 ID를 붙이고 원문 지정 ID는 보존해 반환한다."""
    for index, item in enumerate(experiences, start=1):
        item["item_id"] = f"req-{index}"
        item_match = _ITEM_ID.match(item["text"])
        if item_match:
            item["item_id"] = item_match.group(1)
            item["text"] = item["text"][item_match.end():]
    return experiences


def _parse_company_role_groups(
    section: str, starts: list[re.Match[str]]
) -> list[dict[str, str]]:
    """경력 구역과 역할 시작점을 받아 회사별로 묶은 경험 항목을 돌려준다."""
    if not starts:
        return []

    initial_prefix = section[:starts[0].start()]
    initial_lines = [
        line.strip() for line in initial_prefix.splitlines() if line.strip()
    ]
    if not initial_lines or len(initial_lines[0]) > 60:
        return []

    company = initial_lines[0]
    leading_dates = [
        line
        for line in initial_lines[1:]
        if re.search(r"(?:19|20)\d{2}[./-]", line)
    ]
    grouped_text = [company, *leading_dates]
    groups: list[dict[str, str]] = []

    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(section)
        raw_role_text = section[start.start():end]
        role_text = raw_role_text.strip()
        next_company = None
        if index + 1 < len(starts):
            boundary = raw_role_text.rfind("\n\n")
            if boundary >= 0:
                suffix = raw_role_text[boundary:].strip()
            else:
                suffix = "\n".join(raw_role_text.splitlines()[-2:]).strip()
            candidate = _company_header(suffix)
            if candidate:
                next_company = candidate[0]
                if boundary >= 0:
                    role_text = raw_role_text[:boundary].strip()
                else:
                    role_text = "\n".join(raw_role_text.splitlines()[:-2]).strip()

        if role_text:
            role_text = _remove_inline_company_description(role_text)
            grouped_text.append(role_text)
        if next_company:
            content = "\n".join(part for part in grouped_text if part).strip()
            if content:
                groups.append({"item_id": f"req-{len(groups) + 1}", "text": content})
            company = next_company
            grouped_text = [company]

    content = "\n".join(part for part in grouped_text if part).strip()
    if content:
        groups.append({"item_id": f"req-{len(groups) + 1}", "text": content})
    return groups if len(groups) > 1 else []


def _company_header(block: str) -> tuple[str, list[str]] | None:
    """회사 소개 경계 후보 문자열을 받아 회사 제목과 뒤 문장을 반환한다."""
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines or len(lines) > 3 or len(lines[0]) > 60:
        return None
    if _ROLE_DATE.fullmatch(lines[0]) or _SECTION_TITLE.fullmatch(lines[0]):
        return None
    if len(lines) == 1 or len(lines[1]) >= max(20, len(lines[0]) * 2):
        return lines[0], lines[1:]
    return None


def _remove_inline_company_description(role_text: str) -> str:
    """역할 제목 뒤의 회사명과 소개 문장 형식을 받아 소개 문장만 뺀 내용을 돌려준다."""
    lines = role_text.splitlines()
    for index in range(len(lines) - 2):
        if not _ROLE_DATE.match(lines[index].strip()):
            continue
        company_line = lines[index + 1].strip()
        description_line = lines[index + 2].strip()
        if (
            company_line
            and len(company_line) <= 60
            and len(description_line) >= max(40, len(company_line) * 2)
        ):
            del lines[index + 2]
            break
    return "\n".join(lines).strip()


def save_experience(text: str, case_id: str) -> Path:
    """이력서 원문과 케이스 ID를 받아 검증된 experience.json을 저장하고 경로를 돌려준다."""
    experience = parse_experience(text, case_id)
    case_dir = get_case_directory(case_id)
    output_path = case_dir / "experience.json"
    return write_json_document(output_path, experience, SCHEMA_PATH)


def convert_sample_files(samples_dir: Path | str = Path("samples")) -> list[Path]:
    """샘플 원문 파일을 읽어 스키마 형식의 JSON 파일 경로 목록으로 저장한다."""
    directory = Path(samples_dir)
    outputs = []
    for source_path in sorted(directory.glob("experience.sample._*.txt")):
        match = re.search(r"_(\d+)\.txt\Z", source_path.name)
        if not match:
            continue
        resume_number = match.group(1)
        result = parse_experience(
            read_input_text(source_path),
            case_id=f"case-{int(resume_number):02d}",
        )
        if not result["experiences"]:
            print(f"경험 구역을 인식하지 못했습니다: {source_path}")
        output_path = directory / f"experience.sample.{resume_number}.json"
        outputs.append(
            write_json_document(output_path, result, SCHEMA_PATH, overwrite=True)
        )
    return outputs


def main(argv: Sequence[str] | None = None) -> None:
    """이력서 TXT 경로와 케이스 ID를 받아 experience.json을 저장하고 경로를 출력한다."""
    parser = argparse.ArgumentParser(description="이력서 TXT에서 경험 JSON을 생성합니다.")
    parser.add_argument("input_txt", help="이력서 TXT 파일 경로")
    parser.add_argument(
        "case_id",
        nargs="?",
        default="case-01",
        help="케이스 ID (기본값: case-01)",
    )
    args = parser.parse_args(argv)
    try:
        output_path = save_experience(read_input_text(args.input_txt), args.case_id)
    except Exception as error:
        parser.exit(status=1, message=f"오류: {type(error).__name__}: {error}\n")
    print(output_path)


if __name__ == "__main__":
    main()
