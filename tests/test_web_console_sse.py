"""Tests for web_console.generate_stream — event sequence with injected fake agents.

新架构:worker 线程跑链,SSE 生成器实时消费队列 —— token 帧必须在 agent 完成前到达。
"""

import threading
import time

from web_console import generate_stream, _local_quiz_url


def _frames(gen) -> list:
    import json
    events = []
    for frame in gen:
        if frame.startswith(": "):
            continue  # 心跳 comment 帧
        assert frame.startswith("data: ")
        events.append(json.loads(frame[6:].strip()))
    return events


def _fake_agents():
    def nav(state):
        return {"selected_topic": state.get("selected_topic") or "人格阴影测试",
                "dimension_defs": [{"id": "D1"}], "suggested_price": 1.99}

    def gen(state):
        return {"questions_json": {"questions": [{"id": 1}] * 3}}

    def pkg(state):
        return {"generated_html": "<html>x</html>", "packaging_text": "测测你"}

    def rev(state):
        return {"review_score": 7, "review_verdict": "approve",
                "review_retry_count": state.get("review_retry_count", 0), "review_fixes_needed": []}

    def aud(state):
        return {"audit_status": "pass", "audit_feedback": ""}

    def pub(state):
        return {"html_url": "https://example.test/d/2026-08-25/103000/",
                "cover_image_url": "https://example.test/d/2026-08-25/103000/cover.png",
                "result_image_url": "https://example.test/d/2026-08-25/103000/result.png",
                "product_image_url": "https://example.test/d/2026-08-25/103000/product.png"}

    return {"navigator": nav, "generator": gen, "packager": pkg,
            "reviewer": rev, "auditor": aud, "publisher": pub}


def _wait_for(predicate, timeout=5.0):
    """条件轮询等待(等待可观察状态,非猜竞态)。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestGenerateStream:
    def test_event_sequence_and_done(self):
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}
        events = _frames(generate_stream(cmd, "test-ip", agents=_fake_agents()))
        kinds = [e["event"] for e in events]
        # 六 agent:navigator/generator/packager/reviewer/auditor/publisher + step + done
        assert kinds == ["agent_start", "agent_done", "agent_start", "agent_done",
                         "agent_start", "agent_done", "agent_start", "agent_done",
                         "agent_start", "agent_done", "step", "agent_start", "agent_done", "done"]
        assert kinds.count("agent_start") == 6
        done = events[-1]
        assert done["url"] == "https://example.test/d/2026-08-25/103000/"
        assert done["cost"] >= 0
        assert done["post_materials"]["copy"] == "测测你"
        assert len(done["post_materials"]["images"]) == 3
        assert done["audit_warning"] == ""

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


class TestStreamingTimeliness:
    def test_tokens_reach_consumer_before_agent_done(self):
        """流式核心验收:agent 运行中途 emit 的 token,必须在 agent 完成前到达消费端。"""
        from utils import stream_bus

        agents = _fake_agents()
        token_seen = threading.Event()
        seen_before_release = {}

        def nav(state):
            stream_bus.emit({"event": "token", "agent": "navigator", "text": "思考中"})
            # 等消费端确认收到 token;若架构是"完成后一口气发",这里会等满 2s 超时
            seen_before_release["ok"] = token_seen.wait(2)
            return {"dimension_defs": [{"id": "D1"}], "suggested_price": 1.99}

        agents["navigator"] = nav
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}
        gen = generate_stream(cmd, "test-ip", agents=agents)
        for frame in gen:
            if '"event": "token"' in frame and '"agent": "navigator"' in frame:
                token_seen.set()

        assert seen_before_release.get("ok") is True, "token 帧没有在 agent 运行期间实时到达"

    def test_heartbeat_on_idle(self):
        """agent 长时间无输出时,消费端收到心跳 comment 帧保活。"""
        agents = _fake_agents()

        def slow_nav(state):
            time.sleep(0.35)
            return {"dimension_defs": [{"id": "D1"}], "suggested_price": 1.99}

        agents["navigator"] = slow_nav
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}
        pings = 0
        for frame in generate_stream(cmd, "test-ip", agents=agents, heartbeat_timeout=0.1):
            if frame.startswith(": ping"):
                pings += 1
        assert pings >= 1, "idle 期间没有心跳帧"


class TestRejectedShortCircuit:
    def test_rejected_navigator_skips_following_agents(self):
        """navigator 拒绝(题量超限/无关输入)→ 只发 navigator 帧与 done,后续 agent 不执行。"""
        agents = _fake_agents()
        called = []

        def gen(state):
            called.append("generator")
            return {"questions_json": {}}

        def pkg(state):
            called.append("packager")
            return {}

        def pub(state):
            called.append("publisher")
            return {}

        agents.update(generator=gen, packager=pkg, publisher=pub)
        agents["navigator"] = lambda state: {"rejected": True, "reply": "单次最多60题"}
        cmd = {"type": "generate", "topic": "测试", "question_count": 1000, "text": "做1000题"}

        events = _frames(generate_stream(cmd, "test-ip", agents=agents))
        kinds = [e["event"] for e in events]
        assert kinds == ["agent_start", "agent_done", "done"]
        done = events[-1]
        assert done["rejected"] is True
        assert done["reply"] == "单次最多60题"
        assert called == []

    def test_close_stops_worker_before_next_agent(self):
        """客户端断开 → 正在进行的 agent 完成后,后续 agent 不再启动。"""
        import web_console

        agents = _fake_agents()
        entered = threading.Event()
        release = threading.Event()
        called = []

        def nav(state):
            entered.set()
            release.wait(5)
            return {"dimension_defs": [{"id": "D1"}], "suggested_price": 1.99}

        def gen(state):
            called.append("generator")
            return {"questions_json": {}}

        agents["navigator"] = nav
        agents["generator"] = gen
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}

        gen_stream = generate_stream(cmd, "test-ip", agents=agents, heartbeat_timeout=0.1)
        next(gen_stream)  # agent_start(navigator)
        assert entered.wait(5), "navigator 未启动"
        gen_stream.close()  # 模拟客户端断开
        release.set()       # 放行 navigator,worker 应在下一 agent 前停止

        # 等待 worker 结束(_running 被 discard),再断言 generator 未被调用
        assert _wait_for(lambda: "test-ip" not in web_console._running), "worker 未在预期时间内结束"
        assert called == [], "客户端断开后 generator 仍被执行"


class _SeqAgent:
    """按顺序返回响应序列(超出后重复最后一个),记录每次收到的 state。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.states = []
        self.calls = 0

    def __call__(self, state):
        self.states.append(dict(state))
        r = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return dict(r)


class TestReviewLoop:
    def _make(self):
        agents = _fake_agents()
        gen_states = []
        gen = _SeqAgent([{"questions_json": {"questions": [{"id": 1}]}}])
        agents["generator"] = gen
        pkg = _SeqAgent([{"generated_html": "<html>v1</html>", "packaging_text": "文案一"},
                         {"generated_html": "<html>v2</html>", "packaging_text": "文案二"},
                         {"generated_html": "<html>v3</html>", "packaging_text": "文案三"}])
        agents["packager"] = pkg
        return agents, gen, pkg

    def _frames_kinds(self, agents, **kw):
        cmd = {"type": "generate", "topic": "测试", "question_count": 5, "text": "做个测试"}
        return [_e["event"] for _e in _frames(generate_stream(cmd, "test-ip", agents=agents, **kw))]

    def test_redo_uses_reviewer_fixes(self):
        """评分不达标且修复无法定向(questions 无 question_id)→ 回退全量生成并注入修复意见。"""
        agents, gen, pkg = self._make()
        rev = _SeqAgent([
            {"review_score": 4, "review_verdict": "revise", "review_retry_count": 1,
             "review_fixes_needed": [{"section": "questions", "issue": "太浅", "action": "加深"}]},
            {"review_score": 8, "review_verdict": "approve", "review_retry_count": 1, "review_fixes_needed": []},
        ])
        agents["reviewer"] = rev
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        starts = [e["agent"] for e in events if e["event"] == "agent_start"]
        assert starts.count("generator") == 2
        assert starts.count("reviewer") == 2
        assert gen.calls == 2 and rev.calls == 2
        # 回退的全量生成收到修复注入
        assert gen.states[1]["review_retry_count"] == 1
        assert gen.states[1]["review_fixes_needed"]
        # 有 step 修复提示帧;done 帧素材取最后成功一轮 pkg 的文案
        step_msgs = [e.get("message", "") for e in events if e["event"] == "step"]
        assert any("修复" in m for m in step_msgs)
        assert events[-1]["post_materials"]["copy"] == "文案二"

    def test_force_pass_after_max_retries(self):
        """恒低分 → 重做至上限(2次)后放行进 auditor/publisher。"""
        agents, gen, pkg = self._make()
        rev = _SeqAgent([
            {"review_score": 3, "review_verdict": "reject", "review_retry_count": 1, "review_fixes_needed": [{"x": 1}]},
            {"review_score": 3, "review_verdict": "reject", "review_retry_count": 2, "review_fixes_needed": [{"x": 1}]},
            {"review_score": 3, "review_verdict": "reject", "review_retry_count": 2, "review_fixes_needed": [{"x": 1}]},
        ])
        agents["reviewer"] = rev
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        assert gen.calls == 3
        assert events[-1]["event"] == "done"
        assert events[-1]["url"]

    def test_loop_bounded_when_retry_count_stalls(self):
        """reviewer 判不过但 retry_count 不递增(异常响应)→ 循环硬上限不死循环,且不反复从头生成。"""
        agents, gen, pkg = self._make()
        rev = _SeqAgent([
            {"review_score": 3, "review_verdict": "reject", "review_retry_count": 0, "review_fixes_needed": []},
        ])
        agents["reviewer"] = rev
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        # 定向轮不重跑 generator(空修复只重渲染),循环由 attempt 硬上限终止
        assert gen.calls == 1
        assert events[-1]["event"] == "done"


class TestLocalQuizUrl:
    def test_ghpages_url_maps_to_local_static(self):
        """素材 URL 从 github.io 映射为本服务 /quiz/ 静态路径(本地加载)。"""
        assert _local_quiz_url("https://KKKKupor.github.io/redbook_agent/d/2026-08-25/121436/cover.png") \
            == "/quiz/d/2026-08-25/121436/cover.png"

    def test_empty_and_unmappable_passthrough(self):
        assert _local_quiz_url("") == ""
        assert _local_quiz_url("C:/some/local/path.png") == "C:/some/local/path.png"


class TestTargetedFix:
    def test_review_fails_applies_targeted_fixes_without_regenerating(self, monkeypatch):
        """定向修复:评审点名的部分单独修,generator 不从头生成。"""
        import fix_issues as fi
        calls = []
        monkeypatch.setattr(fi, "fix_personality",
                            lambda state, llm: (calls.append("personality"), {"primary_tag": "青年感"})[1])
        monkeypatch.setattr(fi, "fix_copy",
                            lambda state, llm: (calls.append("copy"), "新文案")[1])
        monkeypatch.setattr(fi, "fix_analysis_dim",
                            lambda state, dim_id, llm: (calls.append(f"analysis:{dim_id}"),
                                                        {"dim_id": dim_id, "核心特质": "x"})[1])
        monkeypatch.setattr(fi, "fix_question",
                            lambda state, qid, issue, action, llm: (calls.append(f"q{qid}"),
                                                                    {"id": qid, "text": "t", "type": "situational", "options": []})[1])
        monkeypatch.setattr(fi, "fix_style",
                            lambda state, llm: (calls.append("style"), {"theme": "light"})[1])

        agents = _fake_agents()
        gen = _SeqAgent([{"questions_json": {"questions": [{"id": 1}, {"id": 5}]}}])
        agents["generator"] = gen
        rev = _SeqAgent([
            {"review_score": 4, "review_verdict": "revise", "review_retry_count": 1,
             "review_fixes_needed": [
                 {"section": "personality", "issue": "标签脱节", "action": "改成年龄向"},
                 {"section": "copy", "issue": "违禁词", "action": "重写"},
                 {"section": "analysis", "dim_id": "D1", "issue": "太短", "action": "重写"},
                 {"section": "questions", "question_id": 5, "issue": "负分", "action": "修复"},
             ]},
            {"review_score": 8, "review_verdict": "approve", "review_retry_count": 1, "review_fixes_needed": []},
        ])
        agents["reviewer"] = rev
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        assert gen.calls == 1, "定向修复轮不应从头生成题目"
        assert "personality" in calls and "copy" in calls and "analysis:D1" in calls and "q5" in calls
        assert rev.calls == 2
        assert events[-1]["event"] == "done"
        # 定向修复轮有 step 提示
        step_msgs = [e.get("message", "") for e in events if e["event"] == "step"]
        assert any("定向修复" in m for m in step_msgs)

    def test_unknown_section_falls_back_to_full_redo(self, monkeypatch):
        """fixes 含未知 section(如 all)→ 回退全量生成。"""
        import fix_issues as fi
        calls = []
        monkeypatch.setattr(fi, "fix_personality", lambda state, llm: (calls.append("p"), {})[1])
        agents = _fake_agents()
        gen = _SeqAgent([{"questions_json": {"questions": [{"id": 1}]}}])
        agents["generator"] = gen
        rev = _SeqAgent([
            {"review_score": 4, "review_verdict": "revise", "review_retry_count": 1,
             "review_fixes_needed": [{"section": "all", "issue": "整体质量低", "action": "重做"}]},
            {"review_score": 7, "review_verdict": "approve", "review_retry_count": 1, "review_fixes_needed": []},
        ])
        agents["reviewer"] = rev
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        assert gen.calls == 2  # 全量回退
        assert "p" not in calls  # 定向修复未执行(直接回退)
        assert events[-1]["event"] == "done"


class TestAuditorAndMaterials:
    def test_auditor_fail_publishes_anyway_with_warning(self):
        """审核 fail 不回退(web 交互场景),done 帧带 audit_warning。"""
        agents = _fake_agents()
        agents["auditor"] = lambda state: {"audit_status": "fail", "audit_feedback": "文案涉嫌夸大宣传"}
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        done = events[-1]
        assert done["event"] == "done"
        assert done["url"]
        assert done["audit_warning"] == "文案涉嫌夸大宣传"

    def test_post_materials_filters_empty_images(self):
        """截图失败(publisher 置空)→ 素材 images 为空,不掺空串。"""
        agents = _fake_agents()
        agents["publisher"] = lambda state: {"html_url": "https://example.test/d/2026-08-25/103000/",
                                             "cover_image_url": "", "result_image_url": "",
                                             "product_image_url": ""}
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        assert events[-1]["post_materials"]["images"] == []

    def test_post_materials_images_use_local_quiz_urls(self):
        """素材图 URL 映射为 /quiz/ 本地路径(不依赖 github.io 可达性)。"""
        agents = _fake_agents()
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        urls = [im["url"] for im in events[-1]["post_materials"]["images"]]
        assert urls == [
            "/quiz/d/2026-08-25/103000/cover.png",
            "/quiz/d/2026-08-25/103000/result.png",
            "/quiz/d/2026-08-25/103000/product.png",
        ]

    def test_reviewer_auditor_summaries_in_frames(self):
        """reviewer/auditor 的 agent_done 帧带评分与审核摘要。"""
        agents = _fake_agents()
        events = _frames(generate_stream({"type": "generate", "topic": "测试", "question_count": 5},
                                         "test-ip", agents=agents))
        by_agent = {e["agent"]: e for e in events if e["event"] == "agent_done"}
        assert by_agent["reviewer"]["summary"]["评分"] == 7
        assert by_agent["auditor"]["summary"]["审核"] == "pass"

    def test_navigator_interpreted_count_used_downstream(self):
        """题量以 navigator 判读值为准(用户说"五题"→ navigator 返回 5 → generator 收到 5)。"""
        agents = _fake_agents()
        seen = {}

        def nav(state):
            return {"selected_topic": "你适合什么工作",
                    "target_question_count": 5,
                    "dimension_defs": [{"id": "D1"}], "suggested_price": 1.99}

        def gen(state):
            seen["count"] = state["target_question_count"]
            return {"questions_json": {"questions": [{"id": 1}] * 5}}

        agents["navigator"] = nav
        agents["generator"] = gen
        events = _frames(generate_stream({"type": "generate", "topic": "", "question_count": 15,
                                          "text": "五题，你适合什么工作"},
                                         "test-ip", agents=agents))
        assert events[-1]["event"] == "done"
        assert seen["count"] == 5

    def test_effective_topic_from_navigator_used_downstream(self):
        """无主题输入 → navigator 池选题回传,下游 generator/packager/publisher 用池选题。"""
        agents = _fake_agents()
        seen = {}

        def gen(state):
            seen["generator"] = state["selected_topic"]
            return {"questions_json": {"questions": [{"id": 1}]}}

        def pkg(state):
            seen["packager"] = state["selected_topic"]
            return {"generated_html": "<html>x</html>", "packaging_text": "c"}

        def pub(state):
            seen["publisher"] = state["selected_topic"]
            return {"html_url": "https://example.test/d/1/"}

        agents.update(generator=gen, packager=pkg, publisher=pub)
        events = _frames(generate_stream({"type": "generate", "topic": "", "question_count": 10},
                                         "test-ip", agents=agents))
        assert events[-1]["event"] == "done"
        assert seen == {"generator": "人格阴影测试", "packager": "人格阴影测试", "publisher": "人格阴影测试"}
