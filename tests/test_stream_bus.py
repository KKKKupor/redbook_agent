"""Tests for utils.stream_bus — contextvar event bus."""

from utils import stream_bus


class FakeEmitter:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class TestStreamBus:
    def test_no_emitter_is_noop(self):
        stream_bus.emit({"event": "token", "text": "x"})  # 不得抛出

    def test_emit_reaches_current_emitter(self):
        em = FakeEmitter()
        token = stream_bus.set_emitter(em)
        try:
            stream_bus.emit({"event": "token", "text": "你好"})
            assert em.events == [{"event": "token", "text": "你好"}]
        finally:
            stream_bus.reset_emitter(token)

    def test_reset_restores_noop(self):
        em = FakeEmitter()
        token = stream_bus.set_emitter(em)
        stream_bus.reset_emitter(token)
        stream_bus.emit({"event": "token"})  # no-op,不抛
        assert em.events == []
