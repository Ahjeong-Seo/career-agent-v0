"""Streamlit AppTest 실행 환경을 확인하는 테스트 보조 함수."""

from functools import lru_cache
import subprocess
import sys


@lru_cache(maxsize=1)
def streamlit_apptest_supported() -> bool:
    """현재 Python에서 제한 시간 안에 socketpair를 만들 수 있는지 확인해 결과를 반환한다."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import socket; left, right = socket.socketpair(); left.close(); right.close()",
            ],
            capture_output=True,
            check=False,
            timeout=2,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0
