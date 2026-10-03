from openai_codex import Codex

with Codex() as codex:
	thread = codex.thread_start()
	result = thread.run(
			"이력서 첨삭 팀에게 한 줄로 인사해줘"
			)
	print(result.final_response)

