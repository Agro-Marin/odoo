"""``Registry.init_phase`` is open only during ``init_models()``.

Four attributes used to be created in ``init_models``' ``try:`` and ``del``-eted
in its ``finally:``, reached from six sites outside ``registry.py`` -- five of
them in Layer 1. Nothing declared the ordering, and violating it produced
``AttributeError: 'Registry' object has no attribute '_post_init_queue'``, which
names neither the caller nor the rule.

These pin what replaced it: one nullable attribute, a named error, and the two
entry points Layer 1 actually uses.
"""

import pytest

from odoo.orm.runtime._init_phase import InitModelsPhase


class _FakeRegistry:
    """The two members ``Registry.init_phase`` and its callers touch.

    A real ``Registry`` needs a database; the property under test needs one
    attribute. Bound from the real class so the test cannot drift from it.
    """

    def __init__(self, phase=None):
        self._init_phase = phase

    from odoo.orm.runtime.registry import Registry as _R

    init_phase = _R.init_phase
    post_init = _R.post_init
    add_relation_reflection = _R.add_relation_reflection
    del _R


class TestPhaseIsClosedByDefault:
    def test_reading_it_outside_the_window_raises_a_named_error(self):
        with pytest.raises(RuntimeError, match="only available while init_models"):
            _FakeRegistry().init_phase

    def test_the_error_says_what_the_window_is_for(self):
        """The old AttributeError named a private attribute and nothing else."""
        with pytest.raises(RuntimeError) as caught:
            _FakeRegistry().init_phase
        message = str(caught.value)
        assert "init_models()" in message
        assert "post-init queue" in message

    def test_post_init_outside_the_window_raises_the_same_error(self):
        with pytest.raises(RuntimeError, match="only available while init_models"):
            _FakeRegistry().post_init(lambda: None)

    def test_add_relation_reflection_outside_the_window_raises_it_too(self):
        """The one site that used to write into the phase set directly."""
        with pytest.raises(RuntimeError, match="only available while init_models"):
            _FakeRegistry().add_relation_reflection("a.model", "a_rel", "base")


class TestPhaseWhileOpen:
    def test_post_init_queues_in_call_order(self):
        registry = _FakeRegistry(InitModelsPhase(install=True))
        seen = []
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
        """``post_constraint`` branches on it to decide error vs retry."""
        assert _FakeRegistry(InitModelsPhase(install=True)).init_phase.install is True
        assert _FakeRegistry(InitModelsPhase(install=False)).init_phase.install is False

    def test_each_phase_starts_empty(self):
        """No shared mutable default across runs -- the collections are fields
        with default_factory, not class attributes."""
        first = InitModelsPhase(install=True)
        first.post_init_queue.append(lambda: None)
        first.foreign_keys[("t", "c")] = ("t2", "c2", "cascade", None, "base")
        second = InitModelsPhase(install=True)
        assert not second.post_init_queue
        assert not second.foreign_keys
        assert not second.relation_reflections
