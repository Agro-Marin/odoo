from collections.abc import Callable
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

    def post_init(self, func: Callable, *args, **kwargs) -> None:
        self.init_phase.post_init_queue.append(partial(func, *args, **kwargs))

    def add_relation_reflection(
        self, model_name: str, relation: str, module: str
    ) -> None:
        self.init_phase.relation_reflections.add((model_name, relation, module))
