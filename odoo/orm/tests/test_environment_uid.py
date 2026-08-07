import pytest

from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime.environment import Environment


def test_uid_none_accepted():
    with model_test_env() as env:
        anonymous = Environment(env.cr, None, {})
        assert anonymous.uid is None
        assert anonymous.su is False


def test_uid_placeholder_object_accepted():

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
