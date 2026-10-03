from dotenv import load_dotenv
import subprocess

r = subprocess.run(
    ["codex", "exec", "이력서 첨삭 팀에게 한 줄로 인사해줘"],
    capture_output=True, text=True, encoding="utf-8",
)
print(r.stdout)