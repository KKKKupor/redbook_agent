"""Tests for web_console.generate_stream — event sequence with injected fake agents."""

from web_console import generate_stream


def _frames(gen) -> list:
    import json
    events = []
    for frame in gen:
        assert frame.startswith("data: ")
        events.append(json.loads(frame[6:].strip()))
    return events


def _fake_agents():
    def nav(state):
        return {"dimension_defs": [{"id": "D1"}], "suggested_price": 1.99}

    def gen(state):
        return {"questions_json": {"questions": [{"id": 1}] * 3}}

    def pkg(state):
        return {"generated_html": "<html>x</html>", "packaging_text": "测测你"}

    def pub(state):
        return {"html_url": "https://example.test/d/2026-08-24/"}

    return {"navigator": nav, "generator": gen, "packager": pkg, "publisher": pub}


class TestGenerateStream:
    def test_event_sequence_and_done(self):
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}
        events = _frames(generate_stream(cmd, "test-ip", agents=_fake_agents()))
        kinds = [e["event"] for e in events]
        assert kinds == ["agent_start", "agent_done", "agent_start", "agent_done",
                         "agent_start", "agent_done", "step", "agent_start", "agent_done", "done"]
        assert kinds.count("agent_start") == 4
        done = events[-1]
        assert done["url"] == "https://example.test/d/2026-08-24/"
        assert done["cost"] >= 0

    def test_error_event_on_agent_failure(self):
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}
        agents = _fake_agents()
        def boom(state):
            raise ValueError("模拟失败")
        agents["generator"] = boom
        events = _frames(generate_stream(cmd, "test-ip", agents=agents))
        assert events[-1]["event"] == "error"
        assert "生成失败" in events[-1]["message"]
        assert "模拟失败" not in events[-1]["message"]  # 内部异常细节不外泄


class TestGenerateStreamThreadpool:
    def test_token_frames_survive_threadpool_iteration(self):
        import anyio
        from utils import stream_bus

        agents = _fake_agents()

        def nav(state):
            stream_bus.emit({"event": "token", "agent": "navigator", "text": "流式"})
            return {"dimension_defs": [{"id": "D1"}], "suggested_price": 1.99}

        agents["navigator"] = nav
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}

        async def main():
            gen = generate_stream(cmd, "test-ip", agents=agents)
            frames = []
            while True:
                frame = await anyio.to_thread.run_sync(next, gen, None)
                if frame is None:
                    break
                frames.append(frame)
            return frames

        frames = anyio.run(main)
        tokens = [f for f in frames if '"event": "token"' in f]
        assert len(tokens) >= 1, "token 帧在逐项线程池迭代下丢失"
