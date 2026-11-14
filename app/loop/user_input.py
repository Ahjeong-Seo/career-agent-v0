"""터미널 입력에 섞인 제어 문자와 잘못된 유니코드를 정리한다."""

import re


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_INVALID_UNICODE = re.compile(r"[\ud800-\udfff]")


def clean_terminal_input(value: str) -> str:
    """입력 문자열을 받아 터미널 제어 코드와 인코딩 불가 문자를 뺀 문자열을 돌려준다."""
    value = _ANSI_ESCAPE.sub("", value)
    value = value.replace("\x1b", "")
    return _INVALID_UNICODE.sub("", value)
