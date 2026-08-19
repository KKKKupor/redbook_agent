"""Tests for main.run_once fatal path: alert sent, original exception re-raised."""

import pytest

import graph.workflow as workflow_mod
import main as main_mod
from utils import health, review
from utils.git_ops import git_ops as git_ops_singleton
from utils.notifier import notifier


class FakeApp:
    def invoke(self, *a, **kw):
        raise ValueError("模拟工作流崩溃")


class TestRunOnceFatalPath:
    # run_once binds get_app via a function-level `from graph.workflow import
    # get_app`, so the patch targets the graph.workflow module object (string-form
    # monkeypatch on dotted submodule targets fails on this pytest version).
    def test_raises_original_and_sends_fatal(self, monkeypatch):
        sends = []
        monkeypatch.setattr(workflow_mod, "get_app", lambda: FakeApp())
        monkeypatch.setattr(notifier, "send", lambda **kw: sends.append(kw))
        monkeypatch.setattr(review, "REVIEW_MODE", False)
        monkeypatch.setattr(health, "reset", lambda: None)

        with pytest.raises(ValueError, match="模拟工作流崩溃"):
            main_mod.run_once()

        fatal = [s for s in sends if s.get("level") == "fatal"]
        assert len(fatal) == 1
        assert "错误分类" in fatal[0]["content"]

    def test_review_mode_triggers_snapshot(self, monkeypatch):
        sends = []
        commits = {"v": 0}
        monkeypatch.setattr(workflow_mod, "get_app", lambda: FakeApp())
        monkeypatch.setattr(notifier, "send", lambda **kw: sends.append(kw))
        monkeypatch.setattr(review, "REVIEW_MODE", True)
        monkeypatch.setattr(health, "reset", lambda: None)
        monkeypatch.setattr(git_ops_singleton, "auto_commit",
                            lambda *a, **kw: commits.update(v=commits["v"] + 1) or "abc123def456")

        with pytest.raises(ValueError):
            main_mod.run_once()

        assert commits["v"] == 1
        fatal = [s for s in sends if s.get("level") == "fatal"]
        assert "abc123def456" in fatal[0]["content"]
