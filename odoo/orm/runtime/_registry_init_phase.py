from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial

from ._init_phase import InitModelsPhase
from ._registry_stubs import _RegistryStubs


class _RegistryInitPhaseMixin(_RegistryStubs):
    __slots__ = ()

    _init_phase: InitModelsPhase | None

    def _init_phase_state(self) -> None:
        self._init_phase = None

    @property
    def init_phase(self) -> InitModelsPhase:
        if self._init_phase is None:
            raise RuntimeError(
                "Registry.init_phase is only available while init_models() is "
                "running: it holds state for one module-initialisation pass "
                "(the post-init queue, the foreign keys to reconcile, the "
                "many2many relations to reflect). A caller reaching it outside "
                "that window -- typically a field's update_db() run at some "
                "other time -- is the bug."
            )
        return self._init_phase

    @contextmanager
    def init_models_window(self, install: bool) -> Iterator[InitModelsPhase]:
        if self._init_phase is not None:
            raise RuntimeError(
                "Registry.init_models_window() cannot be nested: one "
                "module-initialisation pass is already open"
            )
        self._init_phase = InitModelsPhase(install=install)
        try:
            yield self._init_phase
            self.drain_post_init()
        finally:
            self._init_phase = None

    def drain_post_init(self) -> None:
        post_init_queue = self.init_phase.post_init_queue
        while post_init_queue:
            post_init_queue.popleft()()

    def post_init(self, func: Callable, *args, **kwargs) -> None:
        self.init_phase.post_init_queue.append(partial(func, *args, **kwargs))

    def add_relation_reflection(
        self, model_name: str, relation: str, module: str | None
    ) -> None:
        self.init_phase.relation_reflections.add((model_name, relation, module))
