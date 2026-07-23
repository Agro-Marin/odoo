"""Pins for ``Environment.__new__`` uid validation.

Tier-2 suite: real ``import odoo``, in-memory cursor, no database.

``uid=None`` is LOAD-BEARING for anonymous dispatch (an environment is built
before authentication resolves a user) and must stay legal; any other non-int
uid is a programming error and raises ``TypeError``; ``bool`` was already
rejected (True == 1 == SUPERUSER_ID would silently elevate to superuser) and
stays rejected.
"""

import pytest

from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime.environment import Environment


def test_uid_none_accepted():
    with model_test_env() as env:
        anonymous = Environment(env.cr, None, {})
        assert anonymous.uid is None
        assert anonymous.su is False


def test_uid_string_rejected():
    with model_test_env() as env:
        with pytest.raises(TypeError, match="int or None"):
            Environment(env.cr, "1", {})


def test_uid_float_rejected():
    with model_test_env() as env:
        with pytest.raises(TypeError, match="int or None"):
            Environment(env.cr, 1.0, {})


def test_uid_bool_rejected():
    with model_test_env() as env:
        with pytest.raises(TypeError):
            Environment(env.cr, True, {})
        with pytest.raises(TypeError):
            Environment(env.cr, False, {})


def test_uid_int_accepted():
    with model_test_env() as env:
        assert Environment(env.cr, 1, {}).uid == 1
