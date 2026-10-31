"""Codex CLI를 통해 구조화된 JSON 답변을 받는 공통 진입점."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache"


def call_llm(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    """프롬프트와 JSON 스키마를 받아 Codex의 JSON 답변을 돌려준다."""
    cache_key = hashlib.sha256(
        json.dumps(
            {"prompt": prompt, "schema": schema},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cache_path = CACHE_DIR / f"{cache_key}.json"
    started = time.monotonic()

    if cache_path.exists():
        answer = json.loads(cache_path.read_text(encoding="utf-8"))
        _record_call(cache_key, 0, time.monotonic() - started, cached=True)
        return answer

    codex = shutil.which("codex")
    if codex is None:
        raise RuntimeError("Codex CLI를 찾을 수 없습니다. codex 명령을 설치해 주세요.")

    last_error = "알 수 없는 오류"
    for attempt in range(1, 3):
        try:
            # 저장소 밖의 빈 폴더에서 실행해 프로젝트 지침이 이력서 문장에 섞이지 않게 한다.
            with tempfile.TemporaryDirectory(prefix="career-codex-") as directory:
                workdir = Path(directory)
                schema_path = workdir / "schema.json"
                answer_path = workdir / "answer.json"
                schema_path.write_text(
                    json.dumps(schema, ensure_ascii=False), encoding="utf-8"
                )
                completed = subprocess.run(
                    [
                        codex,
                        "exec",
                        "-C",
                        str(workdir),
                        "--skip-git-repo-check",
                        "--ephemeral",
                        "--sandbox",
                        "read-only",
                        "--output-schema",
                        str(schema_path),
                        "--output-last-message",
                        str(answer_path),
                        "-",
                    ],
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=180,
                    check=False,
                )
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or "Codex 실행 실패")
                answer = json.loads(answer_path.read_text(encoding="utf-8"))
                if not isinstance(answer, dict):
                    raise ValueError("Codex 답변이 JSON 객체가 아닙니다.")
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                _record_call(cache_key, attempt, time.monotonic() - started)
                return answer
        except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError) as error:
            last_error = str(error)

    _record_call(cache_key, 2, time.monotonic() - started, failed=True)
    raise RuntimeError(f"Codex 호출이 두 번 실패했습니다: {last_error}")


def _record_call(
    cache_key: str,
    attempts: int,
    elapsed_seconds: float,
    *,
    cached: bool = False,
    failed: bool = False,
) -> None:
    """캐시 키와 실행 횟수·시간을 받아 기록하고 아무 값도 돌려주지 않는다."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "cache_key": cache_key,
        "attempts": attempts,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "cached": cached,
        "failed": failed,
    }
    with (CACHE_DIR / "calls.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")