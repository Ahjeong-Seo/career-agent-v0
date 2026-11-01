"""공고와 이력서 TXT를 읽어 케이스별 체크리스트와 경험 JSON을 생성한다."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsing.checklist_parser import parse_checklist
from parsing.experience_parser import save_experience


CASES_DIR = ROOT / "data" / "cases"
CASE_ID_PATTERN = re.compile(r"^case-(\d+)$")


def read_input_text(path: str | Path) -> str:
    """TXT 파일 경로를 받아 UTF-8 문자열을 읽고 반환한다."""
    input_path = Path(path)
    try:
        return input_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{input_path}: UTF-8 TXT 파일이 아닙니다.") from error


def create_case_directory() -> str:
    """기존 케이스 폴더 중 가장 큰 번호 다음 ID를 정하고 폴더를 만든다."""
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    existing_numbers = [
        int(match.group(1))
        for child in CASES_DIR.iterdir()
        if child.is_dir() and (match := CASE_ID_PATTERN.fullmatch(child.name))
    ]
    next_number = max(existing_numbers, default=0) + 1

    while True:
        case_id = f"case-{next_number:02d}"
        case_dir = CASES_DIR / case_id
        try:
            case_dir.mkdir()
            return case_id
        except FileExistsError:
            next_number += 1


def run_pipeline(
    job_txt: str | Path, resume_txt: str | Path
) -> tuple[str, dict[str, Path], list[str]]:
    """공고·이력서 TXT 경로를 받아 두 파서를 실행하고 ID, 결과 경로, 오류를 반환한다."""
    job_text = read_input_text(job_txt)
    resume_text = read_input_text(resume_txt)
    case_id = create_case_directory()

    output_paths: dict[str, Path] = {}
    errors: list[str] = []

    try:
        _, output_paths["checklist"] = parse_checklist(job_text, case_id)
    except Exception as error:
        errors.append(f"checklist_parser_v1.py: {type(error).__name__}: {error}")

    try:
        output_paths["experience"] = save_experience(resume_text, case_id)
    except Exception as error:
        errors.append(f"experience_parser.py: {type(error).__name__}: {error}")

    return case_id, output_paths, errors


def main(argv: Sequence[str] | None = None) -> None:
    """공고 TXT와 이력서 TXT 경로를 받아 파이프라인을 실행하고 결과를 출력한다."""
    parser = argparse.ArgumentParser(
        description="공고 TXT와 이력서 TXT에서 케이스별 JSON 결과를 생성합니다."
    )
    parser.add_argument("job_txt", help="회사정보와 채용공고가 포함된 TXT 파일 경로")
    parser.add_argument("resume_txt", help="이력서 TXT 파일 경로")
    args = parser.parse_args(argv)

    try:
        case_id, output_paths, errors = run_pipeline(args.job_txt, args.resume_txt)
    except (OSError, ValueError) as error:
        parser.exit(status=1, message=f"오류: {error}\n")

    print(f"case_id: {case_id}")
    for name, output_path in output_paths.items():
        print(f"{name}: {output_path}")
    for error in errors:
        print(f"오류: {error}", file=sys.stderr)
    if errors:
        parser.exit(status=1)


if __name__ == "__main__":
    main()
