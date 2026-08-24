from __future__ import annotations

import logging
import typing
from inspect import getmembers

from odoo.libs.profiling import _OrmProfile

from ... import decorators as api
from ...helpers import own_class_memo
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

_logger = logging.getLogger("odoo.models")
_orm_crud = logging.getLogger("odoo.orm.crud")


class _ConstraintsMixin(_ModelStubs):
    __slots__ = ()

    @property
    def _constraint_methods(self) -> list:

        def is_constraint(func):
            return callable(func) and hasattr(func, "_constrains")

        def wrap(func, names):
            sudo_flag = getattr(func, "_constrains_sudo", True)

            @api.constrains(*names, sudo=sudo_flag)
            def wrapper(self):
                return func(self)

            return wrapper

        cls = self.env.registry[self._name]

        def build():
            methods = []
            for attr, func in getmembers(cls, is_constraint):
                if callable(func._constrains):
                    func = wrap(func, func._constrains(self.sudo()))
                for name in func._constrains:
                    field = cls._fields.get(name)
                    if not field:
                        _logger.warning(
                            "method %s.%s: @constrains parameter %r is not a field name",
                            cls._name,
                            attr,
                            name,
                        )
                    elif not (field.store or field.inverse or field.inherited):
                        _logger.warning(
                            "method %s.%s: @constrains parameter %r is not writeable",
                            cls._name,
                            attr,
                            name,
                        )
                methods.append(func)
            return methods

        return own_class_memo(cls, "_constraint_methods__", build)

    def _validate_fields(
        self, field_names: Iterable[str], excluded_names: Iterable[str] = ()
    ) -> None:
        methods = self._constraint_methods
        if not methods:
            return

        prof = _OrmProfile(_orm_crud)
        _count = 0

        records_sudo = self.sudo()
        records_user = self
        field_names = set(field_names)
        excluded_names = set(excluded_names)
        for check in methods:
            if not field_names.isdisjoint(
                check._constrains
            ) and excluded_names.isdisjoint(check._constrains):
                use_sudo = getattr(check, "_constrains_sudo", True)
                check(records_sudo if use_sudo else records_user)
                if prof.debug:
                    _count += 1

        prof.stop()
        prof.report(
            _orm_crud, "_validate_fields %s: %d constraints", self._name, _count
        )
