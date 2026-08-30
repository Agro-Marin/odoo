import contextlib
import importlib
import logging
import unittest
from collections import defaultdict
from functools import wraps
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import freezegun

import odoo.cli
from odoo import api
from odoo.fields import Command
from odoo.tools import (
    config,
    mute_logger,
)
from odoo.tools.cache import _COUNTERS
from odoo.tools.mail import single_email_re
from odoo.tools.xml_utils import _check_xml

from .browser import DEFAULT_SUCCESS_SIGNAL, ChromeBrowser, ChromeBrowserException
from .case import TestCase
from .matchers import Approx, Like, RecordCapturer, WhitespaceInsensitive
from .transaction_case import (
    TEST_CURSOR_COOKIE_NAME,
    BaseCase,
    BlockedRequest,
    SingleTransactionCase,
    TransactionCase,
    _registry_test_lock,
    gc_test_filestore,
    release_stranded_test_cursors,
    release_test_lock,
)
from .utils import HOST, get_db_name, save_test_file

if TYPE_CHECKING:
    from collections.abc import Callable

    from .http import HttpCase, JsonRpcException, Opener, Transport


__all__ = [
    "ADMIN_USER_ID",
    "DEFAULT_SUCCESS_SIGNAL",
    "HOST",
    "TEST_CURSOR_COOKIE_NAME",
    "Approx",
    "BaseCase",
    "BlockedRequest",
    "ChromeBrowser",
    "ChromeBrowserException",
    "Command",
    "HttpCase",
    "JsonRpcException",
    "Like",
    "Opener",
    "RecordCapturer",
    "SingleTransactionCase",
    "TransactionCase",
    "Transport",
    "WhitespaceInsensitive",
    "can_import",
    "freeze_time",
    "gc_test_filestore",
    "get_cache_key_counter",
    "get_db_name",
    "loaded_demo_data",
    "mute_logger",
    "new_test_user",
    "no_retry",
    "patch",
    "release_stranded_test_cursors",
    "release_test_lock",
    "save_test_file",
    "skip_if_dev_mode",
    "standalone",
    "standalone_tests",
    "tagged",
    "test_xsd",
    "users",
    "warmup",
]

_logger = logging.getLogger(__name__)
if odoo.cli.COMMAND in ("server", "start") and not config["test_enable"]:
    _logger.error(
        "Importing test framework, avoid importing from business modules and when not running in test mode",
        stack_info=True,
    )
else:
    _logger.info(
        "Importing test framework",
        stack_info=_logger.isEnabledFor(logging.DEBUG),
    )


def get_cache_key_counter(bound_method, *args, **kwargs):
    model = bound_method.__self__
    ormcache_instance = bound_method.__cache__
    cache = model.pool.ormcache_lrus[ormcache_instance.cache_name]
    key = ormcache_instance.key(model, *args, **kwargs)
    counter = _COUNTERS[model.pool.db_name, ormcache_instance.method]
    return cache, key, counter


ADMIN_USER_ID = api.SUPERUSER_ID


def skip_if_dev_mode(*flags: str) -> None:
    dev_mode = config["dev_mode"]
    if active := [flag for flag in flags if flag in dev_mode]:
        raise unittest.SkipTest(
            f"--dev={','.join(active)} disables the behaviour under test"
        )


standalone_tests: defaultdict[str, list] = defaultdict(list)


_registry_test_lock.acquire()


def standalone(*tags: str) -> Callable[[Callable], Callable]:

    def register(func: Callable) -> Callable:
        if func.__module__.startswith("odoo.addons."):
            module = func.__module__.split(".")[2]
            standalone_tests[module].append(func)
        for tag in tags:
            standalone_tests[tag].append(func)
        standalone_tests["all"].append(func)
        return func

    return register


def test_xsd(url=None, path=None, skip=False, xsd_name=None):
    def decorator(func):
        @wraps(func)
        def wrapped_f(self, *args, **kwargs):
            if skip:
                raise unittest.SkipTest(
                    skip if isinstance(skip, str) else "XSD validation disabled"
                )
            xmls = func(self, *args, **kwargs)
            _check_xml(self.env, url, path, xmls, xsd_name)

        return wrapped_f

    return decorator


def new_test_user(env, login="", groups="base.group_user", context=None, **kwargs):
    if not login:
        raise ValueError("New users require at least a login")
    if not groups:
        raise ValueError("New users require at least user groups")
    if context is None:
        context = {}

    group_ids = [
        Command.set(
            kwargs.pop("group_ids", False)
            or [env.ref(g.strip()).id for g in groups.split(",")]
        )
    ]
    create_values = dict(kwargs, login=login, group_ids=group_ids)
    if not create_values.get("name"):
        create_values["name"] = f"{login} ({groups})"
    if not create_values.get("password"):
        create_values["password"] = login + "x" * (8 - len(login))
    if "email" not in create_values:
        if single_email_re.match(login):
            create_values["email"] = login
        else:
            create_values["email"] = f"{login[0]}.{login[0]}@example.com"
    if "company_id" in create_values and "company_ids" not in create_values:
        create_values["company_ids"] = [(4, create_values["company_id"])]

    return env["res.users"].with_context(**context).create(create_values)


def loaded_demo_data(env: api.Environment) -> bool:
    return bool(env.ref("base.user_demo", raise_if_not_found=False))


def no_retry(arg: Any) -> Any:
    arg._retry = False
    return arg


def users(*logins: str) -> Callable:
    assert logins, "Expecting at least one login to execute"

    def users_decorator(func: Callable, /) -> Callable:
        @wraps(func)
        def with_users(self: Any, *args: Any, **kwargs: Any) -> None:
            old_uid = self.uid
            try:
                Users = self.env["res.users"].with_context(active_test=False)
                user_id = {
                    user.login: user.id
                    for user in Users.search([("login", "in", list(logins))])
                }
                missing = [login for login in logins if login not in user_id]
                assert not missing, f"No user with login {missing}"
                for login in logins:
                    with self.subTest(login=login):
                        self.uid = user_id[login]
                        func(self, *args, **kwargs)
                        self.env.flush_all()
                    self.env.invalidate_all()
            finally:
                self.uid = old_uid

        return with_users

    return users_decorator


def warmup(func: Callable, /) -> Callable:

    @wraps(func)
    def warmup(self: Any, *args: Any, **kwargs: Any) -> None:
        self.env.flush_all()
        self.env.invalidate_all()
        self.warm = False
        with contextlib.closing(self.cr.savepoint(flush=False)):
            func(self, *args, **kwargs)
            self.env.flush_all()
        self.env.invalidate_all()
        self.warm = True
        func(self, *args, **kwargs)

    return warmup


def can_import(module: str) -> bool:
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    else:
        return True


def tagged(*tags: str) -> Callable:
    include = {t for t in tags if not t.startswith("-")}
    exclude = {t[1:] for t in tags if t.startswith("-")}

    def tags_decorator(target: Any) -> Any:
        obj: Any = target
        if not isinstance(target, type):
            obj.test_tags = getattr(obj, "test_tags", set()) | include
            obj.test_tags_exclude = getattr(obj, "test_tags_exclude", set()) | exclude
            return obj

        obj.test_tags = (getattr(obj, "test_tags", set()) | include) - exclude
        at_install = "at_install" in obj.test_tags
        post_install = "post_install" in obj.test_tags
        if not (at_install ^ post_install):
            _logger.warning(
                "A tests should be either at_install or post_install, which is not the case of %r",
                obj,
            )
        return obj

    return tags_decorator


class freeze_time:
    _freeze_time = staticmethod(freezegun.freeze_time)

    def __init__(
        self,
        time_to_freeze: Any = None,
        tz_offset: int = 0,
        ignore: list[str] | None = None,
        tick: bool = False,
        as_arg: bool = False,
        as_kwarg: str = "",
        auto_tick_seconds: float = 0,
        real_asyncio: bool = False,
    ) -> None:
        self.freezer = self._freeze_time(
            time_to_freeze=time_to_freeze,
            tz_offset=tz_offset,
            ignore=ignore,
            tick=tick,
            as_arg=as_arg,
            as_kwarg=as_kwarg,
            auto_tick_seconds=auto_tick_seconds,
            real_asyncio=real_asyncio,
        )

    def __call__(self, arg: Any) -> Any:
        target: Any = arg
        if isinstance(arg, type) and issubclass(arg, TestCase):
            target.freeze_time = self
            return target

        return self.freezer(arg)

    def __enter__(self) -> Any:
        return self.freezer.start()

    def __exit__(self, *args: object) -> None:
        self.freezer.stop()

    start = __enter__
    stop = __exit__


freezegun.freeze_time = freeze_time

_HTTP_EXPORTS = ("HttpCase", "JsonRpcException", "Opener", "Transport")
"""Names this module publishes on behalf of :mod:`odoo.tests.http`."""


def __getattr__(name: str) -> Any:
    if name in _HTTP_EXPORTS:
        from . import http

        globals().update({export: getattr(http, export) for export in _HTTP_EXPORTS})
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *_HTTP_EXPORTS})
