from __future__ import annotations

import functools
import logging
from collections import defaultdict
from inspect import getmembers

from ...helpers import own_class_memo
from ._model_stubs import _ModelStubs

_logger = logging.getLogger("odoo.models")


class _HooksMixin(_ModelStubs):
    __slots__ = ()

    @property
    def _ondelete_methods(self) -> list:
        def is_ondelete(func):
            return callable(func) and hasattr(func, "_ondelete")

        cls = self.env.registry[self._name]
        return own_class_memo(
            cls,
            "_ondelete_methods__",
            lambda: [func for _, func in getmembers(cls, is_ondelete)],
        )

    @property
    def _onchange_methods(self) -> dict[str, list]:
        def is_onchange(func):
            return callable(func) and hasattr(func, "_onchange")

        cls = self.env.registry[self._name]

        def build():
            methods = defaultdict(list)
            for _attr, func in getmembers(cls, is_onchange):
                missing = []
                for name in func._onchange:
                    if name in cls._fields:
                        methods[name].append(func)
                    else:
                        missing.append(name)
                if missing:
                    _logger.warning(
                        "@api.onchange%r parameters must be field names -> not valid: %s",
                        func._onchange,
                        missing,
                    )

            def onchange_default(field, self):
                value = field.convert_to_write(self[field.name], self)
                condition = f"{field.name}={value}"
                defaults = self.env["ir.default"]._get_model_defaults(
                    self._name, condition
                )
                self.update(defaults)

            for name, field in cls._fields.items():
                if field.change_default:
                    methods[name].append(functools.partial(onchange_default, field))

            return dict(methods)

        return own_class_memo(cls, "_onchange_methods__", build)
