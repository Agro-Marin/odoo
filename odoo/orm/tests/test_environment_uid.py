"""Pins for ``Environment.__new__`` uid validation.

Tier-2 suite: real ``import odoo``, in-memory cursor, no database.

The uid contract is deliberately loose — int (a real user), ``None``
(LOAD-BEARING for anonymous dispatch: an environment is built before
authentication resolves a user), or an opaque placeholder object (ir.http's
``RequestUID`` during route matching, replaced by a real uid before any
user-dependent work). Only ``bool`` is rejected: True == 1 == SUPERUSER_ID
would silently elevate to superuser. A stricter int-or-None check was tried
and reverted — it broke every model-converter route (vcard, /odoo/action-*/new,
/html_editor/modify_image) by rejecting the RequestUID placeholder.
"""

import pytest

from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime.environment import Environment


def test_uid_none_accepted():
    with model_test_env() as env:
        anonymous = Environment(env.cr, None, {})
        assert anonymous.uid is None
        assert anonymous.su is False


def test_uid_placeholder_object_accepted():
    """The RequestUID pattern: an opaque object stands in for the uid while
    werkzeug route converters run, without superuser elevation."""

    class _RequestUIDLike:
        pass

    with model_test_env() as env:
        placeholder = _RequestUIDLike()
        e = Environment(env.cr, placeholder, {})
        assert e.uid is placeholder
        assert e.su is False


def test_uid_bool_rejected():
    with model_test_env() as env:
        with pytest.raises(TypeError):
            Environment(env.cr, True, {})
        with pytest.raises(TypeError):
            Environment(env.cr, False, {})


def test_uid_int_accepted():
    with model_test_env() as env:
        assert Environment(env.cr, 1, {}).uid == 1
