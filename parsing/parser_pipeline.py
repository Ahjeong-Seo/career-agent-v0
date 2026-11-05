"""공고와 이력서 TXT를 읽어 케이스별 체크리스트와 경험 JSON을 생성한다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsing.checklist_parser import parse_checklist
from parsing.common import (
    create_case_directory,
    get_case_directory,
    read_input_text,
    write_text_file,
)
from parsing.experience_parser import save_experience


def run_pipeline_from_text(
    job_text: str, resume_text: str, case_id: str | None = None
) -> tuple[str, dict[str, Path], list[str]]:
    """공고·이력서 문자열을 받아 원문 TXT와 JSON을 저장하고 ID·경로·오류를 돌려준다."""
    input_error = _validate_pipeline_texts(job_text, resume_text)
    if input_error:
        return case_id or "", {}, [input_error]

    try:
        case_id, case_dir, case_directory_created = _prepare_case_directory(case_id)
    except (OSError, ValueError) as error:
        reported_case_id = case_id if isinstance(case_id, str) else ""
        return reported_case_id, {}, [
            f"케이스 폴더 준비 실패: {type(error).__name__}: {error}"
        ]

    output_paths, errors = _save_source_texts(case_dir, job_text, resume_text)
    if errors:
        if case_directory_created:
            cleanup_error = _remove_empty_case_directory(case_dir)
            if cleanup_error:
                errors.append(cleanup_error)
        return case_id, output_paths, errors

    errors = _run_parsers(job_text, resume_text, case_id, output_paths)
    return case_id, output_paths, errors


def _validate_pipeline_texts(job_text: str, resume_text: str) -> str | None:
    """공고·이력서 문자열을 받아 비어 있거나 문자열이 아닌 입력의 오류를 반환한다."""
    if not isinstance(job_text, str) or not job_text.strip():
        return "공고 TXT 내용이 비어 있거나 문자열이 아닙니다."
    if not isinstance(resume_text, str) or not resume_text.strip():
        return "이력서 TXT 내용이 비어 있거나 문자열이 아닙니다."
    return None


def _prepare_case_directory(case_id: str | None) -> tuple[str, Path, bool]:
    """선택적 케이스 ID를 받아 폴더 경로와 이번 호출의 신규 생성 여부를 반환한다."""
    if case_id is None:
        case_id = create_case_directory()
        return case_id, get_case_directory(case_id), True

    case_dir = get_case_directory(case_id)
    return case_id, case_dir, not case_dir.exists()


def _save_source_texts(
    case_dir: Path, job_text: str, resume_text: str
) -> tuple[dict[str, Path], list[str]]:
    """케이스 폴더와 두 원문을 받아 TXT 경로와 저장 오류를 반환한다."""
    source_files = (
        ("job_txt", case_dir / "jd.txt", job_text),
        ("resume_txt", case_dir / "resume.txt", resume_text),
    )
    output_paths: dict[str, Path] = {}
    errors: list[str] = []
    created_paths: list[Path] = []

    for name, path, content in source_files:
        existed_before = path.exists()
        try:
            output_paths[name] = write_text_file(path, content)
            created_paths.append(path)
        except FileExistsError as error:
            errors.append(f"원문 TXT 저장 실패 ({path}): {type(error).__name__}: {error}")
            break
        except OSError as error:
            if not existed_before and path.exists():
                created_paths.append(path)
            errors.append(f"원문 TXT 저장 실패 ({path}): {type(error).__name__}: {error}")
            break

    if errors:
        for path in created_paths:
            try:
                path.unlink(missing_ok=True)
                source_name = "job_txt" if path.name == "jd.txt" else "resume_txt"
                output_paths.pop(source_name, None)
            except OSError as error:
                errors.append(
                    f"부분 저장 파일 정리 실패 ({path}): "
                    f"{type(error).__name__}: {error}"
                )

    return output_paths, errors


def _remove_empty_case_directory(case_dir: Path) -> str | None:
    """이번 실행에서 만든 빈 케이스 폴더를 지우고 실패하면 오류 문장을 반환한다."""
    try:
        case_dir.rmdir()
    except OSError as error:
        return f"빈 케이스 폴더 정리 실패 ({case_dir}): {type(error).__name__}: {error}"
    return None


def _run_parsers(
    job_text: str,
    resume_text: str,
    case_id: str,
    output_paths: dict[str, Path],
) -> list[str]:
    """두 입력 문자열과 케이스 ID로 파서를 실행하고 각 파서 오류 목록을 반환한다."""
    errors = []

    try:
        _, output_paths["checklist"] = parse_checklist(job_text, case_id)
    except Exception as error:
        errors.append(f"checklist_parser.py: {type(error).__name__}: {error}")

    try:
        output_paths["experience"] = save_experience(resume_text, case_id)
    except Exception as error:
        errors.append(f"experience_parser.py: {type(error).__name__}: {error}")

    return errors


def run_pipeline_from_files(
    job_txt: str | Path, resume_txt: str | Path
) -> tuple[str, dict[str, Path], list[str]]:
    """공고·이력서 TXT 경로를 읽어 문자열 파이프라인에 전달하고 결과를 반환한다."""
    job_text = read_input_text(job_txt)
    resume_text = read_input_text(resume_txt)
    return run_pipeline_from_text(job_text, resume_text)


def main(argv: Sequence[str] | None = None) -> None:
    """공고 TXT와 이력서 TXT 경로를 받아 파이프라인을 실행하고 결과를 출력한다."""
    parser = argparse.ArgumentParser(
        description="공고 TXT와 이력서 TXT에서 케이스별 JSON 결과를 생성합니다."
    )
    parser.add_argument("job_txt", help="회사정보와 채용공고가 포함된 TXT 파일 경로")
    parser.add_argument("resume_txt", help="이력서 TXT 파일 경로")
    args = parser.parse_args(argv)

    try:
        case_id, output_paths, errors = run_pipeline_from_files(
            args.job_txt, args.resume_txt
        )
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
