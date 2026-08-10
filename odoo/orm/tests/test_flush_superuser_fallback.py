import logging

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime.environment import Environment
from odoo.orm.runtime.transaction import Transaction

_MOD = "test_orm_flush_fallback"


class FlushWidget(models.Model):
    _name = "flush.widget"
    _module = _MOD
    _description = "Flush Widget"

    name = fields.Char()


class _PreAuthTransaction:
    def __init__(self, env):
        self._cr = env.cr
        self._root_tx = env.transaction
        self.tx = Transaction(self._root_tx.registry)

    def __enter__(self):
        self._cr.transaction = self.tx
        self.anon = Environment(self._cr, None, {})
        assert list(self.tx.envs), "the pre-auth env was collected"
        assert self.tx.default_env is None, "uid=None must not install a default_env"
        return self.tx

    def __exit__(self, *exc):
        self._cr.transaction = self._root_tx
        return False


def test_fallback_does_not_install_itself_as_default_env():
    with model_test_env(FlushWidget) as env, _PreAuthTransaction(env) as tx:
        tx.flush()
        assert tx.default_env is None, (
            "the SUPERUSER fallback became the transaction's default_env, so "
            "every later flush silently runs as superuser with no warning"
        )


def test_warning_fires_on_every_fallback_flush_not_just_the_first(caplog):
    with model_test_env(FlushWidget) as env, _PreAuthTransaction(env) as tx:
        with caplog.at_level(logging.WARNING, logger="odoo.api"):
            for _ in range(3):
                tx.flush()
        warnings = [r for r in caplog.records if "flushing as SUPERUSER" in r.message]
        assert len(warnings) == 3, (
            f"expected the fallback to warn on each of 3 flushes, got "
            f"{len(warnings)}. A warning that disables itself is worse than no "
            f"warning: it reads as 'happened once' when it is still happening."
        )


def test_a_real_default_env_is_left_alone():
    with model_test_env(FlushWidget) as env:
        tx = env.transaction
        assert tx.default_env is not None
        original = tx.default_env
        tx.flush()
        assert tx.default_env is original


def test_harness_root_env_does_not_take_the_fallback_path(caplog):
    with model_test_env(FlushWidget) as env:
        with caplog.at_level(logging.WARNING, logger="odoo.api"):
            env.transaction.flush()
        assert not [r for r in caplog.records if "SUPERUSER" in r.message]


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
