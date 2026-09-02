import typing

import pytest

from odoo.orm.runtime._init_phase import InitModelsPhase


class _FakeRegistry:
    def __init__(self, phase=None):
        self._init_phase = phase

    from odoo.orm.runtime.registry import Registry as _R

    init_phase: typing.Any = _R.init_phase
    post_init: typing.Any = _R.post_init
    add_relation_reflection: typing.Any = _R.add_relation_reflection
    init_models_window: typing.Any = _R.init_models_window
    drain_post_init: typing.Any = _R.drain_post_init
    del _R


class TestPhaseIsClosedByDefault:
    def test_reading_it_outside_the_window_raises_a_named_error(self):
        with pytest.raises(RuntimeError, match="only available while init_models"):
            _FakeRegistry().init_phase

    def test_the_error_says_what_the_window_is_for(self):
        with pytest.raises(RuntimeError) as caught:
            _FakeRegistry().init_phase
        message = str(caught.value)
        assert "init_models()" in message
        assert "post-init queue" in message

    def test_post_init_outside_the_window_raises_the_same_error(self):
        with pytest.raises(RuntimeError, match="only available while init_models"):
            _FakeRegistry().post_init(lambda: None)

    def test_add_relation_reflection_outside_the_window_raises_it_too(self):
        with pytest.raises(RuntimeError, match="only available while init_models"):
            _FakeRegistry().add_relation_reflection("a.model", "a_rel", "base")


class TestPhaseWhileOpen:
    def test_post_init_queues_in_call_order(self):
        registry = _FakeRegistry(InitModelsPhase(install=True))
        seen: list = []
        registry.post_init(seen.append, 1)
        registry.post_init(seen.append, 2)
        queue = registry.init_phase.post_init_queue
        assert len(queue) == 2
        while queue:
            queue.popleft()()
        assert seen == [1, 2]

    def test_post_init_passes_through_args_and_kwargs(self):
        registry = _FakeRegistry(InitModelsPhase(install=False))
        captured = {}

        def record(a, b=None):
            captured["a"], captured["b"] = a, b

        registry.post_init(record, "x", b="y")
        registry.init_phase.post_init_queue.popleft()()
        assert captured == {"a": "x", "b": "y"}

    def test_relation_reflections_dedupe_and_keep_order(self):
        registry = _FakeRegistry(InitModelsPhase(install=True))
        registry.add_relation_reflection("m.one", "rel_a", "base")
        registry.add_relation_reflection("m.two", "rel_b", "base")
        registry.add_relation_reflection("m.one", "rel_a", "base")
        assert list(registry.init_phase.relation_reflections) == [
            ("m.one", "rel_a", "base"),
            ("m.two", "rel_b", "base"),
        ]

    def test_install_flag_is_carried(self):
        assert _FakeRegistry(InitModelsPhase(install=True)).init_phase.install is True
        assert _FakeRegistry(InitModelsPhase(install=False)).init_phase.install is False

    def test_each_phase_starts_empty(self):
        first = InitModelsPhase(install=True)
        first.post_init_queue.append(lambda: None)
        first.foreign_keys[("t", "c")] = typing.cast(
            "typing.Any", ("t2", "c2", "cascade", None, "base")
        )
        second = InitModelsPhase(install=True)
        assert not second.post_init_queue
        assert not second.foreign_keys
        assert not second.relation_reflections


class TestTheWindow:
    def test_it_opens_the_phase_and_closes_it_again(self):
        registry = _FakeRegistry()
        with registry.init_models_window(install=True) as phase:
            assert registry.init_phase is phase
            assert phase.install is True
        with pytest.raises(RuntimeError, match="only available while init_models"):
            registry.init_phase

    def test_a_clean_exit_drains_the_post_init_queue(self):
        registry = _FakeRegistry()
        ran: list[str] = []
        with registry.init_models_window(install=False):
            registry.post_init(ran.append, "first")
            registry.post_init(ran.append, "second")
            assert ran == []
        assert ran == ["first", "second"]

    def test_an_exception_closes_the_window_without_draining(self):
        registry = _FakeRegistry()
        ran: list[str] = []
        with pytest.raises(ValueError), registry.init_models_window(install=False):
            registry.post_init(ran.append, "never")
            raise ValueError("boom")
        assert ran == []
        assert registry._init_phase is None

    def test_it_cannot_be_nested(self):
        registry = _FakeRegistry()
        with (
            registry.init_models_window(install=False),
            pytest.raises(RuntimeError, match="cannot be nested"),
            registry.init_models_window(install=False),
        ):
            pass

    def test_draining_mid_window_leaves_nothing_for_the_exit(self):
        registry = _FakeRegistry()
        ran: list[str] = []
        with registry.init_models_window(install=False):
            registry.post_init(ran.append, "early")
            registry.drain_post_init()
            assert ran == ["early"]
            registry.post_init(ran.append, "late")
        assert ran == ["early", "late"]
